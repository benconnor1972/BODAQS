"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes.preprocess import router as preprocess_router

app = FastAPI(
    title="BODAQS API",
    description="Suspension telemetry preprocessing API for webapp.bodaqs.net.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tightened per-environment via Vercel env vars in production.
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(preprocess_router)
