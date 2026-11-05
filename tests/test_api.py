"""API testleri: hata kaydı + retry, onay kapısı korumaları, maliyet özeti."""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from app_factory.api.registry import RunRegistry
from app_factory.api.runs import router
from app_factory.graph import build_graph
from app_factory.schemas.contracts import AppConcept
from app_factory.services.ci import StubCI
from tests.conftest import FakeLLM, make_deps


def make_client(test_settings, ci, llm):
    deps, llm = make_deps(test_settings, ci, llm)
    app = FastAPI()
    app.include_router(router)
    app.state.graph = build_graph(deps, checkpointer=MemorySaver())
    app.state.tasks = {}
    app.state.registry = RunRegistry(test_settings.workspace_root / "runs.json")
    app.state.workspace_root = test_settings.workspace_root
    return TestClient(app)


def wait_until(client, run_id, pred, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = client.get(f"/runs/{run_id}").json()
        if "phase" in d and pred(d):
            return d
        time.sleep(0.05)
    raise AssertionError(f"timeout; last state: {d}")


@pytest.fixture
def llm():
    return FakeLLM()


def test_node_failure_is_reported_and_retry_resumes(test_settings, llm):
    llm.fail_next[AppConcept] = RuntimeError("API overloaded")
    with make_client(test_settings, StubCI(), llm) as client:
        run_id = client.post("/runs", json={"idea": "su takip"}).json()["run_id"]
        d = wait_until(client, run_id, lambda d: d["error"] or d["can_retry"])
        assert "API overloaded" in d["error"]
        assert d["can_retry"] and d["next_nodes"] == ["idea"]
        # onay kapısı beklenmiyorken approve reddedilir
        assert client.post(f"/runs/{run_id}/approve").status_code == 409

        assert client.post(f"/runs/{run_id}/retry").status_code == 200
        d = wait_until(client, run_id, lambda d: d["awaiting_approval"])
        assert d["error"] == ""
        assert d["usage"]["calls"] > 0
        assert d["app_id"] == "com.appfactory.sutakip"

        # artık retry edilecek bir şey yok
        assert client.post(f"/runs/{run_id}/retry").status_code == 409

        assert client.post(f"/runs/{run_id}/approve").status_code == 200
        d = wait_until(client, run_id, lambda d: d["phase"] == "done")
        assert "internal track" in d["deploy_message"]
        assert client.post(f"/runs/{run_id}/approve").status_code == 409


def test_approve_without_release_candidate_is_rejected(test_settings, llm):
    with make_client(test_settings, StubCI(fail_times=99, failure_output="Error: same"), llm) as client:
        run_id = client.post("/runs", json={"idea": "su takip"}).json()["run_id"]
        d = wait_until(client, run_id, lambda d: d["awaiting_approval"])
        assert d["circuit_breaker_tripped"]
        r = client.post(f"/runs/{run_id}/approve")
        assert r.status_code == 409
        assert "release candidate" in r.json()["detail"]

        listing = client.get("/runs").json()
        assert listing[0]["run_id"] == run_id and listing[0]["awaiting_approval"]


def test_invalid_platform_rejected(test_settings, llm):
    with make_client(test_settings, StubCI(), llm) as client:
        assert client.post("/runs", json={"idea": "su takip", "platform": "swift"}).status_code == 422
