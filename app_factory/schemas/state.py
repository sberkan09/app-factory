"""LangGraph paylaşılan state (ARCHITECTURE.md §1.2).

Kontrat nesneleri checkpointer serileştirmesi için dict olarak saklanır
(pydantic .model_dump() / model_validate ile dönüştürülür).
"""

import operator
from typing import Annotated, Any, Literal, TypedDict


class PipelineState(TypedDict, total=False):
    run_id: str
    idea_prompt: str
    platform: str  # "flutter" | "react-native"
    phase: Literal[
        "idea", "spec", "design", "coding", "qa", "visual_qa",
        "release", "awaiting_approval", "deploying", "done", "failed",
    ]

    app_concept: dict[str, Any]
    app_spec: dict[str, Any]
    design_spec: dict[str, Any]

    app_id: str  # applicationId / bundle id (spec'ten deterministik türetilir)
    workspace_path: str
    scaffolded: bool  # native platform iskeleti (flutter create / expo) kuruldu mu
    code_diff_history: list[str]  # her coder iterasyonunun unified diff'i (denetim izi)
    # Yalnızca mevcut self-healing turundaki BAŞARISIZ düzeltme denemeleri:
    # [{"iteration", "fingerprint", "error_summary", "diff"}]. Build geçince
    # veya insan yeni tur başlatınca sıfırlanır.
    fix_attempts: list[dict[str, Any]]

    build_result: dict[str, Any]
    build_ok: bool
    qa_iteration: int
    qa_error_fingerprints: list[str]

    visual_report: dict[str, Any]
    visual_ok: bool
    visual_iteration: int

    release_candidate: dict[str, Any]
    human_decision: Literal["pending", "approved", "rejected"]
    human_feedback: str

    escalation_level: Literal["standard", "escalated"]
    circuit_breaker_tripped: bool
    failure_reason: str
    deploy_message: str

    # Her LLM çağrısının token/maliyet kaydı (reducer: node'lar ekleme yapar)
    llm_calls: Annotated[list[dict[str, Any]], operator.add]
