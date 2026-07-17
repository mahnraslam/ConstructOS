import os
import re
import json
import logging
import base64
from google import genai
from dotenv import load_dotenv

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
load_dotenv(_ENV_PATH, override=True)

logger = logging.getLogger(__name__)

_API_KEY = os.getenv("GEMINI_API_KEY", "")
if not _API_KEY or _API_KEY in ("your_key_here", "your_gemini_api_key_here", "test-key"):
    logger.warning("[gemini] GEMINI_API_KEY is not set or is a placeholder. Embeddings will fail.")

_client = genai.Client(api_key=_API_KEY)
_GEN_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").removeprefix("models/")
_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001").removeprefix("models/")

# ── Groq setup (used for ALL text generation) ─────────────────────────────────
_GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
_GROQ_MODEL   = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
_groq_client  = None

if _GROQ_API_KEY:
    try:
        from groq import Groq
        _groq_client = Groq(api_key=_GROQ_API_KEY)
        logger.info(f"[groq] Ready — model: {_GROQ_MODEL}  |  embed: {_EMBED_MODEL} (Gemini)")
    except Exception as e:
        logger.warning(f"[groq] Init failed: {e} — will fall back to Gemini for generation")
else:
    logger.warning("[groq] GROQ_API_KEY not set — generation will use Gemini (may hit quota)")

# Issue 6 fix: always log which provider is actually active, regardless of
# which branch above was taken (previously this only logged in the "no groq
# key" branch, so the common case — Groq configured and ready — never logged
# which provider was serving generation requests).
if _groq_client:
    logger.info(f"ACTIVE GENERATION PROVIDER: Groq/{_GROQ_MODEL}")
else:
    logger.info(f"ACTIVE GENERATION PROVIDER: Gemini/{_GEN_MODEL}")

MAX_RETRIES = 2
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "100"))
MAX_EMBED_CHARS = 8000


# ── Embeddings — always Gemini ────────────────────────────────────────────────

def _split_for_embedding(text: str, max_chars: int = MAX_EMBED_CHARS) -> list[str]:
    """Split text into <= max_chars segments instead of silently truncating.

    Issue 4 fix: the previous implementation truncated any text over 8000
    chars, which could silently drop dimensions, notes, or specifications
    that appeared near the end of a chunk. Splitting (and, in embed_text,
    averaging the resulting vectors) keeps the full content in play instead
    of throwing part of it away.
    """
    if len(text) <= max_chars:
        return [text]
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]


def _average_vectors(vectors: list[list[float]]) -> list[float]:
    if len(vectors) == 1:
        return vectors[0]
    dim = len(vectors[0])
    avg = [0.0] * dim
    for v in vectors:
        for i, val in enumerate(v):
            avg[i] += val
    n = len(vectors)
    return [x / n for x in avg]


def embed_text(text: str) -> list[float]:
    segments = _split_for_embedding(text)
    if len(segments) > 1:
        logger.warning(
            f"[gemini] Text of {len(text)} chars exceeds {MAX_EMBED_CHARS} — "
            f"split into {len(segments)} segments and averaged instead of truncating"
        )
    vectors = []
    for seg in segments:
        result = _client.models.embed_content(model=_EMBED_MODEL, contents=seg)
        vectors.append(result.embeddings[0].values)
    return _average_vectors(vectors)


def _embed_batch_with_retry(batch: list[str]) -> list[list[float]] | None:
    """Try to embed a batch of texts using the batch API, with retries.
    Oversized texts are pulled out and embedded individually via embed_text
    (which splits + averages) instead of being truncated in place.
    Returns None if all retries fail."""
    oversized = [i for i, t in enumerate(batch) if len(t) > MAX_EMBED_CHARS]
    batch_indices = [i for i in range(len(batch)) if i not in set(oversized)]
    batch_texts = [batch[i] for i in batch_indices]

    results: list[list[float] | None] = [None] * len(batch)

    if oversized:
        logger.warning(
            f"[gemini] {len(oversized)} text(s) in batch exceed {MAX_EMBED_CHARS} chars — "
            f"embedding individually (segment + average) instead of truncating"
        )
        for i in oversized:
            try:
                results[i] = embed_text(batch[i])
            except Exception as e:
                logger.error(f"[gemini] Individual embedding failed for oversized text at index {i}: {e}")
                return None

    if batch_texts:
        last_err = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                result = _client.models.embed_content(model=_EMBED_MODEL, contents=batch_texts)
                for pos, i in enumerate(batch_indices):
                    results[i] = result.embeddings[pos].values
                last_err = None
                break
            except Exception as e:
                last_err = e
                if attempt < MAX_RETRIES:
                    import time
                    wait = 2 ** attempt
                    logger.warning(f"[gemini] Batch embed retry {attempt+1}/{MAX_RETRIES} for batch of {len(batch)} texts: {e}")
                    time.sleep(wait)
                else:
                    logger.error(f"[gemini] Batch embedding failed after {MAX_RETRIES} retries for batch of {len(batch)} texts: {e}")
        if last_err is not None:
            return None

    return results  # type: ignore[return-value]


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts using batching, with fallback to individual embeddings."""
    embeddings: list[list[float]] = []

    # Process in batches
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i:i + EMBED_BATCH_SIZE]
        batch_embeddings = _embed_batch_with_retry(batch)
        if batch_embeddings is not None:
            embeddings.extend(batch_embeddings)
        else:
            # Fallback to embedding each text individually
            logger.warning(f"[gemini] Batch embedding failed for batch starting at index {i}, falling back to individual embeddings")
            for j, text in enumerate(batch):
                try:
                    emb = embed_text(text)
                    embeddings.append(emb)
                except Exception as e:
                    logger.error(f"[gemini] Failed to embed text at index {i+j}: {e}")
                    raise  # Re-raise to be consistent with the old behavior
    return embeddings


# ── Text generation — Groq primary, Gemini fallback ──────────────────────────

def generate(prompt: str) -> str:
    if _groq_client:
        return _groq_generate(prompt)
    return _gemini_generate(prompt)


def _groq_generate(prompt: str) -> str:
    import time
    for attempt in range(3):
        try:
            resp = _groq_client.chat.completions.create(
                model=_GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.1,
            )
            return resp.choices[0].message.content
        except Exception as e:
            err = str(e)
            retryable = "429" in err or "rate_limit" in err.lower() or "503" in err
            if retryable and attempt < 2:
                wait = 30 * (2 ** attempt)
                logger.warning(f"[groq] Rate limit, waiting {wait}s (attempt {attempt+1}/3): {err[:120]}")
                time.sleep(wait)
                continue
            logger.error(f"[groq] Failed: {e} — falling back to Gemini")
            return _gemini_generate(prompt)
    return _gemini_generate(prompt)


def _gemini_generate(prompt: str, json_mode: bool = False) -> str:
    import time
    for attempt in range(3):
        try:
            kwargs = {"model": _GEN_MODEL, "contents": prompt}
            if json_mode:
                # Issue 3 fix: ask Gemini for a structured JSON response instead
                # of relying purely on prompt wording. Gemini's JSON mode
                # supports arbitrary JSON shapes (including top-level arrays),
                # unlike some other providers whose JSON mode is object-only.
                kwargs["config"] = {"response_mime_type": "application/json"}
            return _client.models.generate_content(**kwargs).text
        except Exception as e:
            err = str(e)
            retryable = ("429" in err or "RESOURCE_EXHAUSTED" in err
                         or "503" in err or "UNAVAILABLE" in err
                         or "overloaded" in err.lower())
            if retryable and attempt < 2:
                m = re.search(r"retryDelay.*?['\"](\d+)s['\"]", err)
                wait = int(m.group(1)) if m else 30 * (2 ** attempt)
                logger.warning(f"[gemini] Retryable error, waiting {wait}s (attempt {attempt+1}/3): {err[:120]}")
                time.sleep(wait)
                continue
            logger.error(f"[gemini] Generation failed: {e}")
            return f"[LLM error: {e}]"
    return "[LLM error: max retries exceeded]"


def generate_json(prompt: str):
    """
    Generate a response constrained/intended to be JSON and return the
    *parsed* Python object (list or dict) — not a raw string.

    Issue 1 fix: previously this returned a cleaned string, forcing every
    caller to run its own json.loads() (and duplicate the markdown-fence
    stripping). Now invalid JSON is caught in one place.

    Issue 3 fix: when the active/fallback path is pure Gemini, ask for a
    structured JSON response via response_mime_type. Groq's JSON mode is
    object-shaped only and would break our array-shaped extraction prompts,
    so for Groq we keep the existing prompt-based "respond with ONLY a JSON
    array" approach and rely on generate()'s normal Groq→Gemini fallback.
    """
    if _groq_client:
        raw = generate(prompt)
    else:
        raw = _gemini_generate(prompt, json_mode=True)

    if raw.startswith("[LLM error:") or raw.startswith("[Gemini error:"):
        raise ValueError(f"LLM generation failed: {raw}")

    cleaned = re.sub(r'^```(?:json)?\s*\n?', '', raw.strip())
    cleaned = re.sub(r'\n?```\s*$', '', cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM did not return valid JSON: {e} — raw: {cleaned[:200]!r}") from e


def generate_with_images(prompt: str, image_paths: list[str]) -> str:
    """Multimodal — uses Gemini (Groq has no vision). Falls back to Groq text-only on quota error."""
    content: list = []
    loaded = 0
    for path in image_paths:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "rb") as f:
                data = base64.b64encode(f.read()).decode("utf-8")
            content.append({"mime_type": "image/png", "data": data})
            loaded += 1
        except Exception as e:
            logger.warning(f"[gemini] Could not load image {path}: {e}")

    if loaded == 0:
        logger.warning("[gemini] No images loaded — falling back to text-only")
        return generate(prompt)

    content.append(prompt)
    try:
        logger.info(f"[gemini] Multimodal generation with {loaded} image(s)")
        return _client.models.generate_content(model=_GEN_MODEL, contents=content).text
    except Exception as e:
        logger.warning(f"[gemini] Multimodal failed ({e}) — falling back to text-only")
        return generate(prompt)


def describe_blueprint_page(image_path: str) -> str:
    """Vision call for blueprint pages — Gemini only.

    Issue 5: on failure this deliberately returns "" (rather than falling
    back to a text-only LLM guess) so the caller can treat "no vision data"
    as "no vision data" instead of risking a hallucinated description of a
    blueprint page being written into the facts pipeline.
    """
    try:
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
        img_part = {"mime_type": "image/png", "data": image_data}
        prompt = (
            "You are analysing a construction engineering drawing. "
            "Extract and list ALL of the following that are visible:\n"
            "1. All dimensions and measurements (include units — mm, m, inches)\n"
            "2. Material specifications or concrete grades (e.g. C25, M30, f'c=4000psi)\n"
            "3. Rebar sizes, spacing, and arrangement (e.g. 16mm dia @ 150mm c/c)\n"
            "4. Grid references, sheet numbers, revision marks\n"
            "5. Component labels: beams, columns, slabs, walls, MEP elements\n"
            "6. Any notes, callouts, or specification references\n"
            "7. Elevation levels or datum references\n"
            "Be precise and technical. Format as a numbered structured list. "
            "If a section has nothing visible, skip it."
        )
        return _client.models.generate_content(model=_GEN_MODEL, contents=[img_part, prompt]).text
    except Exception as e:
        logger.error(f"[gemini] Vision failed for {image_path}: {e}")
        return ""