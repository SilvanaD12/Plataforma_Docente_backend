"""
Imágenes y audio con la API de Gemini (Interactions API): ilustraciones didácticas y voz sintética para los guiones.

La capa gratuita de Gemini no incluye generación de imágenes y su cuota de voz es pequeña: si el servicio falla,
la generación sigue y el recurso queda con su respaldo (tarjeta visual o voz del navegador).
"""

from __future__ import annotations

import base64
import binascii
import io
import wave
from typing import Any

import httpx

from platform5e.application.ports.outbound.media_port import GeneratedMedia
from platform5e.infrastructure.llm.gemini_language_model import AIProviderError

DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-lite-image"
DEFAULT_SPEECH_MODEL = "gemini-3.8-flash-tts"
DEFAULT_VOICE = "Kore"
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
PCM_SAMPLE_RATE = 24000  # la voz de Gemini entrega PCM de 16 bits, mono, 24 kHz
IMAGE_TYPES = {b"\x89PNG": ("image/png", "png"), b"\xff\xd8\xff": ("image/jpeg", "jpg")}


def _decode(value: str) -> bytes | None:
    try:
        return base64.b64decode(value, validate=False)
    except (binascii.Error, ValueError):
        return None


def find_inline_data(payload: Any, prefix: str) -> tuple[bytes, str] | None:
    """Busca en la respuesta el último bloque en base64 del tipo pedido (Interactions o generateContent)."""
    found: list[tuple[bytes, str]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            data = node.get("data")
            mime = str(node.get("mime_type") or node.get("mimeType") or node.get("type") or "")
            if isinstance(data, str) and len(data) > 64:
                decoded = _decode(data)
                if decoded:
                    found.append((decoded, mime))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    preferred = [item for item in found if item[1].startswith(prefix) or item[1] == prefix.rstrip("/")]
    return (preferred or found or [None])[-1]


def pcm_to_wav(pcm: bytes, sample_rate: int = PCM_SAMPLE_RATE) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm)
    return buffer.getvalue()


def wav_to_mp3(wav_bytes: bytes) -> bytes | None:
    """MP3 de 64 kb/s (unas 5 veces más liviano que el WAV). Sin la librería lameenc, se queda en WAV."""
    try:
        import lameenc
    except ImportError:
        return None
    with wave.open(io.BytesIO(wav_bytes), "rb") as source:
        if source.getsampwidth() != 2:
            return None
        channels, rate, frames = source.getnchannels(), source.getframerate(), source.readframes(source.getnframes())
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(64)
    encoder.set_in_sample_rate(rate)
    encoder.set_channels(channels)
    encoder.set_quality(2)
    return bytes(encoder.encode(frames) + encoder.flush())


def as_audio_file(audio: bytes, mime: str) -> GeneratedMedia:
    if audio[:3] == b"ID3" or audio[:2] in (b"\xff\xfb", b"\xff\xf3"):
        return GeneratedMedia(audio, "audio/mpeg", "mp3")
    if not (audio[:4] == b"RIFF" and audio[8:12] == b"WAVE"):
        rate = PCM_SAMPLE_RATE
        if "rate=" in mime:
            rate = int("".join(ch for ch in mime.split("rate=")[1] if ch.isdigit()) or PCM_SAMPLE_RATE)
        audio = pcm_to_wav(audio, rate)
    mp3 = wav_to_mp3(audio)
    return GeneratedMedia(mp3, "audio/mpeg", "mp3") if mp3 else GeneratedMedia(audio, "audio/wav", "wav")


def as_image_file(image: bytes, mime: str) -> GeneratedMedia:
    for magic, (mime_type, extension) in IMAGE_TYPES.items():
        if image.startswith(magic):
            return GeneratedMedia(image, mime_type, extension)
    if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return GeneratedMedia(image, "image/webp", "webp")
    raise AIProviderError(f"Gemini devolvió un archivo que no es una imagen ({mime or 'sin tipo'}).")


class GeminiMediaGenerator:
    """Adaptador del puerto MediaGeneratorPort con los modelos de imagen y de voz de Gemini."""

    def __init__(
        self,
        api_key: str,
        image_model: str | None = None,
        speech_model: str | None = None,
        voice: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self.image_model = image_model or DEFAULT_IMAGE_MODEL
        self.speech_model = speech_model or DEFAULT_SPEECH_MODEL
        self.voice = voice or DEFAULT_VOICE
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)
        self.description = f"Gemini · {self.image_model} y {self.speech_model}"

    def generate_image(self, prompt: str) -> GeneratedMedia:
        payload = {
            "model": self.image_model,
            "input": [{"type": "text", "text": prompt}],
            "response_format": {"type": "image", "mime_type": "image/jpeg", "aspect_ratio": "16:9", "image_size": "1K"},
        }
        found = find_inline_data(self._post(payload), "image/")
        if found is None:
            raise AIProviderError("Gemini no devolvió una imagen.")
        return as_image_file(*found)

    def synthesize_speech(self, script: str) -> GeneratedMedia:
        payload = {
            "model": self.speech_model,
            "input": [{"type": "user_input", "content": [{"type": "text", "text": script}]}],
            "response_format": {"type": "audio"},
            "generation_config": {"speech_config": [{"voice": self.voice}]},
        }
        found = find_inline_data(self._post(payload), "audio/")
        if found is None:
            raise AIProviderError("Gemini no devolvió audio.")
        return as_audio_file(*found)

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.post(
                f"{self._base_url}/interactions",
                headers={"Content-Type": "application/json", "x-goog-api-key": self._api_key},
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise AIProviderError(f"sin conexión con Gemini: {exc.__class__.__name__}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {})
                message = detail.get("message", "") if isinstance(detail, dict) else str(detail)
            except ValueError:
                message = response.text[:200]
            raise AIProviderError(f"Gemini respondió {response.status_code}: {message[:200]}", response.status_code)
        try:
            return response.json()
        except ValueError as exc:
            raise AIProviderError("Gemini devolvió una respuesta que no es JSON.") from exc


def wav_duration_seconds(wav_bytes: bytes) -> float:
    """Duración de un WAV (para pruebas y para mostrarla)."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as source:
        return source.getnframes() / float(source.getframerate())
