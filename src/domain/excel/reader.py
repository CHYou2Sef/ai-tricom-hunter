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

import pandas as pd
import os
import json
import re
import asyncio
from typing import List, Optional, Tuple

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

        def get(concept: str) -> Optional[str]:
            col = mapping.get(concept)
            if col and col in raw:
                val = raw[col]
                if pd.isna(val) or val is None: return None
                s = str(val).strip()
                return s if s and s.lower() not in ("none", "nan", "") else None
            return None

        self.nom     = get("raison_sociale") or get("enseigne") or get("nom_commercial")
        
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

        self.status = ""
        etat_val = get("Etat") or get("stat")
        if etat_val and str(etat_val).upper() == "DONE":
            self.status = "DONE"
        elif etat_val and "NO" in str(etat_val).upper() and ("TEL" in str(etat_val).upper()):
            self.status = "NO TEL"
        
        from domain.search.phone_extractor import normalize_phone
        raw_phone = get("telephone") or get("phone") or get("téléphone") or get("__phone")
        self.phone = normalize_phone(raw_phone) if raw_phone else None

        raw_agent = get("agent_phone") or get("__agent_phone")
        self.agent_phone = normalize_phone(raw_agent) if raw_agent else None

        # Safeguard: if marked DONE but phone is invalid/trash (e.g. "A"), reset status to re-process
        if self.status == "DONE" and not self.phone and not self.agent_phone:
            self.status = ""

        self.enriched_fields: dict = {}
        self.raw_ai_responses: list = []
        self.search_queries_used: list = []
        self.processing_start_ts: float = 0.0
        self.processing_end_ts: float = 0.0
        self.captcha_hits: int = 0

    def get_fingerprint(self) -> str:
        if self.siren and len(self.siren) >= 9:
            return f"SIREN:{self.siren}"
        n = re.sub(r'[^a-z0-9]', '', str(self.nom or "").lower())
        a = re.sub(r'[^a-z0-9]', '', str(self.adresse or "").lower())
        return f"NA:{n}|{a}"

    def get_search_name(self) -> str:
        return self.nom if self.nom else (self.siren or "")

    def to_dict(self) -> dict:
        result = dict(self.raw)
        result.update({
            "__row_index":    self.row_index,
            "__search_type":  self.search_type,
            "__phone":        self.phone or "",
            "__agent_phone":  self.agent_phone or "",
            "__status":       self.status,
        })
        
        # Expand multi-phone list into columns
        phone_list = self.enriched_fields.get("phone_list", [])
        for i, item in enumerate(phone_list, 1):
            result[f"AI_Phone_{i}"] = item.get("num")
            result[f"AI_Phone_{i}_Conf"] = f"{item.get('score')}%"
            # Optional: result[f"AI_Phone_{i}_Source"] = item.get("source")

        # 3. Add other enriched fields (Email, Siren, etc.)
        for field, data in self.enriched_fields.items():
            if field != "phone_list":
                if isinstance(data, dict) and "value" in data:
                    result[f"AI_{field.capitalize()}"] = data["value"]
                else:
                    result[f"AI_{field.capitalize()}"] = str(data)

        # 4. Add AI Provenance & Quality Validation
        best_source = "N/A"
        phone_list = self.enriched_fields.get("phone_list", [])
        if self.phone and phone_list:
            for item in phone_list:
                if item.get("num") == self.phone:
                    best_source = item.get("source")
                    break
        result["AI_Scrap_Source"] = best_source
        result["AI_Confidence_Score"] = f"{self.enriched_fields.get('final_confidence', 0)}%"
        
        # Add Per-Row Latency
        if self.processing_start_ts and self.processing_end_ts:
            result["AI_Latency_Sec"] = round(self.processing_end_ts - self.processing_start_ts, 1)

        return result

    def clone(self):
        """Create a deep copy of this row for multiple occurrences."""
        import copy
        new_row = copy.copy(self)
        new_row.enriched_fields = copy.deepcopy(self.enriched_fields)
        new_row.raw_ai_responses = copy.deepcopy(self.raw_ai_responses)
        new_row.search_queries_used = copy.deepcopy(self.search_queries_used)
        return new_row

def read_excel(filepath: str) -> Tuple[List[ExcelRow], dict]:
    """Pandas-based universal file reader."""
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
            df = pd.read_json(filepath, dtype=str)
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

    if not validation["can_search_rs"] and not validation["can_search_siren"]:
        logger.warning("[Reader] Heuristics failed. Trying LLM mapping...")
        sample_data = df.head(3).values.tolist()
        llm_mapping = asyncio.run(detect_columns_with_llm(headers, sample_data))
        if llm_mapping:
            mapping.update({k: v for k, v in llm_mapping.items() if v})
            validation = validate_mapping(mapping)

    rows: List[ExcelRow] = []
    for idx, row_series in df.iterrows():
        raw_dict = row_series.to_dict()
        statut_cols = [c for c in headers if any(k in c.lower() for k in ["statut", "état", "etat"])]
        if any("radi" in str(raw_dict.get(sc, "")).lower() for sc in statut_cols):
            continue

        excel_row = ExcelRow(raw=raw_dict, row_index=int(idx) + 2, mapping=mapping)
        if excel_row.siren:
            excel_row.siren = re.sub(r'\D', '', str(excel_row.siren)).zfill(9)
            if len(excel_row.siren) > 9: excel_row.siren = excel_row.siren[:9]
        rows.append(excel_row)

    logger.info(f"[Reader] Loaded {len(rows)} rows via Pandas.")
    return rows, mapping
