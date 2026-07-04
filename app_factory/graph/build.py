"""LangGraph StateGraph kurulumu (ARCHITECTURE.md §1.4).

Akış:
  idea -> spec -> design -> code -> build_and_test --(fail)--> code   (self-heal)
                                        |--(pass)--> visual_review --(fail)--> code
                                                          |--(pass)--> build_release -> await_human
  await_human --(approve)--> deploy -> END
              --(reject+feedback)--> code
              --(abort / breaker)--> END
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from app_factory.agents import (
    CoderAgent,
    DesignAgent,
    IdeaAgent,
    QACompilerAgent,
    SpecAgent,
    VisualReviewerAgent,
)
from app_factory.config import Settings
from app_factory.graph.routing import (
    evaluate_build_failure,
    route_after_build,
    route_after_human,
    route_after_visual,
)
from app_factory.schemas.contracts import (
    AppSpec,
    CodeBundle,
    DesignSpec,
    ErrorReport,
    ReleaseCandidate,
    VisualQAReport,
)
from app_factory.schemas.state import PipelineState
from app_factory.services.deployment import DeploymentProvider
from app_factory.services.device_farm import DeviceFarmProvider
from app_factory.services.workspace import WorkspaceService


@dataclass
class PipelineDeps:
    settings: Settings
    workspace: WorkspaceService
    idea_agent: IdeaAgent
    spec_agent: SpecAgent
    design_agent: DesignAgent
    coder_agent: CoderAgent
    qa_agent: QACompilerAgent
    visual_agent: VisualReviewerAgent
    device_farm: DeviceFarmProvider
    deployment: DeploymentProvider


def build_graph(deps: PipelineDeps, checkpointer=None):
    s = deps.settings

    def idea_node(state: PipelineState) -> dict:
        concept = deps.idea_agent.run(state["idea_prompt"])
        return {"phase": "spec", "app_concept": concept.model_dump()}

    def spec_node(state: PipelineState) -> dict:
        from app_factory.schemas.contracts import AppConcept

        concept = AppConcept.model_validate(state["app_concept"])
        spec = deps.spec_agent.run(concept, state.get("platform", "flutter"))
        return {"phase": "design", "app_spec": spec.model_dump()}

    def design_node(state: PipelineState) -> dict:
        spec = AppSpec.model_validate(state["app_spec"])
        design = deps.design_agent.run(spec)
        return {"phase": "coding", "design_spec": design.model_dump()}

    def code_node(state: PipelineState) -> dict:
        spec = AppSpec.model_validate(state["app_spec"])
        design = DesignSpec.model_validate(state["design_spec"])

        error_report = None
        build_result = state.get("build_result")
        if build_result and build_result.get("error_report"):
            error_report = ErrorReport.model_validate(build_result["error_report"])

        # Görsel QA'dan dönüşte bulgular coder'a UI-fix görevi olarak gider
        human_feedback = state.get("human_feedback") or None
        visual_report = state.get("visual_report")
        if not state.get("visual_ok", True) and visual_report and error_report is None:
            report = VisualQAReport.model_validate(visual_report)
            human_feedback = (
                "Görsel QA bulguları (blocker'ları düzelt):\n" + report.model_dump_json(indent=2)
            )

        is_first_pass = not state.get("code_diff_history")
        existing = None if is_first_pass else deps.workspace.read_all(state["run_id"])

        bundle: CodeBundle = deps.coder_agent.run(
            spec,
            design,
            error_report=error_report,
            human_feedback=human_feedback,
            existing_files=existing,
            diff_history=state.get("code_diff_history"),
            escalated=state.get("escalation_level") == "escalated",
        )
        diff = deps.workspace.apply_bundle(state["run_id"], bundle)
        history = list(state.get("code_diff_history", []))
        history.append(diff or "(no changes)")
        return {
            "phase": "qa",
            "workspace_path": str(deps.workspace.path_for(state["run_id"])),
            "code_diff_history": history,
            "human_feedback": "",  # işlendi; tekrar tetiklenmesin
        }

    def build_and_test_node(state: PipelineState) -> dict:
        iteration = state.get("qa_iteration", 0) + 1
        escalated = state.get("escalation_level") == "escalated"
        result = deps.qa_agent.run(
            Path(state["workspace_path"]),
            state.get("platform", "flutter"),
            iteration,
            analyze_with_llm=escalated,
        )
        update: dict = {
            "build_result": result.model_dump(),
            "qa_iteration": iteration,
        }
        if result.status in ("success", "skipped"):
            update.update(build_ok=True, phase="visual_qa")
            return update

        fp = result.error_report.fingerprint
        fingerprints = list(state.get("qa_error_fingerprints", []))
        verdict = evaluate_build_failure(
            qa_iteration=iteration,
            fingerprints=fingerprints,
            new_fingerprint=fp,
            max_iterations=s.max_qa_iterations,
            max_same_fingerprint=s.max_same_fingerprint,
            escalate_after=s.escalate_after_iteration,
        )
        fingerprints.append(fp)
        update.update(
            build_ok=False,
            qa_error_fingerprints=fingerprints,
            circuit_breaker_tripped=verdict.tripped,
            escalation_level="escalated" if (verdict.escalate or escalated) else "standard",
        )
        if verdict.tripped:
            update.update(phase="failed", failure_reason=verdict.reason,
                          human_decision="pending")
        else:
            update["phase"] = "coding"
        return update

    def visual_review_node(state: PipelineState) -> dict:
        spec = AppSpec.model_validate(state["app_spec"])
        design = DesignSpec.model_validate(state["design_spec"])
        iteration = state.get("visual_iteration", 0) + 1

        artifact = (state.get("build_result") or {}).get("artifact_path")
        screenshots = deps.device_farm.capture(Path(state["workspace_path"]), spec, artifact)
        report = deps.visual_agent.run(design, screenshots)

        update: dict = {"visual_report": report.model_dump(), "visual_iteration": iteration}
        blockers = [i for i in report.issues if i.severity == "blocker"]
        if report.verdict in ("pass", "skipped") or not blockers:
            update.update(visual_ok=True, phase="release")
        elif iteration >= s.max_visual_iterations:
            update.update(
                visual_ok=False,
                circuit_breaker_tripped=True,
                phase="failed",
                failure_reason=f"Visual QA blockers persisted after {iteration} iterations",
                human_decision="pending",
            )
        else:
            update.update(visual_ok=False, phase="coding")
        return update

    def build_release_node(state: PipelineState) -> dict:
        spec = AppSpec.model_validate(state["app_spec"])
        artifact = deps.qa_agent.ci.build_artifact(
            Path(state["workspace_path"]), state.get("platform", "flutter")
        )
        concept = state.get("app_concept", {})
        rc = ReleaseCandidate(
            app_name=spec.app_name,
            artifact_path=artifact,
            changelog=(
                f"{concept.get('one_liner', spec.app_name)}\n"
                f"Çekirdek özellik: {spec.core_feature}"
            ),
            qa_iterations_used=state.get("qa_iteration", 0),
            visual_iterations_used=state.get("visual_iteration", 0),
        )
        return {
            "phase": "awaiting_approval",
            "release_candidate": rc.model_dump(),
            "human_decision": "pending",
        }

    def await_human_node(state: PipelineState) -> dict:
        # Graf burada gerçekten durur; Approval Panel'den approve/reject gelene
        # kadar checkpoint'te bekler (LangGraph interrupt mekanizması).
        payload = {
            "release_candidate": state.get("release_candidate"),
            "circuit_breaker_tripped": state.get("circuit_breaker_tripped", False),
            "failure_reason": state.get("failure_reason", ""),
        }
        decision = interrupt(payload)
        update = {
            "human_decision": decision.get("decision", "rejected"),
            "human_feedback": decision.get("feedback", ""),
        }
        if update["human_decision"] == "rejected" and update["human_feedback"]:
            # insan geri bildirimiyle yeni coding turu: sayaç ve breaker sıfırlanır
            update.update(
                phase="coding",
                circuit_breaker_tripped=False,
                qa_iteration=0,
                qa_error_fingerprints=[],
                visual_iteration=0,
                build_result={},
                build_ok=False,
                visual_ok=True,
                escalation_level="standard",
            )
        elif update["human_decision"] == "approved":
            update["phase"] = "deploying"
        else:
            update["phase"] = "failed"
        return update

    def deploy_node(state: PipelineState) -> dict:
        rc = ReleaseCandidate.model_validate(state["release_candidate"])
        message = deps.deployment.deploy(rc)
        return {"phase": "done", "failure_reason": "", "human_feedback": message}

    graph = StateGraph(PipelineState)
    graph.add_node("idea", idea_node)
    graph.add_node("spec", spec_node)
    graph.add_node("design", design_node)
    graph.add_node("code", code_node)
    graph.add_node("build_and_test", build_and_test_node)
    graph.add_node("visual_review", visual_review_node)
    graph.add_node("build_release", build_release_node)
    graph.add_node("await_human", await_human_node)
    graph.add_node("deploy", deploy_node)

    graph.set_entry_point("idea")
    graph.add_edge("idea", "spec")
    graph.add_edge("spec", "design")
    graph.add_edge("design", "code")
    graph.add_edge("code", "build_and_test")
    graph.add_conditional_edges(
        "build_and_test",
        route_after_build,
        {"visual_review": "visual_review", "code": "code", "await_human": "await_human"},
    )
    graph.add_conditional_edges(
        "visual_review",
        route_after_visual,
        {"build_release": "build_release", "code": "code", "await_human": "await_human"},
    )
    graph.add_edge("build_release", "await_human")
    graph.add_conditional_edges(
        "await_human",
        route_after_human,
        {"deploy": "deploy", "code": "code", "end": END},
    )
    graph.add_edge("deploy", END)

    return graph.compile(checkpointer=checkpointer)
