"""WP-02 acceptance: `data/.llm-cache/<sha256>.json` keying and round-trip (ADR-007)."""

from ce.llm import cache


def test_compute_key_stable_for_identical_inputs():
    a = cache.compute_key("p", 1, "rendered", "claude-haiku-4-5", None)
    b = cache.compute_key("p", 1, "rendered", "claude-haiku-4-5", None)
    assert a == b


def test_compute_key_changes_with_any_component():
    base = cache.compute_key("p", 1, "rendered", "claude-haiku-4-5", None)
    assert base != cache.compute_key("other-prompt", 1, "rendered", "claude-haiku-4-5", None)
    assert base != cache.compute_key("p", 2, "rendered", "claude-haiku-4-5", None)
    assert base != cache.compute_key("p", 1, "different", "claude-haiku-4-5", None)
    assert base != cache.compute_key("p", 1, "rendered", "claude-opus-5", None)
    assert base != cache.compute_key("p", 1, "rendered", "claude-haiku-4-5", {"type": "object"})


def test_write_then_read_round_trips(tmp_path):
    key = cache.compute_key("p", 1, "rendered", "claude-haiku-4-5", None)
    payload = {"content": "hello", "usd": 0.001}
    cache.write(tmp_path, key, payload)
    assert cache.read(tmp_path, key) == payload


def test_read_missing_key_returns_none(tmp_path):
    assert cache.read(tmp_path, "does-not-exist") is None
