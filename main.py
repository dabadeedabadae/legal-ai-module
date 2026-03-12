from fastapi import FastAPI
from app.api.routes import router
from dotenv import load_dotenv
load_dotenv()

app = FastAPI(title="Legal AI Module", version="0.1.0")
app.include_router(router, prefix="/api/v1")

@app.get("/health")
async def health():
    return {"status": "ok", "model": "qwen2.5:7b"}
