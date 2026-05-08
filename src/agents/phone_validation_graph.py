"""
LangGraph PhoneValidationGraph
--------------------------------
Implements a strict, deterministic cross-method agreement gate for phone numbers.

Operator requirement enforced:
- accept a phone only if it appears in >= 2 distinct scraping methods
- never re-insert a phone that is already in the previously accepted set (real-time per line)
- always canonicalize via normalize_phone() before comparison/storage

Backward compatibility:
- controlled by ENABLE_CROSS_METHOD_VALIDATION env flag (phone_hunter.py wiring)

This module is designed to be unit-testable with mocked method_phones input.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, TypedDict, Literal

from core import config
from core.logger import get_logger

from domain.search.phone_extractor import normalize_phone
from services.phone_verifier import verify_phone_neutrino

logger = get_logger(__name__)

Status = Literal["APPROVED", "REJECTED", "NEEDS_REVIEW"]


class PhoneCandidate(TypedDict, total=False):
    canonical_phone: str
    method_id: str
    evidence_source: str
    evidence_priority: int
    raw_value: str


class NeutrinoResult(TypedDict, total=False):
    valid: bool
    confidence: float
    number_type: str
    details: Dict[str, Any]


class PhoneValidationState(TypedDict, total=False):
    entity_fingerprint: str
    existing_phones_set: Set[str]
    method_phones: Dict[str, Set[str]]  # method_id -> phones (canonical)
    agreed_candidates: List[PhoneCandidate]
    accepted_phones: List[str]
    validation_results: Dict[str, NeutrinoResult]
    trust_scores: Dict[str, float]
    status: Status
    phone_validation_provenance: str  # JSON string


# Evidence priority: larger means stronger / preferred
DEFAULT_EVIDENCE_PRIORITY: Dict[str, int] = {
    "tel_href": 100,
    "google_kp": 95,
    "schema_jsonld": 92,
    "llm_extract": 70,
    "ai_std": 90,
    "ai_expert": 90,
    "data_phone": 88,
    "meta": 84,
    "firecrawl_premium": 90,
    "discovery_web": 80,
    "discovery_fb": 80,
    "discovery_li": 80,
    "web_scrap": 75,
    "google_scrap": 75,
    "regex_text": 60,
    "layer2": 65,
}


def _sorted_deterministic(items: List[str]) -> List[str]:
    return sorted(items, key=lambda x: (len(x), x))


def _build_provenance(
    entity_fingerprint: str,
    agreed: List[Dict[str, Any]],
    accepted: List[str],
    validation_results: Dict[str, Any],
    trust_scores: Dict[str, float],
    status: Status,
) -> str:
    payload = {
        "entity_fingerprint": entity_fingerprint,
        "status": status,
        "agreed_candidates": agreed,
        "accepted_phones": accepted,
        "validation_results": validation_results,
        "trust_scores": trust_scores,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def collect_candidates(state: PhoneValidationState) -> PhoneValidationState:
    """
    Input: method_phones already canonicalized (phone_hunter supplies it).
    Output: agreed_candidates computed later; here we just normalize/dedup structures.
    """
    if "existing_phones_set" not in state or state["existing_phones_set"] is None:
        state["existing_phones_set"] = set()

    method_phones = state.get("method_phones") or {}
    normalized_method_phones: Dict[str, Set[str]] = {}

    for method_id, phones in method_phones.items():
        s: Set[str] = set()
        if not phones:
            normalized_method_phones[method_id] = s
            continue
        for p in phones:
            norm = normalize_phone(p)
            if norm:
                s.add(norm)
        normalized_method_phones[method_id] = s

    state["method_phones"] = normalized_method_phones
    state.setdefault("accepted_phones", [])
    state.setdefault("validation_results", {})
    state.setdefault("trust_scores", {})
    state["agreed_candidates"] = []
    state.setdefault("status", "NEEDS_REVIEW")
    return state


def cross_method_agreement(state: PhoneValidationState) -> PhoneValidationState:
    """
    Keep phones that appear in >=2 distinct method_id sets.
    Sort deterministically:
      1) evidence_priority desc (max among agreeing methods)
      2) canonical_phone asc (stable)
    """
    method_phones: Dict[str, Set[str]] = state.get("method_phones") or {}
    if not method_phones:
        state["agreed_candidates"] = []
        state["status"] = "NEEDS_REVIEW"
        return state

    phone_to_methods: Dict[str, Set[str]] = {}
    for method_id, phones in method_phones.items():
        for p in phones:
            phone_to_methods.setdefault(p, set()).add(method_id)

    agreed: List[str] = [p for p, mids in phone_to_methods.items() if len(mids) >= 2]
    if not agreed:
        state["agreed_candidates"] = []
        state["status"] = "NEEDS_REVIEW"
        return state

    agreed_candidate_dicts: List[Dict[str, Any]] = []
    for p in agreed:
        mids = sorted(phone_to_methods[p])
        max_prio = 0
        for mid in mids:
            max_prio = max(max_prio, DEFAULT_EVIDENCE_PRIORITY.get(mid, 10))

        agreed_candidate_dicts.append(
            {
                "canonical_phone": p,
                "method_ids": mids,
                "evidence_priority": max_prio,
            }
        )

    # Deterministic ordering
    agreed_candidate_dicts.sort(key=lambda d: (-int(d["evidence_priority"]), d["canonical_phone"]))

    candidates: List[PhoneCandidate] = []
    for d in agreed_candidate_dicts:
        # Choose one representative method_id for provenance (highest priority among mids)
        rep_mid = max(
            d["method_ids"],
            key=lambda mid: DEFAULT_EVIDENCE_PRIORITY.get(mid, 10),
        )
        candidates.append(
            {
                "canonical_phone": d["canonical_phone"],
                "method_id": rep_mid,
                "evidence_source": rep_mid,
                "evidence_priority": int(d["evidence_priority"]),
                "raw_value": d["canonical_phone"],
            }
        )

    state["agreed_candidates"] = candidates
    # default optimistic status; final decision after validation/commit
    state["status"] = "NEEDS_REVIEW"
    return state


def neutrino_validation(state: PhoneValidationState) -> PhoneValidationState:
    """
    Validate agreed candidates against Neutrino.
    If Neutrino is disabled or API fails, we mark NEEDS_REVIEW (failure safety).
    """
    if not getattr(config, "NEUTRINO_ENABLED", False):
        # Keep as needs review; commit will decide without neutrino.
        state["status"] = "NEEDS_REVIEW"
        return state

    results: Dict[str, NeutrinoResult] = {}
    trust_scores: Dict[str, float] = dict(state.get("trust_scores") or {})

    agreed = state.get("agreed_candidates") or []
    if not agreed:
        state["status"] = "NEEDS_REVIEW"
        return state

    agreed_phones = sorted({c["canonical_phone"] for c in agreed})
    for phone in agreed_phones:
        try:
            v_res = verify_phone_neutrino(phone)
            # Expected shape: {"valid": bool, "confidence": float, ...}
            if not v_res:
                results[phone] = {"valid": False, "confidence": 0.0, "details": {"error": "empty_response"}}
                continue

            # Normalize keys defensively
            valid = bool(v_res.get("valid", False))
            conf = float(v_res.get("confidence", 0.0) or 0.0)
            number_type = str(v_res.get("number_type", "") or v_res.get("type", "") or "")
            results[phone] = {
                "valid": valid,
                "confidence": conf,
                "number_type": number_type,
                "details": {k: v for k, v in v_res.items() if k not in {"valid", "confidence", "number_type", "type"}},
            }
            # Trust score combines evidence priority proxy + neutrino confidence.
            evidence_prio = max(DEFAULT_EVIDENCE_PRIORITY.get(mid, 10) for mid in state.get("method_phones", {}).keys())
            trust_scores[phone] = 0.6 * conf + 0.4 * min(100.0, float(evidence_prio))
        except Exception as e:
            logger.warning(f"[PhoneValidationGraph] Neutrino validation failed for {phone}: {e}")
            results[phone] = {"valid": False, "confidence": 0.0, "details": {"exception": str(e)}}
            trust_scores[phone] = 0.0

    state["validation_results"] = results
    state["trust_scores"] = trust_scores
    return state


def non_duplicate_insertion(state: PhoneValidationState) -> PhoneValidationState:
    """
    Insert agreed candidates into accepted_phones respecting:
    - never add already existing phones (existing_phones_set)
    - still deterministic ordering
    """
    existing: Set[str] = set(state.get("existing_phones_set") or set())
    accepted: List[str] = list(state.get("accepted_phones") or [])

    agreed = state.get("agreed_candidates") or []
    if not agreed:
        state["status"] = "NEEDS_REVIEW"
        state["accepted_phones"] = accepted
        state["existing_phones_set"] = existing
        return state

    # Deterministic iteration: sorted by (evidence_priority desc, canonical_phone asc)
    ordered = sorted(
        agreed,
        key=lambda c: (-int(c.get("evidence_priority", 0)), c.get("canonical_phone", "")),
    )

    inserted: List[str] = []
    for c in ordered:
        phone = c["canonical_phone"]
        if phone in existing:
            continue
        accepted.append(phone)
        inserted.append(phone)
        existing.add(phone)

    state["accepted_phones"] = accepted
    state["existing_phones_set"] = existing

    # provisional decision: if inserted non-empty -> APPROVED else NEEDS_REVIEW
    state["status"] = "APPROVED" if inserted else "NEEDS_REVIEW"
    return state


def commit(state: PhoneValidationState) -> PhoneValidationState:
    """
    Choose best phone for AI_Phone and set provenance JSON string.
    This function does NOT mutate ExcelRow directly; phone_hunter will read state.
    """
    accepted = state.get("accepted_phones") or []
    if not accepted:
        state["status"] = "NEEDS_REVIEW"
        state["phone_validation_provenance"] = _build_provenance(
            entity_fingerprint=state.get("entity_fingerprint", ""),
            agreed=[],
            accepted=[],
            validation_results=state.get("validation_results") or {},
            trust_scores=state.get("trust_scores") or {},
            status="NEEDS_REVIEW",
        )
        return state

    # Determine best by max evidence priority among methods containing the phone.
    method_phones: Dict[str, Set[str]] = state.get("method_phones") or {}
    phone_to_best_prio: Dict[str, int] = {}
    for phone in accepted:
        best_prio = 0
        for mid, phones in method_phones.items():
            if phone in phones:
                best_prio = max(best_prio, DEFAULT_EVIDENCE_PRIORITY.get(mid, 10))
        phone_to_best_prio[phone] = best_prio

    # If neutrino provided, prefer valid higher confidence; failure safety:
    # if neutrino enabled and no validated valid phones exist => NEEDS_REVIEW.
    if getattr(config, "NEUTRINO_ENABLED", False):
        vres = state.get("validation_results") or {}
        valid_phones = [p for p in accepted if (vres.get(p, {}).get("valid") is True)]
        if not valid_phones:
            state["status"] = "NEEDS_REVIEW"
        else:
            # reduce accepted to valid set for choosing best
            accepted_valid = valid_phones
            accepted_sorted = sorted(
                accepted_valid,
                key=lambda p: (-phone_to_best_prio.get(p, 0), -float(state.get("trust_scores", {}).get(p, 0.0)), p),
            )
            best = accepted_sorted[0]
            state["status"] = "APPROVED"
    else:
        best = sorted(
            accepted,
            key=lambda p: (-phone_to_best_prio.get(p, 0), p),
        )[0]
        state["status"] = "APPROVED"

    # Provenance aligned to spec
    agreed = state.get("agreed_candidates") or []
    agreed_payload = [
        {
            "canonical_phone": c["canonical_phone"],
            "evidence_priority": int(c.get("evidence_priority", 0)),
            "method_id": c.get("method_id"),
        }
        for c in agreed
    ]

    state["phone_validation_provenance"] = _build_provenance(
        entity_fingerprint=state.get("entity_fingerprint", ""),
        agreed=agreed_payload,
        accepted=accepted,
        validation_results=state.get("validation_results") or {},
        trust_scores=state.get("trust_scores") or {},
        status=state.get("status", "NEEDS_REVIEW"),
    )

    # Store chosen best for downstream (phone_hunter)
    # (TypedDict doesn’t declare this field, but it is part of the runtime contract.)
    state["best_phone"] = best  # type: ignore[typeddict-item]
    return state


def build_phone_validation_graph():
    """
    Build and compile the LangGraph workflow.

    Important: we keep StateGraph typed with PhoneValidationState so LangGraph
    can register schemas correctly at runtime. Any static typing complaints
    should not affect runtime behaviour.
    """
    from langgraph.graph import StateGraph, END

    g = StateGraph(PhoneValidationState)  # type: ignore[bad-specialization]

    g.add_node("collect_candidates", collect_candidates)
    g.add_node("cross_method_agreement", cross_method_agreement)
    g.add_node("non_duplicate_insertion", non_duplicate_insertion)
    g.add_node("commit", commit)
    g.add_node("neutrino_validation", neutrino_validation)

    g.set_entry_point("collect_candidates")
    g.add_edge("collect_candidates", "cross_method_agreement")

    def _route_after_agreement(state: PhoneValidationState) -> str:
        return "neutrino_validation" if getattr(config, "NEUTRINO_ENABLED", False) else "non_duplicate_insertion"

    g.add_conditional_edges(
        "cross_method_agreement",
        _route_after_agreement,
        {
            "neutrino_validation": "neutrino_validation",
            "non_duplicate_insertion": "non_duplicate_insertion",
        },
    )

    g.add_edge("neutrino_validation", "non_duplicate_insertion")
    g.add_edge("non_duplicate_insertion", "commit")
    g.add_edge("commit", END)

    return g.compile()


_GRAPH: Any = None


def run_phone_validation_graph(state: Any) -> Any:
    """Run the compiled LangGraph with the provided state."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_phone_validation_graph()
    result: Any = _GRAPH.invoke(state)  # type: ignore[misc]
    return result
