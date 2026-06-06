import re
import logging
from sqlalchemy.orm import Session
from services import vector_store
from db import Fact, ProjectDocument

logger = logging.getLogger(__name__)


# ── Public API ────────────────────────────────────────────────────────────────

def extract_facts_for_document(
    doc_id: str,
    project_id: str,
    filename: str,
    doc_type: str,
    db: Session,
) -> int:
    """Extract facts via regex — no LLM, no API calls, no rate limits."""
    db.query(Fact).filter(Fact.document_id == doc_id).delete()
    db.commit()

    chunks = vector_store.get_all_by_doc_id(doc_id)
    if not chunks:
        logger.warning(f"[facts] No chunks found for doc_id={doc_id}")
        return 0

    # Combine all pages into one searchable string
    full_text = "\n".join(c["text"] for c in chunks)
    logger.info(f"[facts] Regex-extracting from '{filename}' ({len(chunks)} chunks, {len(full_text)} chars)")

    all_facts: list[dict] = []
    all_facts += _extract_door_schedule(full_text, doc_id, project_id)
    all_facts += _extract_window_schedule(full_text, doc_id, project_id)
    all_facts += _extract_u_factor(full_text, doc_id, project_id)
    all_facts += _extract_header_schedule(full_text, doc_id, project_id)
    all_facts += _extract_room_finishes(full_text, doc_id, project_id)

    # Deduplicate by (field, normalised_value)
    seen: set[tuple] = set()
    unique: list[dict] = []
    for f in all_facts:
        key = (f["field"], _norm(f["value"]))
        if key not in seen:
            seen.add(key)
            unique.append(f)

    for f in unique:
        db.add(Fact(**f))
    db.commit()

    logger.info(f"[facts] Stored {len(unique)} facts for '{filename}'")
    return len(unique)


def get_facts_for_project(project_id: str, db: Session) -> list[dict]:
    """Return all facts for a project with document filename."""
    rows = db.query(Fact, ProjectDocument.filename).join(
        ProjectDocument, Fact.document_id == ProjectDocument.id
    ).filter(Fact.project_id == project_id).all()
    return [
        {
            "id":          r.Fact.id,
            "category":    r.Fact.category,
            "field":       r.Fact.field,
            "value":       r.Fact.value,
            "unit":        r.Fact.unit,
            "page":        r.Fact.page,
            "sheet":       r.Fact.sheet,
            "section":     r.Fact.section,
            "quote":       r.Fact.quote,
            "document_id": r.Fact.document_id,
            "filename":    r.filename,
        }
        for r in rows
    ]


# ── Extractors ────────────────────────────────────────────────────────────────

def _extract_door_schedule(text: str, doc_id: str, project_id: str) -> list[dict]:
    """
    Section 08100 — Door Schedule.
    Matches: 102  3/0x6/8  INT  NO  ...
             109  (2)2/4x6/8  INT  NO  ...
    Covers defects: D-01 to D-06.
    """
    facts = []
    pattern = re.compile(
        r'\b(\d{3})\s+'                           # door number e.g. 102
        r'((?:\(\d+\))?[\d]+/[\d]+x[\d]+/[\d]+)' # size e.g. 3/0x6/8 or (2)2/4x6/8
        r'(?:\s*\[.*?\])?'                         # strip [■ WRONG ...] annotation
        r'\s+(INT|EXT)',                            # INT or EXT
        re.IGNORECASE
    )
    seen: set[str] = set()
    for m in pattern.finditer(text):
        door_num = m.group(1)
        if door_num in seen:
            continue
        seen.add(door_num)
        size = _clean(m.group(2))
        facts.append(_fact(
            project_id, doc_id, "architectural",
            f"door_{door_num}_size", size,
            section="08100",
            quote=f"Door {door_num}: {size}",
        ))

    # Attic ladder (special format: ATT 20x54 or ATT 22.2x54)
    attic = re.search(r'\bATT\s+([\d.]+x[\d]+)\s+INT', text, re.IGNORECASE)
    if attic:
        facts.append(_fact(
            project_id, doc_id, "architectural",
            "attic_ladder_size", _clean(attic.group(1)),
            section="08100", quote=f"ATT {attic.group(1)}",
        ))

    return facts


def _extract_window_schedule(text: str, doc_id: str, project_id: str) -> list[dict]:
    """
    Section 08500 — Window Schedule.
    Matches: A  NYL  3/0x5/0  Double Hung  Egress Window
    Covers defects: W-01 to W-04.
    """
    facts = []
    # Window label A-K followed by optional material, then size, then operation
    pattern = re.compile(
        r'\b([A-K])\s+'
        r'(?:NYL|EX\.?|VINYL)?\s*'
        r'((?:\(\d+\))?[\d]+/[\d]+x[\d]+/[\d]+)'   # size
        r'(?:\s*\[.*?\])?'                            # strip annotations
        r'\s*(DOUBLE HUNG|CASEMENT|TRANSOM|FIXED|SLIDER|SLIDING)?',
        re.IGNORECASE
    )
    seen: set[str] = set()
    for m in pattern.finditer(text):
        label = m.group(1).upper()
        if label in seen:
            continue
        seen.add(label)
        size = _clean(m.group(2))
        facts.append(_fact(
            project_id, doc_id, "architectural",
            f"window_{label}_size", size,
            section="08500", quote=f"Window {label}: {size}",
        ))
        if m.group(3):
            facts.append(_fact(
                project_id, doc_id, "architectural",
                f"window_{label}_operation", m.group(3).strip().title(),
                section="08500", quote=f"Window {label}: {m.group(3).strip()}",
            ))
    return facts


def _extract_u_factor(text: str, doc_id: str, project_id: str) -> list[dict]:
    """
    Section 08500 — U-Factor.
    Blueprint: MAX. U = .31    Spec (defective): 0.35
    Covers defect: W-05 (U-factor wrong in spec).
    """
    # Matches: MAX. U = .31  or  U-Factor: 0.35  or  U = 0.31
    m = re.search(
        r'(?:MAX\.?\s*U\s*=\s*\.?|U[\s-]?FACTOR[:\s]+\.?)(\d*\.?\d+)',
        text, re.IGNORECASE
    )
    if m:
        return [_fact(
            project_id, doc_id, "architectural",
            "window_u_factor", m.group(1),
            section="08500", quote=m.group(0)[:80],
        )]
    return []


def _extract_header_schedule(text: str, doc_id: str, project_id: str) -> list[dict]:
    """
    Section 06100 — Header Schedule.
    Blueprint: Openings up to 3'-0"  →  (2) 2x10
    Spec:      Openings up to 3'-0"  →  (2) 1.75x11.875 1.9E Microlam
    Covers defects: H-01 (wrong size), H-02 (wrong grade).
    """
    facts = []

    # Opening ≤ 3'-0"
    m = re.search(
        r'(?:UP TO|OPENINGS UP TO)\s*3[\'\-]0[\'"]?\s+'
        r'((?:\(\d+\)\s*)?(?:[\d.]+x[\d.]+|\d+x\d+)(?:\s+[\d.]+E\s+\S+)?)',
        text, re.IGNORECASE
    )
    if m:
        facts.append(_fact(
            project_id, doc_id, "structural",
            "header_opening_up_to_3ft", _clean(m.group(1).strip()),
            section="06100", quote=m.group(0)[:120],
        ))

    # Opening > 3' to 6'
    m = re.search(
        r'(?:GREATER THAN|>)\s*3[\'\-]0[\'"]?\s+(?:TO|UP TO)\s*6[\'\-]0[\'"]?\s+'
        r'((?:\(\d+\)\s*)?(?:[\d.]+x[\d.]+)(?:\s+[\d.]+E\s+\S+)?)',
        text, re.IGNORECASE
    )
    if m:
        facts.append(_fact(
            project_id, doc_id, "structural",
            "header_opening_3ft_to_6ft", _clean(m.group(1).strip()),
            section="06100", quote=m.group(0)[:120],
        ))

    # Opening > 6' to 8'
    m = re.search(
        r'(?:GREATER THAN|>)\s*6[\'\-]0[\'"]?\s+(?:TO|UP TO)\s*8[\'\-]0[\'"]?\s+'
        r'((?:\(\d+\)\s*)?(?:[\d.]+x[\d.]+)(?:\s+[\d.]+E\s+\S+)?)',
        text, re.IGNORECASE
    )
    if m:
        facts.append(_fact(
            project_id, doc_id, "structural",
            "header_opening_6ft_to_8ft", _clean(m.group(1).strip()),
            section="06100", quote=m.group(0)[:120],
        ))

    # LVL grade (1.9E vs 1.5E) — subtle defect H-02
    for grade_m in re.finditer(r'([\d.]+E)\s+Microlam', text, re.IGNORECASE):
        facts.append(_fact(
            project_id, doc_id, "structural",
            "header_lvl_grade", grade_m.group(1).upper(),
            section="06100", quote=grade_m.group(0)[:80],
        ))

    return facts


def _extract_room_finishes(text: str, doc_id: str, project_id: str) -> list[dict]:
    """
    Section 09300 — Room Finish Schedule (floor materials only).
    Covers defects: R-01 to R-06.
    """
    facts = []

    # Rooms to track → normalised field key
    ROOMS: dict[str, str] = {
        r"dining[\s/]?room":       "dining_room",
        r"bedroom[\s]?2":          "bedroom_2",
        r"bedroom[\s]?3":          "bedroom_3",
        r"storage[\s\(\w\)]*":     "storage_basement",
        r"master[\s]?bath\w*":     "master_bath",
        r"garage":                 "garage",
        r"pantry":                 "pantry",
        r"living[\s]?room":        "living_room",
        r"kitchen":                "kitchen",
        r"laundry[\w\s/]*room":    "laundry",
        r"sunroom":                "sunroom",
        r"craft[\s]?room":         "craft_room",
        r"entertainment[\s]?area": "entertainment_area",
        r"sump[\s]?closet":        "sump_closet",
        r"bath[\s]?room[\s]?2":    "bathroom_2",
    }

    FINISH_MATERIALS = (
        "CERAMIC TILE", "LVT", "CARPET", "CONCRETE",
        "UNFINISHED", "BEAD BOARD", "PAINTED GYP",
        "MACADAM", "CONCRETE PAVERS",
    )
    mat_pat = re.compile(
        "|".join(re.escape(m) for m in FINISH_MATERIALS),
        re.IGNORECASE,
    )

    for room_regex, room_key in ROOMS.items():
        m = re.search(
            rf'\b({room_regex})\b([^\n]{{1,120}})',
            text, re.IGNORECASE
        )
        if not m:
            continue
        line = _clean(m.group(2))  # strip [■ WRONG ...] first
        mat = mat_pat.search(line)
        if mat:
            value = mat.group(0).strip().title()
            facts.append(_fact(
                project_id, doc_id, "architectural",
                f"floor_finish_{room_key}", value,
                section="09300",
                quote=f"{m.group(1).strip()}: {value}",
            ))

    return facts


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean(s: str) -> str:
    """Strip [■ WRONG — ...] spec annotations and extra whitespace."""
    s = re.sub(r'\[.*?\]', '', s)   # remove [■ WRONG — should be ...]
    s = re.sub(r'■.*', '', s)       # remove anything after ■
    return re.sub(r'\s+', ' ', s).strip()


def _norm(s: str) -> str:
    return re.sub(r'\s+', ' ', s.strip().lower())


def _fact(
    project_id: str, doc_id: str, category: str,
    field: str, value: str,
    section: str = "", quote: str = "",
    page: int = 0, sheet: str = "A100",
) -> dict:
    return {
        "project_id":  project_id,
        "document_id": doc_id,
        "category":    category,
        "field":       field,
        "value":       value,
        "unit":        "",
        "page":        page,
        "sheet":       sheet,
        "section":     section,
        "quote":       quote[:100],
    }
 