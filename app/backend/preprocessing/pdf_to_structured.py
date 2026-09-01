"""
preprocessing/pdf_to_structured.py
-----------------------------------
Extracts structured UE / ECUE data from academic PDF program files.

Uses pdfplumber to parse tables and text, detects UE codes (e.g. 311)
and ECUE codes (e.g. 3111), groups ECUEs under their parent UE via
prefix matching, and produces clean semantic chunks for ChromaDB.
"""

import logging
import re
from pathlib import Path
from typing import List, Optional

import pdfplumber

logger = logging.getLogger(__name__)

# ── Regex patterns ────────────────────────────────────────────────────

# UE code: 3 digits starting with 3, 4, or 5 (Enet'com academic years)
UE_PATTERN = re.compile(
    r"(?:^|(?<=\s)|(?<=\b))"
    r"(?:UE\s*)?"
    r"([345]\d{2})"
    r"\s+"
    r"([A-ZÀ-Ÿa-zà-ÿ][A-ZÀ-Ÿa-zà-ÿ\s''(),.:&/éèêëàâäùûüôöîïç-]+?)"
    r"(?=\s+\d|\s*$)",  # stop before any digit sequence or end of line
    re.UNICODE,
)

# ECUE code: 4-5 digits whose first 3 digits form a valid UE code (3xx/4xx/5xx)
ECUE_PATTERN = re.compile(
    r"(?:^|(?<=\s)|(?<=\b))"
    r"(?:ECUE\s*)?"
    r"([345]\d{3,4})"
    r"\s+"
    r"([A-ZÀ-Ÿa-zà-ÿ][A-ZÀ-Ÿa-zà-ÿ\s''(),.:&/éèêëàâäùûüôöîïç-]+?)"
    r"(?=\s+\d|\s*$)",  # stop before any digit sequence or end of line
    re.UNICODE,
)


def _clean_name(name: str) -> str:
    """Strip trailing whitespace, numbers, and stray punctuation from a name."""
    name = name.strip()
    # Normalize internal newlines to spaces
    name = re.sub(r"\s*\n\s*", " ", name)
    # Remove trailing sequences of digits+spaces (credit/coeff columns from tables)
    name = re.sub(r"(?:\s+\d+[.,]?\d*)+\s*$", "", name)
    # Remove trailing 'X' markers (exam indicators in tables)
    name = re.sub(r"\s+X\s*$", "", name)
    # Remove trailing whitespace/dashes
    name = name.rstrip(" -–—")
    return name


def extract_ue_ecue_from_pdf(pdf_path: str | Path) -> List[dict]:
    """
    Parse a PDF and extract structured UE → ECUE hierarchy.

    Strategy:
      1. Extract all text from tables (which contain program data)
      2. Also extract raw page text as fallback
      3. Scan for UE and ECUE codes via regex
      4. Group ECUEs under their parent UE by prefix matching

    Args:
        pdf_path: Path to the academic PDF file.

    Returns:
        List of dicts with keys: ue_code, ue_name, ecues (list of code/name).
    """
    pdf_path = Path(pdf_path)
    logger.info("structured_parser: processing %s", pdf_path.name)

    all_text_lines: List[str] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            # ── Extract from tables first (most structured data lives here)
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row:
                        # Join cells, skip None values
                        line = " ".join(
                            str(cell).strip() for cell in row if cell
                        )
                        if line.strip():
                            all_text_lines.append(line)

            # ── Also extract raw text as fallback
            raw_text = page.extract_text()
            if raw_text:
                for line in raw_text.split("\n"):
                    if line.strip():
                        all_text_lines.append(line.strip())

    logger.info(
        "structured_parser: extracted %d text lines from %s",
        len(all_text_lines), pdf_path.name,
    )

    # ── Detect all UE and ECUE entries ────────────────────────────────
    ues: dict[str, dict] = {}   # code -> {ue_code, ue_name, ecues: []}
    ecues: List[dict] = []      # [{code, name}]

    for line in all_text_lines:
        # Try ECUE first (longer codes) to avoid false UE matches
        for match in ECUE_PATTERN.finditer(line):
            code = match.group(1)
            name = _clean_name(match.group(2))
            if name and len(name) > 2:
                ecues.append({"code": code, "name": name})
                logger.debug("structured_parser: found ECUE %s — %s", code, name)

        for match in UE_PATTERN.finditer(line):
            code = match.group(1)
            name = _clean_name(match.group(2))
            # Skip if this code was already captured as an ECUE
            if any(e["code"] == code for e in ecues):
                continue
            # Skip very short or numeric-only names
            if name and len(name) > 2 and not name.isdigit():
                if code not in ues:
                    ues[code] = {"ue_code": code, "ue_name": name, "ecues": []}
                    logger.debug("structured_parser: found UE %s — %s", code, name)

    # ── Group ECUEs under their parent UE via prefix matching ─────────
    for ecue in ecues:
        ecue_code = ecue["code"]
        # The parent UE code is the prefix: ECUE 3111 → UE 311, ECUE 51201 → UE 512
        matched = False
        # Try longest prefix first (3-digit UE before 2-digit)
        for prefix_len in (3, 2):
            parent_code = ecue_code[:prefix_len]
            if parent_code in ues:
                # Avoid duplicate ECUEs
                existing_codes = {e["code"] for e in ues[parent_code]["ecues"]}
                if ecue_code not in existing_codes:
                    ues[parent_code]["ecues"].append(ecue)
                matched = True
                break

        if not matched:
            logger.warning(
                "structured_parser: orphan ECUE %s (%s) — no parent UE found",
                ecue_code, ecue["name"],
            )

    result = list(ues.values())
    logger.info(
        "structured_parser: extracted %d UE(s) with %d total ECUE(s) from %s",
        len(result),
        sum(len(ue["ecues"]) for ue in result),
        pdf_path.name,
    )
    return result


def ue_to_semantic_chunk(ue: dict) -> str:
    """
    Convert a single UE dict into a readable semantic chunk text.

    Example output:
        UE 311 Mathématiques I contient les éléments constitutifs suivants :
        - 3111 Mathématiques de l'ingénieur
        - 3112 Probabilité et Processus Stochastiques
    """
    lines = [f"UE {ue['ue_code']} {ue['ue_name']} contient les éléments constitutifs suivants :"]
    for ecue in ue["ecues"]:
        lines.append(f"- {ecue['code']} {ecue['name']}")

    if not ue["ecues"]:
        lines.append("(aucun ECUE détecté)")

    return "\n".join(lines)


def build_structured_chunks(pdf_path: str | Path) -> List[dict]:
    """
    Full pipeline: PDF → structured UE extraction → semantic chunks.

    Returns a list of dicts ready for ChromaDB ingestion:
        [{text, source, ue_code, ue_name}, ...]
    """
    pdf_path = Path(pdf_path)
    ues = extract_ue_ecue_from_pdf(pdf_path)

    chunks = []
    for ue in ues:
        text = ue_to_semantic_chunk(ue)
        chunks.append({
            "text": text,
            "source": pdf_path.name,
            "ue_code": ue["ue_code"],
            "ue_name": ue["ue_name"],
        })

    logger.info(
        "structured_parser: built %d structured chunks from %s",
        len(chunks), pdf_path.name,
    )
    return chunks


def match_ue_from_query(query: str) -> Optional[str]:
    """
    Extract a UE code from a user query string.

    Handles patterns like:
      - "UE 311"
      - "UE311"
      - "l'UE 311"
      - Just "311" when preceded by typical keywords

    Args:
        query: The user's natural-language question.

    Returns:
        The UE code as a string (e.g. "311"), or None if not found.
    """
    # Direct pattern: "UE 311" or "UE311"
    m = re.search(r"UE\s*([345]\d{2})\b", query, re.IGNORECASE)
    if m:
        return m.group(1)

    # Contextual pattern: code after keywords like "unité", "module"
    m = re.search(
        r"(?:unité|module|matière|élément)\s+([345]\d{2})\b",
        query, re.IGNORECASE,
    )
    if m:
        return m.group(1)

    return None
