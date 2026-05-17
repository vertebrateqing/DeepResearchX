"""DeepResearchX — FastAPI backend entrypoint.

Run with uv (recommended):
    uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000

Or activate the venv first:
    source .venv/bin/activate
    uvicorn main:app --reload --host 0.0.0.0 --port 8000

Interactive API docs: http://localhost:8000/docs
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.router import api_router


def _configure_logging() -> None:
    """Raise root logger to INFO so application logs are visible.

    Uvicorn configures its own loggers but leaves Python's root logger at
    WARNING, which silently drops INFO calls from ``deep_research.*``.
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root.addHandler(handler)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    _configure_logging()
    yield


app = FastAPI(
    title="DeepResearchX API",
    description="Multi-agent deep research system with streaming report generation.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "DeepResearchX API"}
