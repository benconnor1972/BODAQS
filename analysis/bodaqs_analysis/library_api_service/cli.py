"""Command-line entry point for the local BODAQS Library API service."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import uvicorn

from .app import create_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local BODAQS Library API service.")
    parser.add_argument(
        "--libraries-root",
        required=True,
        help="Directory containing one or more processed BODAQS libraries.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address. Keep 127.0.0.1 for local-only development.",
    )
    parser.add_argument("--port", type=int, default=8765, help="Port to bind.")
    parser.add_argument(
        "--web-root",
        default=None,
        help="Optional directory containing a built BODAQS web app to serve at /.",
    )
    parser.add_argument(
        "--allow-origin",
        action="append",
        default=None,
        help="Allowed browser origin for CORS. May be supplied multiple times.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app = create_app(
        Path(args.libraries_root),
        allow_origins=tuple(args.allow_origin) if args.allow_origin else None,
        web_root=Path(args.web_root) if args.web_root else None,
    )
    uvicorn.run(app, host=str(args.host), port=int(args.port))
    return 0
