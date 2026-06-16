"""
ORQUESTADOR del pipeline completo.

Une todos los pasos en una sola funcion `create_video_from_url()`:

  URL  ->  articulo  ->  guion (IA)  ->  voz  ->  imagenes  ->
  subtitulos  ->  (avatar opcional)  ->  video final .mp4

Reporta el progreso mediante un callback para mostrarlo en la interfaz.
"""
from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import avatar as avatar_mod
from .article import extract_article
from .assemble import build_video
from .config import settings
from .images import fetch_images
from .script_gen import generate_script
from .subtitles import SubtitleStyle, build_ass_subtitles
from .voice import synthesize_voice

ProgressFn = Callable[[str, int], None]


@dataclass
class VideoJobResult:
    video_path: Path
    title: str
    narration: str
    titles: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    duration: float = 0.0
    used_avatar: bool = False


def _noop(msg: str, pct: int) -> None:
    pass


def _slugify(text: str, maxlen: int = 40) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "" for c in text)
    keep = "_".join(keep.split())
    return (keep[:maxlen] or "video").strip("_")


def create_video_from_url(
    url: str,
    *,
    duration: int | None = None,
    style: str | None = None,
    voice: str | None = None,
    rate: str | None = None,
    cta: str | None = None,
    subtitle_color: str = "amarillo",
    subtitle_position: str = "center",
    use_avatar: bool | None = None,
    progress: ProgressFn = _noop,
) -> VideoJobResult:
    """Ejecuta el pipeline completo y devuelve el resultado."""
    cfg = settings
    duration = duration or cfg.video_duration
    voice = voice or cfg.tts_voice
    rate = rate if rate is not None else cfg.tts_rate
    style = style or cfg.script_style
    cta = cta or cfg.call_to_action
    use_avatar = cfg.avatar_enabled if use_avatar is None else use_avatar

    # Carpeta de trabajo unica para este video
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_dir = cfg.work_dir / f"job_{stamp}"
    job_dir.mkdir(parents=True, exist_ok=True)
    images_dir = job_dir / "images"

    # 1) Leer la noticia
    progress("Leyendo la noticia...", 8)
    article = extract_article(url)

    # 2) Generar el guion con IA
    progress("Escribiendo el guion viral con IA...", 22)
    script = generate_script(article, duration=duration, style=style, cta=cta)

    # 3) Generar la voz
    progress("Generando la voz en espanol...", 40)
    audio = synthesize_voice(
        script.narration, voice=voice, rate=rate, out_path=job_dir / "voz.mp3"
    )

    # 4) Descargar imagenes
    progress("Buscando y descargando imagenes...", 58)
    n_images = max(4, min(8, round((audio.duration or duration) / 7)))
    images = fetch_images(script.image_keywords, images_dir, min_images=n_images)

    # 5) Subtitulos
    progress("Creando los subtitulos sincronizados...", 70)
    subs = None
    if audio.words:
        subs = build_ass_subtitles(
            audio.words,
            job_dir / "subtitles.ass",
            style=SubtitleStyle(name=subtitle_color, position=subtitle_position),
        )

    # 6) Avatar (opcional)
    avatar_video = None
    if use_avatar:
        progress("Generando el avatar en la nube...", 80)
        face = cfg.assets_dir / "avatar.jpg"
        avatar_video = avatar_mod.generate_avatar_video(
            audio.audio_path, face, job_dir / "avatar.mp4"
        )

    # 7) Ensamblar el video final
    progress("Ensamblando el video final...", 90)
    logo = cfg.assets_dir / "logo.png"
    out_name = f"{stamp}_{_slugify(article.title)}.mp4"
    out_path = cfg.output_dir / out_name
    result = build_video(
        images=[im.path for im in images],
        audio_path=audio.audio_path,
        subtitles_path=subs,
        out_path=out_path,
        work_dir=job_dir,
        logo_path=logo if logo.exists() else None,
        avatar_video=avatar_video,
        target_duration=audio.duration or duration,
    )

    progress("Listo!", 100)

    return VideoJobResult(
        video_path=result.video_path,
        title=article.title,
        narration=script.narration,
        titles=script.titles,
        hashtags=script.hashtags,
        duration=result.duration,
        used_avatar=bool(avatar_video),
    )
