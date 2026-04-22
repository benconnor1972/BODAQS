from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes.preprocess import router as preprocess_router

app = FastAPI(title="BODAQS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(preprocess_router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
