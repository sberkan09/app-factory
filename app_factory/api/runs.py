"""Orkestrasyon API'si (ARCHITECTURE.md §4.2, §5.1).

- POST /runs                  -> yeni pipeline başlat
- GET  /runs                  -> tüm run'ları listele
- GET  /runs/{id}             -> durum sorgula (maliyet özeti dahil)
- GET  /runs/{id}/files       -> üretilen dosya listesi
- GET  /runs/{id}/files/{p}   -> dosya içeriği
- POST /runs/{id}/approve     -> human gate: onayla, dağıtımı tetikle
- POST /runs/{id}/reject      -> human gate: yorumla reddet, coder'a geri dön
- POST /runs/{id}/retry       -> hata alan / yarım kalan run'ı son checkpoint'ten sürdür
- GET  /panel                 -> onay paneli (HTML dashboard)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from langgraph.types import Command
from pydantic import BaseModel, Field

from app_factory.llm.usage import summarize_usage
from app_factory.services.workspace import is_ignored

log = logging.getLogger(__name__)
router = APIRouter()


class CreateRunRequest(BaseModel):
    idea: str = Field(min_length=3, max_length=2000)
    platform: Literal["flutter", "react-native"] = "flutter"


class DecisionRequest(BaseModel):
    feedback: str = ""


def _graph(request: Request):
    return request.app.state.graph


def _config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def _is_running(request: Request, run_id: str) -> bool:
    task = request.app.state.tasks.get(run_id)
    return task is not None and not task.done()


def _start(request: Request, run_id: str, payload) -> None:
    """Grafı arka planda çalıştırır; hata olursa run kaydına yazar.

    LangGraph her adımı checkpoint'lediği için hata alan node, /retry ile
    `invoke(None)` çağrılarak kaldığı yerden yeniden çalıştırılabilir.
    """
    graph = _graph(request)
    registry = request.app.state.registry
    registry.update(run_id, error="")

    async def runner():
        try:
            # LangGraph invoke senkron; event loop'u bloklamamak için thread'e alınır.
            await asyncio.to_thread(graph.invoke, payload, _config(run_id))
        except Exception as exc:  # node hatası: run'ı "takılı" bırakma, kaydet
            log.exception("Run %s failed", run_id)
            registry.update(run_id, error=f"{type(exc).__name__}: {exc}"[:2000])

    request.app.state.tasks[run_id] = asyncio.create_task(runner())


async def _snapshot(request: Request, run_id: str):
    snapshot = await asyncio.to_thread(_graph(request).get_state, _config(run_id))
    if snapshot is None or not snapshot.values:
        return None
    return snapshot


def _awaiting_human(snapshot) -> bool:
    return bool(getattr(snapshot, "interrupts", None)) or "await_human" in (snapshot.next or ())


def _status(request: Request, run_id: str, snapshot) -> dict:
    """Run'ın canlı durumu: çalışıyor mu, onay mı bekliyor, hata mı aldı."""
    running = _is_running(request, run_id)
    awaiting = not running and _awaiting_human(snapshot)
    entry = request.app.state.registry.get(run_id) or {}
    error = "" if running else entry.get("error", "")
    # Bekleyen node var ama çalışmıyor ve insan beklemiyor -> hata/yeniden başlatma
    stalled = not running and not awaiting and bool(snapshot.next)
    return {
        "running": running,
        "awaiting_approval": awaiting,
        "error": error,
        "can_retry": stalled,
    }


@router.get("/runs")
async def list_runs(request: Request):
    registry = request.app.state.registry
    out = []
    for entry in registry.list():
        snapshot = await _snapshot(request, entry["run_id"])
        values = snapshot.values if snapshot else {}
        status = _status(request, entry["run_id"], snapshot) if snapshot else {}
        out.append({
            **entry,
            **status,
            "phase": values.get("phase", "?"),
            "app_name": (values.get("app_concept") or {}).get("app_name", ""),
        })
    return out


@router.post("/runs")
async def create_run(body: CreateRunRequest, request: Request):
    run_id = uuid.uuid4().hex[:12]
    request.app.state.registry.add(run_id, body.idea, body.platform)
    initial = {
        "run_id": run_id,
        "idea_prompt": body.idea,
        "platform": body.platform,
        "phase": "idea",
        "qa_iteration": 0,
        "visual_iteration": 0,
        "code_diff_history": [],
        "fix_attempts": [],
        "qa_error_fingerprints": [],
        "escalation_level": "standard",
        "llm_calls": [],
    }
    _start(request, run_id, initial)
    return {"run_id": run_id, "status": "started"}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request):
    snapshot = await _snapshot(request, run_id)
    if snapshot is None:
        raise HTTPException(404, "run not found")
    values = snapshot.values
    spec = values.get("app_spec") or {}
    design = values.get("design_spec") or {}
    build = values.get("build_result") or {}
    error_report = build.get("error_report") or {}
    return {
        "run_id": run_id,
        **_status(request, run_id, snapshot),
        "phase": values.get("phase"),
        "next_nodes": list(snapshot.next or ()),
        "platform": values.get("platform", "flutter"),
        "app_id": values.get("app_id", ""),
        "qa_iteration": values.get("qa_iteration", 0),
        "visual_iteration": values.get("visual_iteration", 0),
        "escalation_level": values.get("escalation_level", "standard"),
        "circuit_breaker_tripped": values.get("circuit_breaker_tripped", False),
        "failure_reason": values.get("failure_reason", ""),
        "release_candidate": values.get("release_candidate") or None,
        "app_concept": values.get("app_concept"),
        "screens": [s.get("name") for s in spec.get("screens", [])],
        "design_tokens": design.get("tokens"),
        "build_status": build.get("status", ""),
        "last_error": error_report.get("raw_output", "")[:1500],
        "last_error_analysis": error_report.get("analysis"),
        "visual_report": values.get("visual_report") or None,
        "human_decision": values.get("human_decision"),
        "deploy_message": values.get("deploy_message", ""),
        "usage": summarize_usage(values.get("llm_calls", [])),
    }


@router.get("/runs/{run_id}/files")
async def list_files(run_id: str, request: Request):
    workspace: Path = request.app.state.workspace_root / run_id
    if not workspace.is_dir():
        raise HTTPException(404, "workspace not found")
    files = []
    for p in sorted(workspace.rglob("*")):
        rel = p.relative_to(workspace)
        if p.is_file() and not is_ignored(rel):
            files.append({"path": str(rel), "size": p.stat().st_size})
    return files


@router.get("/runs/{run_id}/files/{file_path:path}", response_class=PlainTextResponse)
async def read_file(run_id: str, file_path: str, request: Request):
    workspace: Path = (request.app.state.workspace_root / run_id).resolve()
    target = (workspace / file_path).resolve()
    if not target.is_relative_to(workspace) or not target.is_file():
        raise HTTPException(404, "file not found")
    try:
        return target.read_text()
    except UnicodeDecodeError:
        raise HTTPException(415, "binary file")


async def _resume(request: Request, run_id: str, decision: str, feedback: str):
    snapshot = await _snapshot(request, run_id)
    if snapshot is None:
        raise HTTPException(404, "run not found")
    if _is_running(request, run_id) or not _awaiting_human(snapshot):
        raise HTTPException(409, "run is not waiting for a human decision")
    if decision == "approved" and not snapshot.values.get("release_candidate"):
        raise HTTPException(
            409, "no release candidate to approve — reject with feedback to start a new attempt"
        )
    _start(request, run_id, Command(resume={"decision": decision, "feedback": feedback}))
    return {"run_id": run_id, "decision": decision, "status": "resumed"}


@router.post("/runs/{run_id}/approve")
async def approve(run_id: str, request: Request):
    return await _resume(request, run_id, "approved", "")


@router.post("/runs/{run_id}/reject")
async def reject(run_id: str, body: DecisionRequest, request: Request):
    return await _resume(request, run_id, "rejected", body.feedback.strip())


@router.post("/runs/{run_id}/retry")
async def retry(run_id: str, request: Request):
    snapshot = await _snapshot(request, run_id)
    if snapshot is None:
        raise HTTPException(404, "run not found")
    if not _status(request, run_id, snapshot)["can_retry"]:
        raise HTTPException(409, "run is running, waiting for approval, or already finished")
    _start(request, run_id, None)  # None: son checkpoint'ten devam
    return {"run_id": run_id, "status": "retrying", "next_nodes": list(snapshot.next)}


@router.get("/panel")
async def panel():
    return FileResponse(Path(__file__).parent / "ui.html", media_type="text/html")
