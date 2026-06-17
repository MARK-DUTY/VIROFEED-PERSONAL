"""
ORQUESTADOR del pipeline, en DOS PASOS (como el editor de ViroFeed):

  PASO 1 (prepare_video):
    URL -> articulo -> guion en escenas (IA) -> voz -> imagenes por escena
    Devuelve un PreparedJob para que el usuario REVISE las imagenes.

  (el usuario puede regenerar / reemplazar imagenes que salieron mal)

  PASO 2 (assemble_prepared):
    subtitulos -> (avatar opcional) -> ensamblar video final .mp4

Asi el usuario aprueba/corrige las imagenes ANTES de armar el video.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import avatar as avatar_mod
from .article import extract_article
from .assemble import build_video, probe_duration
from .config import settings
from .images import ImageResult, fetch_scene_images, fetch_single_image
from .script_gen import Scene, generate_script
from .subtitles import SubtitleStyle, build_ass_subtitles, build_subtitles_from_text
from .voice import WordTiming, synthesize_voice

ProgressFn = Callable[[str, int], None]


def _noop(msg: str, pct: int) -> None:
    pass


def _slugify(text: str, maxlen: int = 40) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "" for c in text)
    keep = "_".join(keep.split())
    return (keep[:maxlen] or "video").strip("_")


@dataclass
class PreparedJob:
    """Estado intermedio: todo listo menos el video final (a la espera de revision)."""
    job_dir: Path
    title: str
    narration: str
    scenes: list[Scene]
    images: list[ImageResult]          # una por escena (editable por el usuario)
    audio_path: Path
    audio_words: list[WordTiming]
    real_duration: float
    titles: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    image_source: str = "hybrid"


@dataclass
class VideoJobResult:
    video_path: Path
    title: str
    narration: str
    titles: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    duration: float = 0.0
    used_avatar: bool = False
    image_source: str = "hybrid"


def _scene_durations(scenes: list[Scene], total_duration: float) -> list[float]:
    """Reparte la duracion total entre escenas, segun cuantas palabras narra cada una."""
    counts = [max(1, len(s.text.split())) for s in scenes]
    total_words = sum(counts)
    return [total_duration * (c / total_words) for c in counts]


# ==========================================================================
#  PASO 1: preparar (guion + voz + imagenes) para revisar
# ==========================================================================
def prepare_video(
    url: str,
    *,
    duration: int | None = None,
    style: str | None = None,
    voice: str | None = None,
    rate: str | None = None,
    cta: str | None = None,
    image_source: str | None = None,
    progress: ProgressFn = _noop,
) -> PreparedJob:
    cfg = settings
    duration = duration or cfg.video_duration
    voice = voice or cfg.tts_voice
    rate = rate if rate is not None else cfg.tts_rate
    style = style or cfg.script_style
    cta = cta or cfg.call_to_action
    image_source = (image_source or cfg.image_source or "hybrid").lower()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_dir = cfg.work_dir / f"job_{stamp}"
    job_dir.mkdir(parents=True, exist_ok=True)
    images_dir = job_dir / "images"

    # 1) Leer la noticia
    progress("Leyendo la noticia...", 8)
    article = extract_article(url)

    # 2) Guion en escenas
    progress("Escribiendo el guion viral con IA...", 25)
    script = generate_script(article, duration=duration, style=style, cta=cta)
    print(f"[guion] {len(script.scenes)} escenas generadas")

    # 3) Voz
    progress("Generando la voz en espanol...", 45)
    audio = synthesize_voice(
        script.narration, voice=voice, rate=rate, out_path=job_dir / "voz.mp3"
    )
    real_duration = probe_duration(audio.audio_path) or audio.duration or float(duration)

    # 4) Imagenes por escena
    progress(f"Generando imagenes ({image_source})...", 60)
    print(f"[imagenes] fuente: {image_source}")
    images = fetch_scene_images(
        script.scenes, images_dir, source=image_source, progress=progress
    )
    for im in images:
        print(f"[imagenes] {im.source}: {im.query[:60]}")

    progress("Listo para revisar imagenes!", 100)

    return PreparedJob(
        job_dir=job_dir,
        title=article.title,
        narration=script.narration,
        scenes=script.scenes,
        images=images,
        audio_path=audio.audio_path,
        audio_words=audio.words,
        real_duration=real_duration,
        titles=script.titles,
        hashtags=script.hashtags,
        image_source=image_source,
    )


# ==========================================================================
#  Regenerar / reemplazar la imagen de UNA escena
# ==========================================================================
def regenerate_scene_image(
    prepared: PreparedJob,
    index: int,
    mode: str = "hybrid",
    new_prompt: str | None = None,
    new_keyword: str | None = None,
    attempt: int = 0,
) -> ImageResult:
    """
    Vuelve a generar/buscar la imagen de la escena `index`.

    mode       : "ai" | "stock" | "hybrid"
    new_prompt : si el usuario edito la descripcion visual, se usa esta
    attempt    : numero de intento (cambia la semilla para obtener algo distinto)
    """
    if index < 0 or index >= len(prepared.scenes):
        raise ValueError("Escena fuera de rango.")

    scene = prepared.scenes[index]
    if new_prompt:
        scene.image_prompt = new_prompt.strip()
    if new_keyword:
        scene.keyword = new_keyword.strip()

    images_dir = prepared.job_dir / "images"
    # nombre nuevo en cada intento (evita que el navegador muestre la imagen vieja en cache)
    ts = datetime.now().strftime("%H%M%S")
    dest = images_dir / f"img_{index:02d}_{ts}_{attempt}.jpg"

    seed = 1000 + index * 100 + attempt + 1
    result = fetch_single_image(scene.image_prompt, scene.keyword, dest, mode=mode, seed=seed)
    if result is None:
        raise ValueError(
            "No pude generar/encontrar una nueva imagen. "
            "Prueba con otra descripcion, o cambia a 'foto real'."
        )

    prepared.images[index] = result
    return result


def set_scene_image(prepared: PreparedJob, index: int, image_path: Path, source: str = "subida") -> ImageResult:
    """Asigna una imagen ya guardada (por ejemplo, subida por el usuario) a una escena."""
    if index < 0 or index >= len(prepared.scenes):
        raise ValueError("Escena fuera de rango.")
    result = ImageResult(path=Path(image_path), source=source, query="imagen subida")
    prepared.images[index] = result
    return result


# ==========================================================================
#  PASO 2: ensamblar el video final con las imagenes ya aprobadas
# ==========================================================================
def assemble_prepared(
    prepared: PreparedJob,
    *,
    subtitle_color: str = "amarillo",
    subtitle_position: str = "center",
    use_avatar: bool = False,
    progress: ProgressFn = _noop,
) -> VideoJobResult:
    cfg = settings
    job_dir = prepared.job_dir

    # Subtitulos
    progress("Creando los subtitulos sincronizados...", 30)
    sub_style = SubtitleStyle(name=subtitle_color, position=subtitle_position)
    if prepared.audio_words:
        print(f"[subtitulos] {len(prepared.audio_words)} palabras con tiempos exactos")
        subs = build_ass_subtitles(prepared.audio_words, job_dir / "subtitles.ass", style=sub_style)
    else:
        print("[subtitulos] usando Plan B (reparto por texto)")
        subs = build_subtitles_from_text(
            prepared.narration, prepared.real_duration, job_dir / "subtitles.ass", style=sub_style
        )

    # Avatar opcional
    avatar_video = None
    if use_avatar:
        progress("Generando el avatar en la nube...", 55)
        face = cfg.assets_dir / "avatar.jpg"
        avatar_video = avatar_mod.generate_avatar_video(
            prepared.audio_path, face, job_dir / "avatar.mp4"
        )

    # Duraciones sincronizadas por escena
    img_durations = _scene_durations(prepared.scenes, prepared.real_duration)
    if len(img_durations) != len(prepared.images):
        img_durations = [prepared.real_duration / max(1, len(prepared.images))] * len(prepared.images)

    # Ensamblar
    progress("Ensamblando el video final...", 75)
    logo = cfg.assets_dir / "logo.png"
    out_name = f"{prepared.job_dir.name}_{_slugify(prepared.title)}.mp4"
    out_path = cfg.output_dir / out_name
    result = build_video(
        images=[im.path for im in prepared.images],
        audio_path=prepared.audio_path,
        subtitles_path=subs,
        out_path=out_path,
        work_dir=job_dir,
        logo_path=logo if logo.exists() else None,
        avatar_video=avatar_video,
        target_duration=prepared.real_duration,
        image_durations=img_durations,
    )

    progress("Listo!", 100)
    return VideoJobResult(
        video_path=result.video_path,
        title=prepared.title,
        narration=prepared.narration,
        titles=prepared.titles,
        hashtags=prepared.hashtags,
        duration=result.duration,
        used_avatar=bool(avatar_video),
        image_source=prepared.image_source,
    )


# ==========================================================================
#  Compatibilidad: flujo de un solo paso (sin revision de imagenes)
# ==========================================================================
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
    image_source: str | None = None,
    progress: ProgressFn = _noop,
) -> VideoJobResult:
    prepared = prepare_video(
        url,
        duration=duration,
        style=style,
        voice=voice,
        rate=rate,
        cta=cta,
        image_source=image_source,
        progress=progress,
    )
    return assemble_prepared(
        prepared,
        subtitle_color=subtitle_color,
        subtitle_position=subtitle_position,
        use_avatar=bool(use_avatar) if use_avatar is not None else settings.avatar_enabled,
        progress=progress,
    )
