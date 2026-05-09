"""
╔══════════════════════════════════════════════════════════════════════════╗
║  domain/excel/reader.py                                                  ║
║                                                                          ║
║  Universal Excel/CSV/JSON File Reader & Row Model                        ║
║                                                                          ║
║  ROLE:                                                                   ║
║    Reads any tabular input file and converts each row into an ExcelRow   ║
║    object with normalized fields (nom, adresse, siren, phone, etc.).     ║
║                                                                          ║
║  HOW IT WORKS:                                                           ║
║    1. Uses pandas to read .xlsx, .xls, .csv, or .json files             ║
║    2. detect_columns() maps headers to standard concepts via keywords    ║
║    3. If heuristics fail, falls back to LLM-based column detection       ║
║    4. Each row becomes an ExcelRow with search_type (RS_ADR/SIREN_ADR)  ║
║    5. Filters out "radié" (closed) companies automatically               ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import json
import re
import asyncio
import sys
from typing import Any, List, Optional, Tuple

pd: Any = None

# Pandas import can fail in containerized setups if Python is accidentally
# running from/inside a NumPy source tree.
# Root cause: Docker PYTHONPATH=/app/src injected at position 0 causes Python
# to find /app/src/numpy (non-existent but shadowing) before site-packages.
#
# Two-layer fix:
#   1. Sanitize sys.path  — move site-packages before project dirs
#   2. Evict module cache — clear broken numpy/pandas from sys.modules BEFORE
#      retrying, otherwise Python returns the cached broken module on all retries.
def _safe_import_pandas():
    """
    Hardened pandas importer for containerized environments.

    Strategy:
      • Always move site-packages to the front of sys.path.
      • Evict any cached-but-broken numpy/pandas from sys.modules before
        each attempt (broken ImportError state is sticky in the module cache).
      • Never restore the original poisoned path on failure.
    """
    import sys
    import os

    # ── Step 1: Build a safe sys.path ────────────────────────────────────
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    src_dir   = os.path.join(repo_root, "src")
    cwd       = os.getcwd()

    # Remove all known shadowing directories
    dangerous = {cwd, os.path.abspath(cwd), repo_root, src_dir, ""}
    clean_path = [p for p in sys.path if p not in dangerous]

    # Site-packages first — this is the critical ordering requirement
    site_pkgs = [p for p in clean_path if "site-packages" in p]
    others    = [p for p in clean_path if "site-packages" not in p]
    safe_path  = site_pkgs + others

    # Append project dirs at the END so they resolve last
    for d in [repo_root, src_dir]:
        if d not in safe_path:
            safe_path.append(d)

    sys.path[:] = safe_path

    # ── Step 2: Evict broken/partial module cache entries ─────────────────
    # If a previous import attempt partially populated sys.modules with a
    # broken numpy/pandas, every subsequent `import pandas` returns the
    # same broken object from cache — path fixes have NO effect.
    _numpy_mods  = [k for k in list(sys.modules) if k == "numpy" or k.startswith("numpy.")]
    _pandas_mods = [k for k in list(sys.modules) if k == "pandas" or k.startswith("pandas.")]
    for _mod in _numpy_mods + _pandas_mods:
        sys.modules.pop(_mod, None)

    # ── Step 3: Import ─────────────────────────────────────────────────
    try:
        import pandas as _pd  # type: ignore
        return _pd
    except Exception as e:
        raise ImportError(
            f"Pandas/Numpy import failed even after path sanitization and "
            f"module-cache eviction.\n"
            f"Error: {e}\n"
            f"sys.path used: {sys.path[:8]} ..."
        ) from e

from core import config

from common.column_detector import detect_columns, validate_mapping
from common.llm_parser import detect_columns_with_llm
from core.logger import get_logger

logger = get_logger(__name__)

class ExcelRow:
    """Represents a single cleaned row from the file."""
    def __init__(self, raw: dict, row_index: int, mapping: dict):
        self.raw       = raw
        self.row_index = row_index

        _null_values = {s.upper() for s in config.NULL_VALUE_STRINGS}
        def get(concept: str) -> Optional[str]:
            col = mapping.get(concept)
            if col and col in raw:
                val = raw[col]
                global pd
                if pd is None:
                    pd = _safe_import_pandas()
                if pd.isna(val) or val is None: return None
                s = str(val).strip()
                return s if s and s.upper() not in _null_values else None
            return None

        self.nom     = get("raison_sociale") or get("enseigne") or get("nom_commercial") or get("denominationUsuelleEtablissement")
        
        if mapping.get("adresse") == "__COMPOSITE__":
            parts = [get(c) for c in ["adresse_numero", "adresse_typevoie", "adresse_libellevoie"]]
            parts = [p for p in parts if p]
            cp = get("code_postal")
            ville = get("ville")
            street = " ".join(parts)
            city_part = " ".join(filter(None, [cp, ville]))
            self.adresse = " ".join(filter(None, [street, city_part])) or None
        else:
            self.adresse = get("adresse")
        
        self.siren   = get("siren") or get("siret")
        self.category = get("libelle_activite") or get("activite") or get("forme_juridique")
        self.raw_context = json.dumps(raw, ensure_ascii=False)

        if self.nom and self.adresse:
            self.search_type = "RS_ADR"
        elif self.siren and self.adresse:
            self.search_type = "SIREN_ADR"
        elif self.nom:
             self.search_type = "RS_ADR"
        elif self.siren:
             self.search_type = "SIREN_ADR"
        else:
            self.search_type = "SKIP"

        from domain.search.phone_extractor import normalize_phone, is_valid_french_phone
        
        restored_alt_phones = []
        for ks, val in raw.items():
            val_str = str(val).strip()
            if not val_str or val_str.lower() in config.NULL_VALUE_STRINGS:
                continue

            # Reconstruct phone_list from Alt_Phone columns
            if ks.startswith("AI_Alt_Phone_") and not ks.endswith("_Conf"):
                # VALIDATION: Only restore if it's not a blocked number
                digits = re.sub(r"\D", "", val_str)
                if is_valid_french_phone(digits):
                    restored_alt_phones.append({"num": val_str, "score": 80, "source": "previous_run"})
                else:
                    logger.debug(f"🚫 [Restoration] Dropping blocked number {val_str} from {ks}")
        
        raw_phone = get("telephone") or get("phone") or get("téléphone") or get("__phone")
        self.phone = normalize_phone(raw_phone) if raw_phone else None

        raw_agent = get("agent_phone") or get("__agent_phone")
        self.agent_phone = normalize_phone(raw_agent) if raw_agent else None

        self.status = ""
        etat_val = get("Etat") or get("stat")
        raw_status = str(etat_val).upper() if etat_val else ""
        
        if raw_status == "DONE":
            # Hardened check: If DONE, we MUST have a valid phone
            if self.phone or self.agent_phone:
                self.status = "DONE"
            else:
                logger.warning(f"⚠️ [Row {self.row_index}] Downgrading 'DONE' to 'NO TEL' because no valid phone was found.")
                self.status = "NO TEL"
        elif "NO" in raw_status and "TEL" in raw_status:
            self.status = "NO TEL"
        elif raw_status in ["SKIP", "ERROR", "LOW_CONF"]:
            self.status = raw_status

        # Safeguard: if marked DONE but phone is invalid/trash (e.g. "A"), reset status to re-process
        if self.status == "DONE" and not self.phone and not self.agent_phone:
            self.status = ""

        self.enriched_fields: dict = {}
        if restored_alt_phones:
            self.enriched_fields["phone_list"] = restored_alt_phones
        self.raw_ai_responses: list = []
        self.search_queries_used: list = []
        self.processing_start_ts: float = 0.0
        self.processing_end_ts: float = 0.0
        self.captcha_hits: int = 0
        self.is_clone: bool = False

        # ── 6. Restore enriched fields from previous AI runs (if checkpoint is missing) ──
        for k, v in raw.items():
            ks = str(k)
            if ks.startswith("AI_") and ks not in ["AI_Phone", "AI_Phone_Responsable", "AI_Status", "AI_Final_Status", "AI_Result_Phone"] and not ks.startswith("AI_Alt_Phone"):
                field_key = ks.replace("AI_", "").lower()
                if v and not pd.isna(v) and str(v).strip().upper() not in _null_values:
                    self.enriched_fields[field_key] = {"value": str(v), "source": "previous_run", "was_empty": False}

    def get_fingerprint(self) -> str:
        if self.siren and len(self.siren) >= 9:
            return f"SIREN:{self.siren}"
        n = re.sub(r'[^a-z0-9]', '', str(self.nom or "").lower())
        a = re.sub(r'[^a-z0-9]', '', str(self.adresse or "").lower())
        return f"NA:{n}|{a}"

    def get_search_name(self) -> str:
        return self.nom if self.nom else (self.siren or "")

    def to_dict(self) -> dict:
        """
        Produce a flat dictionary for Pandas export.
        Ensures AI-enriched columns are prefixed and formatted consistently.
        """
        result = dict(self.raw)
        
        # 1. Internal metadata (hidden in final Excel by writer)
        result.update({
            "__row_index":    self.row_index,
            "__search_type":  self.search_type,
            "__phone":        self.phone or "",
            "__agent_phone":  self.agent_phone or "",
            "__status":       self.status,
        })
        
        # 2. Main AI Outputs (consistent naming for user visibility)
        # Use config.STATUS_COLUMN_NAME as the primary key for the status column
        status_col = config.STATUS_COLUMN_NAME or "AI_Status"
        
        # FINAL SAFETY: If marked DONE but no phone was found/kept, downgrade to NO TEL.
        # This prevents the "Empty Done lines" reported by the user.
        display_status = self.status
        has_phone = bool(self.phone or self.agent_phone)
        if display_status == "DONE" and not has_phone:
            display_status = "NO TEL"

        result["AI_Phone"] = self.phone or ""
        result["AI_Phone_Responsable"] = self.agent_phone or ""
        result[status_col] = display_status

        # 3. Expand multi-phone list into columns
        phone_list = self.enriched_fields.get("phone_list", [])
        if isinstance(phone_list, list):
            for i, item in enumerate(phone_list, 1):
                if i > 5: break # Cap at 5 alternative phones
                result[f"AI_Alt_Phone_{i}"] = item.get("num")
                result[f"AI_Alt_Phone_{i}_Conf"] = f"{item.get('score')}%"

        # 4. Add other enriched fields (Email, Siren, etc.)
        for field, data in self.enriched_fields.items():
            if field in ("phone_list", "final_confidence", "tier", "validation_error"):
                continue
            
            # Standardize column name: AI_Email, AI_Website, etc.
            col_name = f"AI_{field.replace('_', ' ').title().replace(' ', '_')}"
            
            if isinstance(data, dict) and "value" in data:
                result[col_name] = data["value"]
            else:
                result[col_name] = str(data)

        # 5. Provenance & Performance Meta
        best_source = "N/A"
        if self.phone and phone_list and isinstance(phone_list, list):
            for item in phone_list:
                if item.get("num") == self.phone:
                    best_source = item.get("source")
                    break
        
        result["AI_Scrap_Source"] = best_source
        result["AI_Confidence_Score"] = f"{self.enriched_fields.get('final_confidence', 0)}%"
        
        if self.processing_start_ts and self.processing_end_ts:
            result["AI_Latency_Sec"] = round(self.processing_end_ts - self.processing_start_ts, 1)
        
        # Clear legacy mapping keys to avoid column pollution
        for key in ["__fingerprint", "AI_Final_Status", "AI_Result_Phone"]:
            if key in result: result.pop(key)

        return result

    def clone(self):
        """Create a deep copy of this row for multiple occurrences."""
        import copy
        new_row = copy.copy(self)
        new_row.is_clone = True
        new_row.enriched_fields = copy.deepcopy(self.enriched_fields)
        new_row.raw_ai_responses = copy.deepcopy(self.raw_ai_responses)
        new_row.search_queries_used = copy.deepcopy(self.search_queries_used)
        return new_row

def read_excel(filepath: str) -> Tuple[List[ExcelRow], dict]:
    """Pandas-based universal file reader."""
    global pd
    if pd is None:
        pd = _safe_import_pandas()

    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    ext = os.path.splitext(filepath)[1].lower()
    logger.info(f"[Reader] Loading file with Pandas: {os.path.basename(filepath)}")

    try:
        if ext == ".csv":
            df = pd.read_csv(filepath, sep=None, engine='python', dtype=str, on_bad_lines='skip')
        elif ext in [".xlsx", ".xls"]:
            df = pd.read_excel(filepath, dtype=str)
        elif ext == ".json":
            # Avoid dtype=str (pandas typing overload mismatch across versions)
            df = pd.read_json(filepath)
        else:
            raise ValueError(f"Unsupported format: {ext}")
    except Exception as e:
        logger.error(f"[Reader] Pandas failed to read {filepath}: {e}")
        return [], {}

    if df.empty:
        return [], {}

    # Clean headers: remove newlines, strip spaces, AND strip literal quotes
    df.columns = [str(c).replace('\n', ' ').strip(' "\'') for c in df.columns]
    headers = list(df.columns)
    mapping = detect_columns(headers)
    validation = validate_mapping(mapping)

    # On force le LLM si les heuristiques ont raté la Raison Sociale, l'Adresse ou l'Activité
    # afin de récupérer un maximum de contexte pour la recherche.
    if not validation.get("has_raison_sociale") or not validation.get("has_adresse") or not mapping.get("activite"):
        logger.warning("[Reader] Missing key fields (RS, Address, or Activity). Trying LLM mapping via OpenRouter...")
        sample_data = df.head(3).values.tolist()
        llm_mapping = asyncio.run(detect_columns_with_llm(headers, sample_data))
        if llm_mapping:
            # On ne met à jour que les clés trouvées par le LLM (sans écraser avec des None)
            mapping.update({k: v for k, v in llm_mapping.items() if v is not None})
            validation = validate_mapping(mapping)

    rows: List[ExcelRow] = []
    for raw_idx, row_series in df.iterrows():
        # Ensure deterministic int row index even if pandas index type isn't int.
        # Avoid calling int() directly on unknown pandas index types (static typing warnings).
        row_num: int
        try:
            raw_idx_str = str(raw_idx).strip()
            # If it's numeric, parse; otherwise fallback.
            row_num = int(raw_idx_str) if raw_idx_str.isdigit() else len(rows)
        except Exception:
            row_num = len(rows)
        raw_dict = row_series.to_dict()
        statut_cols = [c for c in headers if any(k in c.lower() for k in ["statut", "état", "etat"])]
        if any("radi" in str(raw_dict.get(sc, "")).lower() for sc in statut_cols):
            continue

        excel_row = ExcelRow(raw=raw_dict, row_index=row_num + 2, mapping=mapping)
        if excel_row.siren:
            excel_row.siren = re.sub(r'\D', '', str(excel_row.siren)).zfill(9)
            if len(excel_row.siren) > 9: excel_row.siren = excel_row.siren[:9]
        rows.append(excel_row)

    logger.info(f"[Reader] Loaded {len(rows)} rows via Pandas.")
    return rows, mapping
