"""POST /api/preprocess route."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from ..schemas.preprocess import PreprocessResponse
from ..services.preprocess_service import run_preprocess

router = APIRouter()

_MAX_CSV_BYTES = 50 * 1024 * 1024  # 50 MB


@router.post("/preprocess", response_model=PreprocessResponse)
async def preprocess_endpoint(
    csv_file: UploadFile = File(..., description="Logger CSV file."),
    bike_profile_json: UploadFile = File(..., description="Bike profile JSON."),
    sidecar_json: UploadFile = File(..., description="Log metadata sidecar JSON."),
    event_schema_yaml: UploadFile = File(..., description="Event schema YAML."),
    preprocess_profile_json: UploadFile | None = File(
        default=None,
        description="Preprocess profile JSON. If omitted, the bundled default is used.",
    ),
) -> PreprocessResponse:
    # Read all files upfront so temp-file logic stays in the service layer.
    csv_bytes = await csv_file.read()
    if len(csv_bytes) > _MAX_CSV_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"CSV file exceeds the 50 MB limit ({len(csv_bytes) / 1024 / 1024:.1f} MB uploaded).",
        )

    sidecar_bytes = await sidecar_json.read()
    bike_profile_bytes = await bike_profile_json.read()
    schema_bytes = await event_schema_yaml.read()
    preprocess_profile_bytes = (
        await preprocess_profile_json.read() if preprocess_profile_json is not None else None
    )

    try:
        response = run_preprocess(
            csv_bytes=csv_bytes,
            csv_filename=csv_file.filename or "upload.csv",
            sidecar_bytes=sidecar_bytes,
            bike_profile_bytes=bike_profile_bytes,
            event_schema_bytes=schema_bytes,
            preprocess_profile_bytes=preprocess_profile_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}") from exc

    return response
