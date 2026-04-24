import asyncio
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from app.api.routes import verify_api_key
from app.services.stt.transcriber import WhisperTranscriber

router = APIRouter(prefix="/stt", tags=["stt"])

ALLOWED_CONTENT_TYPES = {
    "audio/wav", "audio/x-wav", "audio/wave",
    "audio/ogg", "audio/opus",
    "audio/mp4", "audio/x-m4a", "audio/m4a",
    "audio/webm", "video/webm",
}
ALLOWED_EXTENSIONS = {"wav", "ogg", "m4a", "webm"}

_transcriber: WhisperTranscriber | None = None


def get_transcriber() -> WhisperTranscriber:
    global _transcriber
    if _transcriber is None:
        _transcriber = WhisperTranscriber(model_size="small")
    return _transcriber


@router.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    _=Depends(verify_api_key),
):
    filename = (audio.filename or "").lower()
    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
    content_type = (audio.content_type or "").lower()

    if ext not in ALLOWED_EXTENSIONS and content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported audio format. Allowed: wav, ogg, m4a, webm",
        )

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    transcriber = get_transcriber()
    try:
        text, language = await asyncio.to_thread(transcriber.transcribe, audio_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")

    return {"text": text, "language": language}
