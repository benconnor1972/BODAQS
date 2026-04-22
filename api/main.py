from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="BODAQS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok"}
