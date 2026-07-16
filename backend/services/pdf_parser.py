import os
import logging
import pdfplumber
from pdf2image import convert_from_path
from dotenv import load_dotenv
from services.gemini import describe_blueprint_page


_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
load_dotenv(_ENV_PATH, override=True)

logger = logging.getLogger(__name__)

PAGES_DIR = os.getenv("PAGES_PATH", "storage/pages")

CHUNK_SIZE = 1500
CHUNK_OVERLAP = 100
VISION_THRESHOLD = 200

os.makedirs(PAGES_DIR, exist_ok=True)


def _chunk_text(text: str, page: int, doc_id: str) -> list[dict]:
    """Split page text into overlapping chunks."""

    text = text.strip()

    if not text:
        return []

    if len(text) <= CHUNK_SIZE:
        return [{
            "doc_id": doc_id,
            "page": page,
            "text": text
        }]

    chunks = []
    start = 0

    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end]

        if chunk.strip():
            chunks.append({
                "doc_id": doc_id,
                "page": page,
                "text": chunk
            })

        start += CHUNK_SIZE - CHUNK_OVERLAP

    return chunks


def _get_vision_text(image_path: str) -> str | None:
    """Run Gemini Vision safely."""

    try:
        
        return describe_blueprint_page(image_path)

    except Exception as e:
        logger.warning(f"[pdf_parser] Vision failed for {image_path}: {e}")
        return None


def parse(pdf_path: str, doc_id: str) -> tuple[list[dict], int]:
    """
    Parse a PDF.

    Workflow:

    1. Render PDF once.
    2. Open PDF once.
    3. Save each page image.
    4. Extract page text.
    5. Run Vision only for drawing-heavy pages.
    6. Chunk text.
    """

    # ----------------------------------------------------
    # Render PDF ONCE
    # ----------------------------------------------------

    try:
        images = convert_from_path(pdf_path)

    except Exception as e:
        logger.error(f"[pdf_parser] Failed to render PDF: {e}")
        raise

    chunks = []

    # ----------------------------------------------------
    # Open PDF ONCE
    # ----------------------------------------------------

    with pdfplumber.open(pdf_path) as pdf:

        page_count = len(pdf.pages)

        if len(images) != page_count:
            logger.warning(
                f"[pdf_parser] Rendered {len(images)} images "
                f"but PDF contains {page_count} pages."
            )

        for i, page in enumerate(pdf.pages):

            page_num = i + 1

            image = images[i]

            image_path = os.path.join(
                PAGES_DIR,
                f"{doc_id}_page_{page_num}.png"
            )

            image_saved = False

            # -----------------------------------------
            # Save page image
            # -----------------------------------------

            try:
                image.save(image_path, "PNG")
                image_saved = True

            except Exception as e:
                logger.warning(
                    f"[pdf_parser] Failed to save image "
                    f"for page {page_num}: {e}"
                )

            # -----------------------------------------
            # Extract text
            # -----------------------------------------

            try:
                text = page.extract_text() or ""

            except Exception as e:
                logger.warning(
                    f"[pdf_parser] Failed to extract text "
                    f"from page {page_num}: {e}"
                )
                text = ""

            # -----------------------------------------
            # Vision enrichment
            # -----------------------------------------

            if image_saved and len(text.strip()) < VISION_THRESHOLD:

                vision_text = _get_vision_text(image_path)

                if vision_text:

                    text += "\n\n[VISION ANALYSIS]\n"
                    text += vision_text

                    logger.info(
                        f"[pdf_parser] Vision enriched page "
                        f"{page_num}"
                    )

            # -----------------------------------------
            # Chunk page
            # -----------------------------------------

            chunks.extend(
                _chunk_text(
                    text=text,
                    page=page_num,
                    doc_id=doc_id
                )
            )

    return chunks, page_count