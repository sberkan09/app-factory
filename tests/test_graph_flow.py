"""Uçtan uca graf akış testleri: self-healing döngüsü, breaker, human gate."""

from langgraph.types import Command

from app_factory.schemas.contracts import VisualIssue, VisualQAReport
from app_factory.services.ci import StubCI
from app_factory.services.device_farm import Screenshot
from tests.conftest import FakeLLM, initial_state, make_pipeline, run_config


def test_happy_path_reaches_approval_then_deploys(test_settings):
    graph, llm = make_pipeline(test_settings, StubCI(fail_times=0))
    result = graph.invoke(initial_state(), run_config())

    # İnsan onayında duraklamış olmalı
    assert result["phase"] == "awaiting_approval"
    assert result["release_candidate"]["app_name"] == "SuTakip"
    snapshot = graph.get_state(run_config())
    assert snapshot.next  # interrupt'ta bekliyor

    # Onayla -> deploy -> done
    final = graph.invoke(Command(resume={"decision": "approved"}), run_config())
    assert final["phase"] == "done"
    assert "internal track" in final["deploy_message"]
    assert "com.appfactory.sutakip" in final["deploy_message"]


def test_self_healing_retries_until_build_passes(test_settings):
    # Farklı hatalarla 2 kez başarısız, 3.'de geçer
    ci = StubCI(fail_times=2, failure_outputs=["Error: A is broken", "Error: B is broken"])
    graph, llm = make_pipeline(test_settings, ci)
    result = graph.invoke(initial_state(), run_config())

    assert result["phase"] == "awaiting_approval"
    assert result["qa_iteration"] == 3
    assert not result.get("circuit_breaker_tripped")
    # Coder 3 kez çağrılmış olmalı (1 ilk üretim + 2 düzeltme)
    assert llm.code_version == 3


def test_circuit_breaker_trips_on_repeated_identical_error(test_settings):
    # Aynı hata sürekli tekrar ediyor -> fingerprint tespiti 2. görüşte kesmeli
    ci = StubCI(fail_times=99, failure_output="Error: same thing every time")
    graph, llm = make_pipeline(test_settings, ci)
    result = graph.invoke(initial_state(), run_config())

    assert result["circuit_breaker_tripped"]
    assert result["phase"] == "failed"
    assert result["qa_iteration"] == 2  # 5 hakkı beklemeden erken kesti
    # Breaker sonrası insana devredilmiş (interrupt'ta bekliyor)
    assert graph.get_state(run_config()).next


def test_escalation_switches_model_after_threshold(test_settings):
    ci = StubCI(fail_times=3, failure_outputs=["Error: A", "Error: B", "Error: C"])
    graph, llm = make_pipeline(test_settings, ci)
    result = graph.invoke(initial_state(), run_config())

    assert result["phase"] == "awaiting_approval"
    # 3. iterasyondan sonra coder escalation modeliyle çağrılmış olmalı
    coder_models = [c["model"] for c in llm.calls if c["output"] == "CodeBundle"]
    assert "test-escalation" in coder_models


def test_reject_with_feedback_restarts_coding(test_settings):
    graph, llm = make_pipeline(test_settings, StubCI(fail_times=0))
    graph.invoke(initial_state(), run_config())

    result = graph.invoke(
        Command(resume={"decision": "rejected", "feedback": "Butonu yeşil yap"}),
        run_config(),
    )
    # Yeni coding turu -> tekrar onaya gelmiş olmalı
    assert result["phase"] == "awaiting_approval"
    assert llm.code_version == 2  # feedback ile ikinci üretim


def test_visual_blocker_sends_back_to_coder(test_settings):
    llm = FakeLLM()
    llm.visual_reports = [
        VisualQAReport(
            verdict="fail",
            issues=[VisualIssue(type="overflow", screen="HomeScreen",
                                description="Buton taşıyor", severity="blocker")],
        ),
        VisualQAReport(verdict="pass"),
    ]

    # StubDeviceFarm screenshot döndürmez (visual QA skipped olurdu); blocker
    # akışını test etmek için screenshot döndüren bir farm kullan.
    graph, _ = make_pipeline(test_settings, StubCI(fail_times=0), llm, device_farm=OneShotFarm())
    result = graph.invoke(initial_state("vqa-run"), run_config("vqa-run"))

    assert result["phase"] == "awaiting_approval"
    assert result["visual_iteration"] == 2  # 1. tur blocker -> coder -> 2. tur pass
    assert llm.code_version == 2
    fix_prompt = [c for c in llm.calls if c["output"] == "CodeBundle"][1]["prompt"]
    assert "Buton taşıyor" in fix_prompt


class OneShotFarm:
    def capture(self, workspace, spec, artifact_path, app_id=""):
        return [Screenshot(screen_name="HomeScreen", png_bytes=b"fakepng")]
