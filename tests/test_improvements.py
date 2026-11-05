"""v0.2 iyileştirmelerinin testleri: maliyet takibi, QA analizi, başarısız
deneme bağlamı, breaker sonrası onay koruması, platform/app_id tutarlılığı."""

from langgraph.types import Command

from app_factory.llm.usage import estimate_cost, summarize_usage
from app_factory.services.ci import StubCI
from tests.conftest import FakeLLM, initial_state, make_pipeline, run_config


def test_llm_usage_is_tracked_per_node(test_settings):
    graph, llm = make_pipeline(test_settings, StubCI(fail_times=1, failure_output="Error: x"))
    result = graph.invoke(initial_state(), run_config())

    calls = result["llm_calls"]
    assert len(calls) == len(llm.calls)
    agents = {c["agent"] for c in calls}
    assert {"idea", "spec", "design", "code", "build_and_test"} <= agents
    summary = summarize_usage(calls)
    assert summary["calls"] == len(calls)
    assert summary["input_tokens"] == 1000 * len(calls)
    assert not summary["cost_complete"]  # test modellerinin fiyatı bilinmiyor


def test_cost_estimate_for_known_model():
    assert estimate_cost("claude-sonnet-5-5", 1_000_000, 1_000_000) == 12.0
    assert estimate_cost("unknown-model", 10, 10) is None


def test_qa_analysis_runs_on_every_failure_with_model_cascade(test_settings):
    ci = StubCI(fail_times=4, failure_outputs=["Error: A", "Error: B", "Error: C", "Error: D"])
    graph, llm = make_pipeline(test_settings, ci)
    graph.invoke(initial_state(), run_config())

    analysis_models = [c["model"] for c in llm.calls if c["output"] == "ErrorAnalysis"]
    # Her hatada analiz: eskalasyon 3. hatadan sonra devreye girer
    assert analysis_models == ["test-model", "test-model", "test-model", "test-escalation"]


def test_only_failed_fix_attempts_are_fed_back(test_settings):
    ci = StubCI(fail_times=2, failure_outputs=["Error: A broke", "Error: B broke"])
    graph, llm = make_pipeline(test_settings, ci)
    result = graph.invoke(initial_state(), run_config())

    code_prompts = [c["prompt"] for c in llm.calls if c["output"] == "CodeBundle"]
    # İlk düzeltme çağrısında henüz başarısız deneme yok (ilk üretim deneme değildir)
    assert "BAŞARISIZ olan düzeltmeler" not in code_prompts[1]
    # İkinci düzeltmede bir önceki düzeltme denemesi bağlam olarak verilir
    assert "BAŞARISIZ olan düzeltmeler" in code_prompts[2]
    # Build geçince bağlam sıfırlanır
    assert result["fix_attempts"] == []


def test_approve_after_circuit_breaker_does_not_deploy(test_settings):
    ci = StubCI(fail_times=99, failure_output="Error: same")
    graph, _ = make_pipeline(test_settings, ci)
    result = graph.invoke(initial_state(), run_config())
    assert result["circuit_breaker_tripped"]

    final = graph.invoke(Command(resume={"decision": "approved"}), run_config())
    assert final["phase"] == "failed"
    assert not final.get("deploy_message")
    assert "sürüm adayı yok" in final["failure_reason"]


def test_reject_after_breaker_with_feedback_starts_fresh_round(test_settings):
    ci = StubCI(fail_times=2, failure_output="Error: same")  # 2. görüşte breaker
    graph, llm = make_pipeline(test_settings, ci)
    result = graph.invoke(initial_state(), run_config())
    assert result["circuit_breaker_tripped"]

    final = graph.invoke(
        Command(resume={"decision": "rejected", "feedback": "state yönetimini sadeleştir"}),
        run_config(),
    )
    assert final["phase"] == "awaiting_approval"
    assert not final["circuit_breaker_tripped"]
    assert final["escalation_level"] == "standard"
    assert "state yönetimini sadeleştir" in [c for c in llm.calls if c["output"] == "CodeBundle"][-1]["prompt"]


def test_platform_is_enforced_and_app_id_derived(test_settings):
    llm = FakeLLM()
    llm.spec_platform = "react-native"  # model yanlış platform döndürse bile
    graph, _ = make_pipeline(test_settings, StubCI(), llm)
    result = graph.invoke(initial_state(), run_config())

    assert result["app_spec"]["platform"] == "flutter"
    assert result["app_id"] == "com.appfactory.sutakip"
    assert result["release_candidate"]["app_id"] == "com.appfactory.sutakip"
    coder_prompt = next(c["prompt"] for c in llm.calls if c["output"] == "CodeBundle")
    assert "com.appfactory.sutakip" in coder_prompt
