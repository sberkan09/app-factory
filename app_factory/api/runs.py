"""Orkestrasyon API'si (ARCHITECTURE.md §4.2, §5.1).

- POST /runs                  -> yeni pipeline başlat
- GET  /runs                  -> tüm run'ları listele
- GET  /runs/{id}             -> durum sorgula
- GET  /runs/{id}/files       -> üretilen dosya listesi
- GET  /runs/{id}/files/{p}   -> dosya içeriği
- POST /runs/{id}/approve     -> human gate: onayla, dağıtımı tetikle
- POST /runs/{id}/reject      -> human gate: yorumla reddet, coder'a geri dön
- GET  /panel                 -> onay paneli (HTML dashboard)
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from langgraph.types import Command
from pydantic import BaseModel

router = APIRouter()


class CreateRunRequest(BaseModel):
    idea: str
    platform: str = "flutter"


class DecisionRequest(BaseModel):
    feedback: str = ""


def _graph(request: Request):
    return request.app.state.graph


def _config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


async def _invoke(graph, payload, config):
    # LangGraph invoke senkron; event loop'u bloklamamak için thread'e alınır.
    return await asyncio.to_thread(graph.invoke, payload, config)


async def _snapshot_values(request: Request, run_id: str) -> dict | None:
    graph = _graph(request)
    snapshot = await asyncio.to_thread(graph.get_state, _config(run_id))
    if snapshot is None or not snapshot.values:
        return None
    return snapshot.values


@router.get("/runs")
async def list_runs(request: Request):
    registry = request.app.state.registry
    out = []
    for entry in registry.list():
        values = await _snapshot_values(request, entry["run_id"]) or {}
        out.append({
            **entry,
            "phase": values.get("phase", "?"),
            "awaiting_approval": values.get("phase") == "awaiting_approval"
            or (values.get("circuit_breaker_tripped") and values.get("human_decision") == "pending"),
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
        "qa_error_fingerprints": [],
        "escalation_level": "standard",
    }
    graph = _graph(request)
    task = asyncio.create_task(_invoke(graph, initial, _config(run_id)))
    request.app.state.tasks[run_id] = task
    return {"run_id": run_id, "status": "started"}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request):
    graph = _graph(request)
    snapshot = await asyncio.to_thread(graph.get_state, _config(run_id))
    if snapshot is None or not snapshot.values:
        raise HTTPException(404, "run not found")
    values = snapshot.values
    spec = values.get("app_spec") or {}
    design = values.get("design_spec") or {}
    build = values.get("build_result") or {}
    error_report = build.get("error_report") or {}
    return {
        "run_id": run_id,
        "phase": values.get("phase"),
        "platform": values.get("platform", "flutter"),
        "qa_iteration": values.get("qa_iteration", 0),
        "visual_iteration": values.get("visual_iteration", 0),
        "escalation_level": values.get("escalation_level", "standard"),
        "circuit_breaker_tripped": values.get("circuit_breaker_tripped", False),
        "failure_reason": values.get("failure_reason", ""),
        "awaiting_approval": bool(snapshot.next and "await_human" in str(snapshot.next))
        or values.get("phase") == "awaiting_approval",
        "release_candidate": values.get("release_candidate"),
        "app_concept": values.get("app_concept"),
        "screens": [s.get("name") for s in spec.get("screens", [])],
        "design_tokens": design.get("tokens"),
        "build_status": build.get("status", ""),
        "last_error": error_report.get("raw_output", "")[:1500],
        "visual_report": values.get("visual_report"),
        "human_decision": values.get("human_decision"),
        "last_message": values.get("human_feedback", ""),
    }


@router.get("/runs/{run_id}/files")
async def list_files(run_id: str, request: Request):
    workspace: Path = request.app.state.workspace_root / run_id
    if not workspace.is_dir():
        raise HTTPException(404, "workspace not found")
    files = []
    for p in sorted(workspace.rglob("*")):
        rel = p.relative_to(workspace)
        if p.is_file() and not any(part.startswith(".") for part in rel.parts):
            files.append({"path": str(rel), "size": p.stat().st_size})
    return files


@router.get("/runs/{run_id}/files/{file_path:path}", response_class=PlainTextResponse)
async def read_file(run_id: str, file_path: str, request: Request):
    workspace: Path = (request.app.state.workspace_root / run_id).resolve()
    target = (workspace / file_path).resolve()
    if not str(target).startswith(str(workspace)) or not target.is_file():
        raise HTTPException(404, "file not found")
    try:
        return target.read_text()
    except UnicodeDecodeError:
        raise HTTPException(415, "binary file")


async def _resume(request: Request, run_id: str, decision: str, feedback: str):
    graph = _graph(request)
    snapshot = await asyncio.to_thread(graph.get_state, _config(run_id))
    if snapshot is None or not snapshot.values:
        raise HTTPException(404, "run not found")
    command = Command(resume={"decision": decision, "feedback": feedback})
    task = asyncio.create_task(_invoke(graph, command, _config(run_id)))
    request.app.state.tasks[run_id] = task
    return {"run_id": run_id, "decision": decision, "status": "resumed"}


@router.post("/runs/{run_id}/approve")
async def approve(run_id: str, request: Request):
    return await _resume(request, run_id, "approved", "")


@router.post("/runs/{run_id}/reject")
async def reject(run_id: str, body: DecisionRequest, request: Request):
    return await _resume(request, run_id, "rejected", body.feedback)


@router.get("/panel")
async def panel():
    return FileResponse(Path(__file__).parent / "ui.html", media_type="text/html")
