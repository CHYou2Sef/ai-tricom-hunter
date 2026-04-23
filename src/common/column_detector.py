"""
╔══════════════════════════════════════════════════════════════════════════╗
║  utils/column_detector.py                                                ║
║                                                                          ║
║  Smart column name mapper.                                               ║
║  Problem: Excel files use DIFFERENT column names for the same concept.   ║
║  Solution: We scan every column header and score it against keyword      ║
║            lists. The column with the highest score wins.                ║
║                                                                          ║
║  BEGINNER NOTE:                                                          ║
║    This is called "fuzzy matching" — we don't need an exact match,       ║
║    we just need the best candidate above a minimum confidence threshold. ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import re
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# KEYWORD DICTIONARIES
# Each key is a "concept" we care about.
# Each value is a list of substrings that INDICATE that concept.
# We check if any keyword appears inside the column header (after normalizing).
# ─────────────────────────────────────────────────────────────────────────────

COLUMN_KEYWORDS = {

    # ── Company name (Raison Sociale) ──
    "raison_sociale": [
        "raison sociale", "raison_sociale",
        "denomination", "dénomination",
        "denominationunite",       # INSEE: denominationUniteLegale
        "nom commercial", "nomcommercial",
        "nom de l'entreprise", "nom entreprise",
        "societe", "société",
        "libelle", "libellé",
        "enseigne", "nom", "entreprise", "nom_com",
    ],

    # ── Full address (single-field) ──
    "adresse": [
        "adresse complete", "adresse du siege", "adresse du siège",
        "adresse siege", "full address",
    ],

    # ── Address components (split-field, INSEE format) ──
    "adresse_numero": [
        "numerovoie", "numero voie", "numvoie", "num_voie",
    ],
    "adresse_typevoie": [
        "typevoie", "type voie", "type_voie", "indice",
    ],
    "adresse_libellevoie": [
        "libellevoie", "libelle voie", "libelle_voie",
        "libellerue", "libelle rue",
    ],

    # ── SIREN (9-digit company identifier) ──
    "siren": [
        "siren",
    ],

    # ── SIRET (14-digit establishment identifier, includes SIREN) ──
    "siret": [
        "siret",
    ],

    # ── Postal code ──
    "code_postal": [
        "code postal", "codepostal", "cp", "zip", "postal",
    ],

    # ── City ──
    "ville": [
        "ville", "city", "commune", "localite", "localité",
        "libellecommune", "libelle commune",
    ],

    # ── Phone number (if one already exists in the file) ──
    # CRITICAL: Do NOT include generic words like 'numero' or 'contact'
    # that could match street numbers or status fields.
    "telephone": [
        "telephone", "téléphone", "tel", "tél", "phone",
        "portable", "mobile", "fax", "fixe",
        "num tel", "numtel",
    ],

    # ── First name (Prénom) ──
    "prenom": [
        "prenom", "prénom", "first name", "firstname",
    ],

    # ── Last name (Nom de famille) ──
    "nom_famille": [
        "nom", "name", "surname", "last name", "lastname", "nom de famille",
    ],

    # ── Legal form ──
    "forme_juridique": [
        "forme juridique", "formejuridique", "legal",
    ],

    # ── Activity / APE code ──
    "activite": [
        "activite", "activité", "ape", "naf", "code ape",
        "activite principale",
    ],

    # ── Registration date ──
    "date_immatriculation": [
        "immatriculation", "creation", "création", "debut", "début",
        "rne",
    ],
}


def _normalize(text: str) -> str:
    """
    Normalize a string for comparison:
    - Lowercase everything
    - Remove accents
    - Replace separators (_ and -) with spaces
    - Remove extra whitespace
    """
    if not isinstance(text, str):
        return ""

    text = text.lower().strip()
    text = text.replace("_", " ").replace("-", " ")

    # Replace common accented characters
    replacements = {
        "é": "e", "è": "e", "ê": "e", "ë": "e",
        "à": "a", "â": "a", "ä": "a",
        "ù": "u", "û": "u", "ü": "u",
        "î": "i", "ï": "i",
        "ô": "o", "ö": "o",
        "ç": "c",
        "œ": "oe", "æ": "ae",
    }
    for accented, plain in replacements.items():
        text = text.replace(accented, plain)

    # Collapse multiple spaces into one
    text = re.sub(r'\s+', ' ', text)

    return text


def _score_column(col_header: str, keywords: list) -> int:
    """
    Score a single column header against a list of keywords.
    Uses word boundaries for short keywords to prevent false positives (e.g. 'tel' in 'etablissement').
    """
    normalized = _normalize(col_header)
    score = 0
    for kw in keywords:
        kw_norm = _normalize(kw)
        if not kw_norm:
            continue
            
        if len(kw_norm) <= 3:
            # Word boundary check for short keywords
            if re.search(rf'\b{re.escape(kw_norm)}\b', normalized):
                score += 1
        elif kw_norm in normalized:
            score += 1
    return score


def detect_columns(headers: list) -> dict:
    """
    Given a list of Excel column headers, return a mapping of
    concept → column_name (the best matching header for each concept).

    Supports both single-field addresses ("Adresse du siège") and
    split-field addresses (INSEE: numeroVoie + typeVoie + libelleVoie + codePostal + commune).
    """

    # Minimum score required to consider a match valid
    MIN_SCORE = 1

    result = {}

    for concept, keywords in COLUMN_KEYWORDS.items():
        best_header = None
        best_score  = 0

        for header in headers:
            score = _score_column(str(header), keywords)
            if score > best_score:
                best_score  = score
                best_header = header

        # Only assign if score meets minimum threshold
        result[concept] = best_header if best_score >= MIN_SCORE else None

    # ── Composite Address Builder ──
    # If no single "adresse" column was found, check if we have split components
    if not result.get("adresse"):
        has_components = (
            result.get("adresse_numero") or
            result.get("adresse_typevoie") or
            result.get("adresse_libellevoie") or
            result.get("code_postal") or
            result.get("ville")
        )
        if has_components:
            # Set a virtual marker so ExcelRow knows to assemble from parts
            result["adresse"] = "__COMPOSITE__"

    return result


def validate_mapping(mapping: dict) -> dict:
    """
    Check which of the three KEY fields are present:
        1. raison_sociale  → we can do a RS+Adresse search
        2. siren / siret   → we can do a SIREN+Adresse search
        3. adresse         → required for BOTH search types

    Returns a dict with validation results.
    """
    has_rs    = mapping.get("raison_sociale") is not None
    has_siren = (mapping.get("siren") is not None or
                 mapping.get("siret") is not None)
    has_adr   = mapping.get("adresse") is not None  # includes __COMPOSITE__

    return {
        "has_raison_sociale":  has_rs,
        "has_siren_or_siret":  has_siren,
        "has_adresse":         has_adr,
        "can_search_rs":       has_rs and has_adr,
        "can_search_siren":    has_siren and has_adr,
    }

