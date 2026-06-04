import os
import logging
import pdfplumber
from pdf2image import convert_from_path
from dotenv import load_dotenv

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
load_dotenv(_ENV_PATH, override=True)

logger = logging.getLogger(__name__)

PAGES_DIR  = os.getenv("PAGES_PATH", "storage/pages")
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 100
VISION_THRESHOLD = 200  # chars — pages below this get Gemini Vision enrichment

os.makedirs(PAGES_DIR, exist_ok=True)


def _chunk_text(text: str, page: int, doc_id: str) -> list[dict]:
    """Split a page's text into overlapping chunks of ~CHUNK_SIZE characters."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= CHUNK_SIZE:
        return [{"doc_id": doc_id, "page": page, "text": text}]

    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunk_text = text[start:end]
        if chunk_text.strip():
            chunks.append({"doc_id": doc_id, "page": page, "text": chunk_text})
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


def parse(pdf_path: str, doc_id: str) -> tuple[list[dict], int]:
    """
    Extract text chunks per page, apply Vision enrichment for drawing-heavy
    pages, save page images. Returns (chunks, page_count).
    """
    chunks = []
    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""

            # Vision enrichment for drawing-heavy pages (< 200 chars of text)
            if len(text.strip()) < VISION_THRESHOLD:
                try:
                    from services.gemini import describe_blueprint_page
                    # Save page image first so vision can use it
                    page_images = convert_from_path(
                        pdf_path, first_page=i + 1, last_page=i + 1
                    )
                    if page_images:
                        img_path = os.path.join(PAGES_DIR, f"{doc_id}_page_{i + 1}.png")
                        page_images[0].save(img_path, "PNG")
                        vision_text = describe_blueprint_page(img_path)
                        if vision_text:
                            text = text + "\n\n[VISION ANALYSIS]\n" + vision_text
                            logger.info(f"[pdf_parser] Vision enriched page {i+1} for {doc_id}")
                except Exception as e:
                    logger.warning(f"[pdf_parser] Vision failed for page {i+1}: {e}")

            # Chunk the text
            page_chunks = _chunk_text(text, i + 1, doc_id)
            chunks.extend(page_chunks)

    # Save all page images (some may already exist from vision step)
    try:
        images = convert_from_path(pdf_path)
        for i, img in enumerate(images):
            img_path = os.path.join(PAGES_DIR, f"{doc_id}_page_{i + 1}.png")
            if not os.path.exists(img_path):  # skip if vision already saved it
                img.save(img_path, "PNG")
    except Exception as e:
        logger.warning(f"[pdf_parser] Page image rendering failed: {e}")

    return chunks, page_count
