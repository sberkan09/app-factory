"""Uygulama girişi: bağımlılıkları kurar, grafiği derler, FastAPI'yi başlatır.

Çalıştırma:  uvicorn app_factory.main:app --reload
Panel:       http://localhost:8000/panel
"""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()  # ANTHROPIC_API_KEY gibi AF_* dışı değişkenler için

from app_factory.agents import (
    CoderAgent,
    DesignAgent,
    IdeaAgent,
    QACompilerAgent,
    SpecAgent,
    VisualReviewerAgent,
)
from app_factory.api.runs import router
from app_factory.config import Settings, settings
from app_factory.graph import PipelineDeps, build_graph
from app_factory.llm import AnthropicLLM
from app_factory.services import (
    WorkspaceService,
    make_ci_provider,
    make_deployment_provider,
    make_device_farm,
)


def build_deps(cfg: Settings) -> PipelineDeps:
    llm = AnthropicLLM()
    ci = make_ci_provider(cfg)
    return PipelineDeps(
        settings=cfg,
        workspace=WorkspaceService(cfg.workspace_root),
        idea_agent=IdeaAgent(llm, cfg.planner_model_id),
        spec_agent=SpecAgent(llm, cfg.planner_model_id),
        design_agent=DesignAgent(llm, cfg.planner_model_id),
        coder_agent=CoderAgent(llm, cfg.coder_model_id, cfg.qa_escalation_model_id),
        qa_agent=QACompilerAgent(ci, llm, cfg.planner_model_id, cfg.qa_escalation_model_id),
        visual_agent=VisualReviewerAgent(llm, cfg.vision_model_id),
        device_farm=make_device_farm(cfg),
        deployment=make_deployment_provider(cfg),
    )


def make_checkpointer(cfg: Settings):
    from langgraph.checkpoint.sqlite import SqliteSaver

    conn = sqlite3.connect(cfg.checkpoint_db, check_same_thread=False)
    return SqliteSaver(conn)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app_factory.api.registry import RunRegistry

    deps = build_deps(settings)
    app.state.graph = build_graph(deps, checkpointer=make_checkpointer(settings))
    app.state.tasks = {}
    app.state.registry = RunRegistry(settings.workspace_root / "runs.json")
    app.state.workspace_root = settings.workspace_root
    yield


app = FastAPI(title="App Factory", version="0.2.0", lifespan=lifespan)
app.include_router(router)
