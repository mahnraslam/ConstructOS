import os
import re
import logging
import base64
from google import genai
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_API_KEY = os.getenv("GEMINI_API_KEY", "")
if not _API_KEY or _API_KEY in ("your_key_here", "your_gemini_api_key_here", "test-key"):
    logger.warning("[gemini] GEMINI_API_KEY is not set or is a placeholder. LLM calls will fail.")

# Initialize new google-genai SDK
_client = genai.Client(api_key=_API_KEY)

_GEN_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
_EMBED_MODEL = "text-embedding-004"

MAX_RETRIES = 2


def embed_text(text: str) -> list[float]:
    """Embed a single string using text-embedding-004 → 768-dim vector."""
    if len(text) > 8000:
        logger.warning(f"[gemini] Text truncated from {len(text)} to 8000 chars for embedding")
    result = _client.models.embed_content(
        model=_EMBED_MODEL,
        contents=text[:8000],
    )
    return result.embedding


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a list of strings with basic retry on failure."""
    embeddings = []
    for i, t in enumerate(texts):
        last_err = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                embeddings.append(embed_text(t))
                break
            except Exception as e:
                last_err = e
                if attempt < MAX_RETRIES:
                    import time
                    wait = 2 ** attempt
                    logger.warning(f"[gemini] Embed retry {attempt+1}/{MAX_RETRIES} for chunk {i}: {e}")
                    time.sleep(wait)
        else:
            raise RuntimeError(f"Embedding failed after {MAX_RETRIES} retries for chunk {i}: {last_err}")
    return embeddings


def generate(prompt: str) -> str:
    """Plain text generation using gemini-2.0-flash."""
    try:
        response = _client.models.generate_content(
            model=_GEN_MODEL,
            contents=prompt,
        )
        return response.text
    except Exception as e:
        logger.error(f"[gemini] Generation failed: {e}")
        return f"[Gemini error: {e}]"


def generate_json(prompt: str) -> str:
    """Generation expected to return JSON — caller parses."""
    raw = generate(prompt)
    cleaned = re.sub(r'^```(?:json)?\s*\n?', '', raw.strip())
    cleaned = re.sub(r'\n?```\s*$', '', cleaned)
    return cleaned.strip()


def generate_with_images(prompt: str, image_paths: list[str]) -> str:
    """
    Multimodal generation: send text prompt together with one or more page
    images so Gemini can see the drawings when formulating its answer.
    """
    content: list = []
    loaded = 0
    for path in image_paths:
        if not os.path.exists(path):
            logger.warning(f"[gemini] Image not found, skipping: {path}")
            continue
        try:
            with open(path, "rb") as f:
                data = base64.b64encode(f.read()).decode("utf-8")
            content.append({"mime_type": "image/png", "data": data})
            loaded += 1
        except Exception as e:
            logger.warning(f"[gemini] Could not load image {path}: {e}")

    if loaded == 0:
        logger.warning("[gemini] generate_with_images: no images loaded, falling back to text-only")
        return generate(prompt)

    content.append(prompt)

    try:
        logger.info(f"[gemini] Multimodal generation with {loaded} page image(s)")
        response = _client.models.generate_content(
            model=_GEN_MODEL,
            contents=content,
        )
        return response.text
    except Exception as e:
        logger.error(f"[gemini] Multimodal generation failed: {e}")
        logger.info("[gemini] Falling back to text-only generation")
        return generate(prompt)


def describe_blueprint_page(image_path: str) -> str:
    """
    Vision call: extract technical information from a blueprint page image.
    Called for drawing-heavy pages where text extraction yields < 200 chars.
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
        response = _client.models.generate_content(
            model=_GEN_MODEL,
            contents=[img_part, prompt],
        )
        return response.text
    except Exception as e:
        logger.error(f"[gemini] Vision failed for {image_path}: {e}")
        return ""