import io
import os
import threading
from faster_whisper import WhisperModel


class WhisperTranscriber:
    _instance: "WhisperTranscriber | None" = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        model_size: str = "small",
        device: str | None = None,
        compute_type: str | None = None,
    ):
        if getattr(self, "_initialized", False):
            return

        device = device or os.getenv("WHISPER_DEVICE", "cpu")
        compute_type = compute_type or os.getenv(
            "WHISPER_COMPUTE_TYPE",
            "int8" if device == "cpu" else "float16",
        )

        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
        )
        self._initialized = True

    def transcribe(self, audio_bytes: bytes) -> tuple[str, str]:
        segments, info = self.model.transcribe(
            io.BytesIO(audio_bytes),
            beam_size=5,
        )
        text = "".join(seg.text for seg in segments).strip()
        return text, info.language
