import os
import shutil
import subprocess
import tempfile
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

    def _convert_to_wav(self, audio_bytes: bytes) -> str:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg not found in PATH — install it (brew install ffmpeg / apt-get install ffmpeg)")

        in_fd, in_path = tempfile.mkstemp(suffix=".input")
        out_fd, out_path = tempfile.mkstemp(suffix=".wav")
        os.close(in_fd)
        os.close(out_fd)

        with open(in_path, "wb") as f:
            f.write(audio_bytes)

        result = subprocess.run(
            [ffmpeg, "-y", "-i", in_path, "-ar", "16000", "-ac", "1", "-f", "wav", out_path],
            capture_output=True,
        )
        os.remove(in_path)

        if result.returncode != 0:
            try:
                os.remove(out_path)
            except OSError:
                pass
            stderr = result.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"ffmpeg conversion failed: {stderr[-500:]}")

        return out_path

    def transcribe(self, audio_bytes: bytes, language: str = "ru") -> tuple[str, str]:
        print(f"[STT] audio_bytes size: {len(audio_bytes)} bytes")

        try:
            wav_path = self._convert_to_wav(audio_bytes)
        except Exception as e:
            print(f"[STT] ffmpeg conversion error: {e}")
            raise

        wav_size = os.path.getsize(wav_path)
        # 16 kHz mono PCM s16le ⇒ 32000 bytes/sec; WAV header adds 44 bytes
        duration_sec = max(0.0, (wav_size - 44) / 32000.0)
        print(f"[STT] converted wav: {wav_size} bytes, ~{duration_sec:.2f}s")

        try:
            segments, info = self.model.transcribe(
                wav_path,
                language=language,
                beam_size=5,
                vad_filter=False,
            )
            segments = list(segments)
            print(f"[STT] segments count: {len(segments)}, detected language: {info.language}")

            text = "".join(seg.text for seg in segments).strip()
            print(f"[STT] final text: {text!r}")
            return text, info.language
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass
