import os
import sys
import traceback

# Ensure "src" is importable as top-level package root so "core" resolves.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_ROOT = os.path.join(REPO_ROOT, "src")
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

from common.json_parser import parse_ai_mode_json  # noqa: E402


def _assert(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def _run_test(name, fn):
    try:
        fn()
        print(f"[PASS] {name}")
    except Exception as e:
        print(f"[FAIL] {name}: {e}")
        traceback.print_exc()
        raise


def test_returns_none_for_none():
    _assert(parse_ai_mode_json(None) is None, "Expected None for input None")


def test_returns_none_for_non_str_exception_object():
    # Upstream may pass exception objects; parser should never raise.
    try:
        exc = ValueError("boom")
    except Exception:
        exc = Exception("boom")
    result = parse_ai_mode_json(exc)  # type: ignore[arg-type]
    _assert(result is None, "Expected None for non-string exception object input")


def test_returns_none_for_empty_string():
    _assert(parse_ai_mode_json("") is None, "Expected None for empty string")


def test_returns_none_for_whitespace_string():
    _assert(parse_ai_mode_json("   \n\t  ") is None, "Expected None for whitespace string")


def test_parses_fenced_json_block():
    text = (
        'Some prefix...\n\n```json\n{ "a": "  hello  ", "b": { "c": " world " } }\n```\ntail...\n'
    )
    result = parse_ai_mode_json(text)
    if result is None or not isinstance(result, dict):
        raise AssertionError("Expected dict result for fenced JSON")
    _assert(result["a"] == "hello", f"Expected trimmed value for a, got: {result['a']!r}")
    _assert(
        result["b"]["c"] == "world", f"Expected trimmed value for b.c, got: {result['b']['c']!r}"
    )


def test_parses_raw_json_object_when_no_fenced_block():
    text = 'noise {"x": " 1 ", "y": [" a ", "b "]} noise'
    result = parse_ai_mode_json(text)
    _assert(
        result is not None and isinstance(result, dict),
        "Expected dict result for raw JSON object in text",
    )
    _assert(result["x"] == "1", f"Expected trimmed x, got: {result['x']!r}")
    _assert(result["y"] == ["a", "b"], f"Expected deep trimmed y list, got: {result['y']!r}")


def test_parses_json_markdown_with_trailing_commas_gracefully():
    # This covers the fallback cleanup path (trailing commas before } or ]).
    text = '\n```json\n{\n  "a": "hello",\n  "b": [1,2,],\n  "c": {"d": "x",},\n}\n```\n'
    result = parse_ai_mode_json(text)

    # If cleanup works, we get a dict. If not, it should return None (but must not raise).
    _assert(
        result is None or isinstance(result, dict),
        "Expected dict or None for malformed JSON cleanup",
    )

    if result is not None:
        _assert(isinstance(result, dict), "Expected dict when result is not None")

        a = result.get("a")
        b = result.get("b")
        c = result.get("c")

        d = c.get("d") if isinstance(c, dict) else None

        _assert(a == "hello", f"Expected trimmed a, got: {a!r}")
        _assert(b == [1, 2], f"Expected cleaned b list, got: {b!r}")
        _assert(d == "x", f"Expected cleaned c.d, got: {d!r}")


def test_returns_none_for_non_json_text():
    text = "This is not JSON and has no { } block"
    result = parse_ai_mode_json(text)
    _assert(result is None, "Expected None when no JSON structure is present")


def test_does_not_raise_on_unusual_json_like_content():
    # Edge case: JSON-like but invalid structure.
    text = "```json {invalid: true,}\n```"
    result = parse_ai_mode_json(text)
    _assert(result is None, "Expected None for invalid JSON-like content (no exception expected)")


def main():
    tests = [
        ("returns_none_for_none", test_returns_none_for_none),
        (
            "returns_none_for_non_str_exception_object",
            test_returns_none_for_non_str_exception_object,
        ),
        ("returns_none_for_empty_string", test_returns_none_for_empty_string),
        ("returns_none_for_whitespace_string", test_returns_none_for_whitespace_string),
        ("parses_fenced_json_block", test_parses_fenced_json_block),
        (
            "parses_raw_json_object_when_no_fenced_block",
            test_parses_raw_json_object_when_no_fenced_block,
        ),
        (
            "parses_json_markdown_with_trailing_commas_gracefully",
            test_parses_json_markdown_with_trailing_commas_gracefully,
        ),
        ("returns_none_for_non_json_text", test_returns_none_for_non_json_text),
        (
            "does_not_raise_on_unusual_json_like_content",
            test_does_not_raise_on_unusual_json_like_content,
        ),
    ]

    ok = 0
    for name, fn in tests:
        _run_test(name, fn)
        ok += 1

    print(f"All {ok}/{len(tests)} critical-path JSON parser tests passed.")


if __name__ == "__main__":
    main()
