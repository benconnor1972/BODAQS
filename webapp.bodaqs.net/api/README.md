# BODAQS API

FastAPI backend for webapp.bodaqs.net. Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

## Setup

```sh
uv sync --group dev
```

`bodaqs-analysis` is installed as an editable local package from `../../analysis` via `[tool.uv.sources]`.

## Dev server

```sh
uv run uvicorn bodaqs_api.main:app --reload
```

Runs on `http://localhost:8000`. Swagger UI at `/docs`.

> For integrated local dev (frontend + API together), run `vercel dev -L` from the project root instead.

## Tests

```sh
uv run pytest
```
