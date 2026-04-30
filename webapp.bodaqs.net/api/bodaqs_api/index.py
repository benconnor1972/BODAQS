"""Vercel ASGI entry point.

Vercel Python functions look for a callable named `app` in `api/index.py`.
Mangum wraps the FastAPI ASGI app for the AWS Lambda-compatible runtime that
Vercel uses under the hood.
"""

from __future__ import annotations

from mangum import Mangum

from .main import app

handler = Mangum(app, lifespan="off")
