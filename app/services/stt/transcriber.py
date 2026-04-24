import os
import shutil
import subprocess
import tempfile
import threading

import torch
import torchaudio
from transformers import pipeline


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
        model_name: str = "openai/whisper-large-v3",
        device: str = "cpu",
        torch_dtype: torch.dtype = torch.float32,
    ):
        if getattr(self, "_initialized", False):
            return

        self.device = device
        self.torch_dtype = torch_dtype
        self.pipe = pipeline(
            task="automatic-speech-recognition",
            model=model_name,
            torch_dtype=torch_dtype,
            device=device,
            chunk_length_s=30,
            return_timestamps=True,
        )
        self._initialized = True

    def _convert_to_wav(self, audio_bytes: bytes) -> str:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg not found in PATH — install it (apt-get install ffmpeg)")

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

    def _detect_language(self, wav_path: str) -> str:
        waveform, sr = torchaudio.load(wav_path)
        if waveform.ndim == 2:
            waveform = waveform.mean(dim=0)
        sample = waveform[: 30 * 16000]

        features = self.pipe.feature_extractor(
            sample.numpy(),
            sampling_rate=16000,
            return_tensors="pt",
        ).input_features.to(self.device, dtype=self.torch_dtype)

        model = self.pipe.model
        decoder_start_token_id = model.generation_config.decoder_start_token_id
        decoder_input_ids = torch.tensor([[decoder_start_token_id]], device=self.device)

        with torch.no_grad():
            logits = model(features, decoder_input_ids=decoder_input_ids).logits[:, -1, :]

        token_id = int(logits.argmax(dim=-1).item())
        token_text = self.pipe.tokenizer.decode([token_id])
        return token_text.strip().replace("<|", "").replace("|>", "") or "ru"

    def transcribe(
        self,
        audio_bytes: bytes,
        language: str | None = None,
    ) -> tuple[str, str]:
        print(f"[STT] audio_bytes size: {len(audio_bytes)} bytes")

        wav_path = self._convert_to_wav(audio_bytes)
        try:
            wav_size = os.path.getsize(wav_path)
            # 16 kHz mono PCM s16le ⇒ 32000 bytes/sec; WAV header adds 44 bytes
            duration_sec = max(0.0, (wav_size - 44) / 32000.0)
            print(f"[STT] converted wav: {wav_size} bytes, ~{duration_sec:.2f}s")

            if language is None:
                language = self._detect_language(wav_path)

            result = self.pipe(
                wav_path,
                generate_kwargs={"language": language, "task": "transcribe"},
            )

            chunks = result.get("chunks") or []
            text = (result.get("text") or "").strip()
            print(f"[STT] segments count: {len(chunks)}, detected language: {language}")
            print(f"[STT] final text: {text!r}")
            return text, language
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass
