"""Koşullu kenar mantığı + circuit breaker (ARCHITECTURE.md §2.2).

Router fonksiyonları state'i yalnızca OKUR (LangGraph kuralı); sayaç/bayrak
güncellemeleri node'larda yapılır. Breaker değerlendirmesi saf fonksiyon
olarak ayrıldı ki birim testlenebilsin.
"""

from __future__ import annotations

from dataclasses import dataclass

from app_factory.schemas.state import PipelineState


@dataclass
class BreakerVerdict:
    tripped: bool
    escalate: bool
    reason: str = ""


def evaluate_build_failure(
    *,
    qa_iteration: int,
    fingerprints: list[str],
    new_fingerprint: str,
    max_iterations: int,
    max_same_fingerprint: int,
    escalate_after: int,
) -> BreakerVerdict:
    """Yeni bir derleme hatası sonrası breaker kararı.

    - qa_iteration >= max_iterations -> kes (deneme hakkı bitti)
    - aynı fingerprint max_same_fingerprint kez görüldüyse -> kes
      (coder aynı hatayı yeniden üretiyor, ilerleme yok — erken çıkış)
    - qa_iteration > escalate_after -> güçlü modele eskale et
    """
    seen = fingerprints.count(new_fingerprint) + 1  # +1: bu hata dahil
    if qa_iteration >= max_iterations:
        return BreakerVerdict(True, False, f"Max iteration limit reached ({max_iterations})")
    if seen >= max_same_fingerprint:
        return BreakerVerdict(
            True, False,
            f"Same error fingerprint seen {seen} times — no progress, breaking loop",
        )
    return BreakerVerdict(False, qa_iteration > escalate_after)


def route_after_build(state: PipelineState) -> str:
    if state.get("build_ok"):
        return "visual_review"
    if state.get("circuit_breaker_tripped"):
        return "await_human"
    return "code"


def route_after_visual(state: PipelineState) -> str:
    if state.get("visual_ok"):
        return "build_release"
    if state.get("circuit_breaker_tripped"):
        return "await_human"
    return "code"


def route_after_human(state: PipelineState) -> str:
    decision = state.get("human_decision")
    if decision == "approved":
        return "deploy"
    if decision == "rejected" and state.get("human_feedback"):
        return "code"
    return "end"
