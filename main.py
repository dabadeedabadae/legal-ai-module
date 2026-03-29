from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.api.routes import router
from dotenv import load_dotenv
import os
load_dotenv()

app = FastAPI(title="Legal AI Module", version="0.1.0")
app.include_router(router, prefix="/api/v1")

static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", include_in_schema=False)
async def ui():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/health")
async def health():
    return {"status": "ok", "model": "qwen2.5:7b"}
