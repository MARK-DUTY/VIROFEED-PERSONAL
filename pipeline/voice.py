"""
Paso 3 del pipeline: convertir el guion en VOZ (audio) en espanol.

Usa Edge TTS (Microsoft), que es GRATIS e ILIMITADO y suena muy natural.
Ademas de generar el audio .mp3, capturamos el tiempo exacto en el que se
pronuncia cada palabra. Eso nos sirve para que los subtitulos aparezcan
perfectamente sincronizados (estilo CapCut / videos virales).
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

import edge_tts


@dataclass
class WordTiming:
    """Una palabra y cuando se dice (en segundos)."""
    word: str
    start: float   # segundo en que empieza
    end: float     # segundo en que termina


@dataclass
class VoiceResult:
    audio_path: Path
    words: list[WordTiming]
    duration: float   # duracion total del audio en segundos


def _ticks_to_seconds(ticks: int) -> float:
    # Edge TTS reporta el tiempo en "ticks" de 100 nanosegundos
    return ticks / 10_000_000.0


async def _synthesize(text: str, voice: str, rate: str, out_path: Path) -> list[WordTiming]:
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    words: list[WordTiming] = []

    with open(out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = _ticks_to_seconds(chunk["offset"])
                dur = _ticks_to_seconds(chunk["duration"])
                words.append(
                    WordTiming(
                        word=chunk["text"],
                        start=round(start, 3),
                        end=round(start + dur, 3),
                    )
                )
    return words


def synthesize_voice(
    text: str,
    voice: str,
    out_path: Path,
    rate: str = "+0%",
) -> VoiceResult:
    """
    Genera el audio del texto y devuelve la ruta + los tiempos de cada palabra.

    Funciona en Windows sin problemas (maneja el bucle de asyncio por dentro).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    text = (text or "").strip()
    if not text:
        raise ValueError("No hay texto para convertir en voz.")

    words = asyncio.run(_synthesize(text, voice, rate, out_path))

    if not out_path.exists() or out_path.stat().st_size == 0:
        raise ValueError(
            "No se genero el audio. Revisa tu conexion a internet "
            "(Edge TTS necesita internet) y el nombre de la voz en .env."
        )

    duration = words[-1].end if words else 0.0
    return VoiceResult(audio_path=out_path, words=words, duration=duration)


async def _list_voices_es() -> list[dict]:
    voices = await edge_tts.list_voices()
    return [v for v in voices if v.get("Locale", "").startswith("es")]


def list_spanish_voices() -> list[dict]:
    """Lista las voces en espanol disponibles (util para la interfaz)."""
    try:
        return asyncio.run(_list_voices_es())
    except Exception:
        return []


# Frase de ejemplo para que el usuario ESCUCHE como suena una voz antes de
# elegirla. Es corta para que se genere rapido.
VOICE_SAMPLE_TEXT = (
    "Hola, asi se escuchara la narracion de tu video. "
    "Espero que esta voz te guste para tu proyecto."
)


def synthesize_voice_sample(
    voice: str,
    previews_dir: Path,
    rate: str = "+0%",
) -> Path:
    """
    Genera (o reutiliza) un audio CORTO de ejemplo con la voz indicada, para que
    el usuario la escuche antes de elegirla. Guarda el archivo en `previews_dir`
    con un nombre basado en la voz, asi la segunda vez no lo vuelve a generar
    (cache) y suena al instante.
    """
    voice = (voice or "").strip()
    if not voice:
        raise ValueError("No se indico ninguna voz para la muestra.")

    previews_dir = Path(previews_dir)
    previews_dir.mkdir(parents=True, exist_ok=True)

    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", voice)
    out_path = previews_dir / f"sample_{safe}.mp3"

    # Si ya la generamos antes, la reutilizamos (mas rapido).
    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path

    asyncio.run(_synthesize(VOICE_SAMPLE_TEXT, voice, rate, out_path))

    if not out_path.exists() or out_path.stat().st_size == 0:
        raise ValueError(
            "No se pudo generar la muestra de voz. Revisa tu conexion a internet "
            "(Edge TTS necesita internet) y que el nombre de la voz sea valido."
        )
    return out_path
