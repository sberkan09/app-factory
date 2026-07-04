"""Circuit breaker ve routing birim testleri (ARCHITECTURE.md §2.2)."""

from app_factory.graph.routing import (
    evaluate_build_failure,
    route_after_build,
    route_after_human,
    route_after_visual,
)
from app_factory.services.ci import error_fingerprint

LIMITS = dict(max_iterations=5, max_same_fingerprint=2, escalate_after=2)


def test_first_failure_retries_without_escalation():
    v = evaluate_build_failure(qa_iteration=1, fingerprints=[], new_fingerprint="aaa", **LIMITS)
    assert not v.tripped and not v.escalate


def test_escalates_after_threshold():
    v = evaluate_build_failure(qa_iteration=3, fingerprints=["a", "b"], new_fingerprint="c", **LIMITS)
    assert not v.tripped and v.escalate


def test_trips_at_max_iterations():
    v = evaluate_build_failure(qa_iteration=5, fingerprints=list("abcd"), new_fingerprint="e", **LIMITS)
    assert v.tripped


def test_trips_on_repeated_fingerprint_early():
    # Aynı hata 2. kez görülüyor -> 5 hakkı beklemeden erken çıkış
    v = evaluate_build_failure(qa_iteration=2, fingerprints=["same"], new_fingerprint="same", **LIMITS)
    assert v.tripped
    assert "no progress" in v.reason


def test_fingerprint_is_stable_across_line_numbers_and_paths():
    a = error_fingerprint("build", "Error at /tmp/x1/lib/main.dart:42: missing semicolon")
    b = error_fingerprint("build", "Error at /tmp/x9/lib/main.dart:57: missing semicolon")
    assert a == b


def test_fingerprint_differs_for_different_errors():
    a = error_fingerprint("build", "Error: missing semicolon")
    b = error_fingerprint("test", "Expected 3, got 4")
    assert a != b


def test_route_after_build():
    assert route_after_build({"build_ok": True}) == "visual_review"
    assert route_after_build({"build_ok": False, "circuit_breaker_tripped": True}) == "await_human"
    assert route_after_build({"build_ok": False}) == "code"


def test_route_after_visual():
    assert route_after_visual({"visual_ok": True}) == "build_release"
    assert route_after_visual({"visual_ok": False, "circuit_breaker_tripped": True}) == "await_human"
    assert route_after_visual({"visual_ok": False}) == "code"


def test_route_after_human():
    assert route_after_human({"human_decision": "approved"}) == "deploy"
    assert route_after_human({"human_decision": "rejected", "human_feedback": "rengi değiştir"}) == "code"
    assert route_after_human({"human_decision": "rejected", "human_feedback": ""}) == "end"
