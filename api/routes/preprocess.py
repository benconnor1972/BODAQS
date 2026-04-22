from __future__ import annotations

import gzip

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from api.schemas.preprocess import PreprocessConfig
from api.services.preprocess_service import run_preprocess

router = APIRouter()


@router.post("/preprocess")
async def preprocess(
    csv_file: UploadFile = File(...),
    config_json: str = Form(...),
):
    try:
        config = PreprocessConfig.model_validate_json(config_json)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid config: {exc}")

    raw = await csv_file.read()
    try:
        csv_bytes = gzip.decompress(raw)
    except Exception:
        csv_bytes = raw  # accept uncompressed fallback

    filename = csv_file.filename or "upload.csv"

    try:
        return run_preprocess(csv_bytes, config, filename=filename)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"error": "preprocess_failed", "detail": str(exc)},
        )
