"""Test fixture'ları: sahte LLM + stub sağlayıcılarla tam pipeline."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app_factory.agents import (
    CoderAgent,
    DesignAgent,
    IdeaAgent,
    QACompilerAgent,
    SpecAgent,
    VisualReviewerAgent,
)
from app_factory.config import Settings
from app_factory.llm.usage import record_usage
from app_factory.graph import PipelineDeps, build_graph
from app_factory.schemas.contracts import (
    AppConcept,
    AppSpec,
    CodeBundle,
    DesignSpec,
    DesignTokens,
    ErrorAnalysis,
    GeneratedFile,
    ScreenDesign,
    ScreenSpec,
    VisualQAReport,
)
from app_factory.services import StubCI, StubDeployment, StubDeviceFarm, WorkspaceService

CONCEPT = AppConcept(
    app_name="SuTakip",
    one_liner="Günlük su tüketimini tek dokunuşla kaydet",
    core_feature="Bir bardak su içince tek dokunuşla kaydetmek",
    target_audience="Sağlıklı yaşam takipçileri",
    differentiator="Sıfır kurulum, tek ekran",
)

SPEC = AppSpec(
    app_name="SuTakip",
    core_feature="Tek dokunuşla su kaydı",
    platform="flutter",
    screens=[ScreenSpec(name="HomeScreen", purpose="Su kaydı", components=["counter", "button"])],
)

DESIGN = DesignSpec(
    tokens=DesignTokens(
        primary_color="#1B6CA8", secondary_color="#7FB7D9", background_color="#F4F9FC",
        text_color="#12262F", font_family="Nunito", corner_radius=16, spacing_unit=8,
    ),
    screen_designs=[ScreenDesign(screen="HomeScreen", layout_description="Ortada büyük buton", key_components=["FAB"])],
)


class FakeLLM:
    """output_model tipine göre kayıtlı yanıtları döndürür; çağrıları loglar."""

    def __init__(self):
        self.calls: list[dict] = []
        self.code_version = 0
        self.visual_reports: list[VisualQAReport] = []
        self.fail_next: dict[type, Exception] = {}  # output_model -> bir kez fırlatılacak hata
        self.spec_platform = "flutter"

    def structured(self, *, model, output_model, system, prompt, images=None, max_tokens=16000):
        self.calls.append({"model": model, "output": output_model.__name__, "prompt": prompt})
        record_usage(model=model, input_tokens=1000, output_tokens=100)
        if output_model in self.fail_next:
            raise self.fail_next.pop(output_model)
        if output_model is AppConcept:
            return CONCEPT
        if output_model is AppSpec:
            return SPEC.model_copy(update={"platform": self.spec_platform})
        if output_model is DesignSpec:
            return DESIGN
        if output_model is CodeBundle:
            self.code_version += 1
            return CodeBundle(
                files=[GeneratedFile(path="lib/main.dart", content=f"// v{self.code_version}\nvoid main() {{}}\n")],
                entry_point="lib/main.dart",
            )
        if output_model is ErrorAnalysis:
            return ErrorAnalysis(root_cause="test", fix_strategy="fix it")
        if output_model is VisualQAReport:
            if self.visual_reports:
                return self.visual_reports.pop(0)
            return VisualQAReport(verdict="pass")
        raise AssertionError(f"Unexpected output model: {output_model}")


@pytest.fixture
def test_settings(tmp_path):
    return Settings(
        workspace_root=tmp_path / "workspaces",
        ci_provider="stub",
        device_farm_provider="stub",
        deployment_provider="stub",
    )


def make_deps(settings: Settings, ci: StubCI, llm: FakeLLM | None = None, device_farm=None):
    llm = llm or FakeLLM()
    deps = PipelineDeps(
        settings=settings,
        workspace=WorkspaceService(settings.workspace_root),
        idea_agent=IdeaAgent(llm, "test-model"),
        spec_agent=SpecAgent(llm, "test-model"),
        design_agent=DesignAgent(llm, "test-model"),
        coder_agent=CoderAgent(llm, "test-coder", "test-escalation"),
        qa_agent=QACompilerAgent(ci, llm, "test-model", "test-escalation"),
        visual_agent=VisualReviewerAgent(llm, "test-vision"),
        device_farm=device_farm or StubDeviceFarm(),
        deployment=StubDeployment(),
    )
    return deps, llm


def make_pipeline(settings: Settings, ci: StubCI, llm: FakeLLM | None = None, device_farm=None):
    deps, llm = make_deps(settings, ci, llm, device_farm)
    graph = build_graph(deps, checkpointer=MemorySaver())
    return graph, llm


def initial_state(run_id: str = "test-run") -> dict:
    return {
        "run_id": run_id,
        "idea_prompt": "su içme takip uygulaması",
        "platform": "flutter",
        "phase": "idea",
        "qa_iteration": 0,
        "visual_iteration": 0,
        "code_diff_history": [],
        "fix_attempts": [],
        "qa_error_fingerprints": [],
        "escalation_level": "standard",
    }


def run_config(run_id: str = "test-run") -> dict:
    return {"configurable": {"thread_id": run_id}}
