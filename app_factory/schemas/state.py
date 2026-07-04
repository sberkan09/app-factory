"""LangGraph paylaşılan state (ARCHITECTURE.md §1.2).

Kontrat nesneleri checkpointer serileştirmesi için dict olarak saklanır
(pydantic .model_dump() / model_validate ile dönüştürülür).
"""

from typing import Any, Literal, TypedDict


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

    workspace_path: str
    code_diff_history: list[str]  # her coder iterasyonunun unified diff'i

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
