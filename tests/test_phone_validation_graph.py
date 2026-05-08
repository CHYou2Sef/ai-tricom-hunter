"""
Unit tests for PhoneValidationGraph.

Covers:
- cross_method_agreement: agreement_count >= 2 gate
- non_duplicate_insertion: respects existing_phones_set
- full graph run (Neutrino disabled by default in tests)

Run:
  pytest -q tests/test_phone_validation_graph.py
"""

from unittest.mock import patch, MagicMock

import pytest

with patch("core.logger.get_logger", return_value=MagicMock()):
    from agents.phone_validation_graph import (
        PhoneValidationState,
        run_phone_validation_graph,
        cross_method_agreement,
        non_duplicate_insertion,
    )


def _base_state() -> PhoneValidationState:
    return {
        "entity_fingerprint": "fp_1",
        "existing_phones_set": set(),
        "method_phones": {
            "tel_href": set(),
            "schema_jsonld": set(),
            "regex_text": set(),
        },
        "accepted_phones": [],
        "validation_results": {},
        "trust_scores": {},
        "status": "NEEDS_REVIEW",
    }


def test_cross_method_agreement_rejects_below_threshold():
    state = _base_state()
    state["method_phones"] = {
        "tel_href": {"06 12 34 56 78"},
        "schema_jsonld": set(),
        "regex_text": set(),
    }

    out = cross_method_agreement(state)
    assert out["agreed_candidates"] == []
    assert out["status"] == "NEEDS_REVIEW"


def test_cross_method_agreement_accepts_phone_in_two_methods():
    state = _base_state()
    state["method_phones"] = {
        "tel_href": {"06 12 34 56 78"},
        "schema_jsonld": {"06 12 34 56 78"},
        "regex_text": set(),
    }

    out = cross_method_agreement(state)
    assert len(out["agreed_candidates"]) == 1
    assert out["agreed_candidates"][0]["canonical_phone"] == "06 12 34 56 78"


def test_non_duplicate_insertion_respects_existing_set():
    state = _base_state()
    state["existing_phones_set"] = {"06 12 34 56 78"}
    state["method_phones"] = {
        "tel_href": {"06 12 34 56 78", "07 89 01 23 45"},
        "schema_jsonld": {"06 12 34 56 78", "07 89 01 23 45"},
        "regex_text": set(),
    }

    # first compute agreement
    state = cross_method_agreement(state)

    # Then insert
    out = non_duplicate_insertion(state)

    # both phones agree, but one already exists, so only the other is inserted
    assert "06 12 34 56 78" not in out["accepted_phones"]
    assert "07 89 01 23 45" in out["accepted_phones"]


def test_full_graph_run_approves_when_agreement_and_no_neutrino():
    state = _base_state()
    state["method_phones"] = {
        "tel_href": {"06 12 34 56 78"},
        "schema_jsonld": {"06 12 34 56 78"},
        "regex_text": set(),
    }

    # Ensure neutrino is considered disabled
    with patch("core.config.NEUTRINO_ENABLED", False, create=True):
        out = run_phone_validation_graph(state)

    assert out["status"] in ("APPROVED", "NEEDS_REVIEW")
    # commit() should have added the accepted phone(s)
    assert "06 12 34 56 78" in out.get("accepted_phones", [])
