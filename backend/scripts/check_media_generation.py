"""Prueba real de la voz y las imágenes de Gemini con tu clave, sin levantar la plataforma.

Uso, desde backend/ (PowerShell):
    $env:LLM_API_KEY="TU_CLAVE"
    python scripts/check_media_generation.py

Guarda los archivos en media-check/ y explica cada error: 400 suele ser un pedido mal armado (avísale al equipo),
403 o «billing» significa que el proyecto no tiene facturación (la capa gratuita no genera imágenes) y 429 que se
acabó la cuota del día. Variables opcionales: IMAGE_MODEL, SPEECH_MODEL y SPEECH_VOICE.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from platform5e.infrastructure.llm.gemini_language_model import AIProviderError
from platform5e.infrastructure.llm.gemini_media_generator import GeminiMediaGenerator

SCRIPT = (
    "Hola. Esta es una prueba de la plataforma docente. El protocolo TCP confirma la entrega de los datos; "
    "el protocolo UDP no la confirma y por eso es más rápido en videollamadas y juegos en línea."
)
PROMPT = (
    "Ilustración didáctica, clara y sin texto escrito, de dos computadoras que se envían paquetes de datos por una red: "
    "una con confirmaciones de entrega y otra sin ellas. Estilo de libro escolar, colores suaves y fondo limpio."
)


def hint(error: AIProviderError) -> str:
    status = error.status_code
    if status == 400:
        return "El servicio rechazó el pedido (400). Copia este mensaje al equipo para ajustar el adaptador."
    if status in (401, 403) or "billing" in str(error).lower():
        return "La clave no tiene permiso o el proyecto no tiene facturación activa (necesaria para imágenes)."
    if status == 404:
        return "El modelo no existe para esta clave: prueba otro con IMAGE_MODEL o SPEECH_MODEL."
    if status == 429:
        return "Se acabó la cuota de hoy o del minuto. Espera o usa otro proyecto con facturación."
    return "Revisa la conexión y vuelve a intentar."


def main() -> int:
    parser = argparse.ArgumentParser(description="Prueba la voz y las imágenes de Gemini con tu clave.")
    parser.add_argument("--out", type=Path, default=Path("media-check"))
    parser.add_argument("--skip-image", action="store_true", help="solo prueba la voz")
    args = parser.parse_args()
    key = os.getenv("LLM_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not key:
        print("Define LLM_API_KEY con la clave de Google AI Studio.")
        return 2
    generator = GeminiMediaGenerator(
        key,
        image_model=os.getenv("IMAGE_MODEL") or None,
        speech_model=os.getenv("SPEECH_MODEL") or None,
        voice=os.getenv("SPEECH_VOICE") or None,
    )
    args.out.mkdir(exist_ok=True)
    checks = [("voz", generator.speech_model, lambda: generator.synthesize_speech(SCRIPT), "audio")]
    if not args.skip_image:
        checks.append(("imagen", generator.image_model, lambda: generator.generate_image(PROMPT), "imagen"))
    ok = True
    for label, model, run, name in checks:
        try:
            media = run()
        except AIProviderError as error:
            ok = False
            print(f"✗ {label} ({model}): {error}\n  {hint(error)}")
            continue
        path = args.out / f"{name}.{media.extension}"
        path.write_bytes(media.content)
        print(f"✓ {label} ({model}): {path} · {media.mime_type} · {len(media.content) // 1024} KB")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
