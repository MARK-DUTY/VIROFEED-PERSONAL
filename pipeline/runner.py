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
try:
    from . import music as music_mod
except Exception:  # si falta music.py, el programa sigue funcionando (sin musica automatica)
    music_mod = None
from .article import extract_article, extract_articles
from .assemble import build_video, probe_duration, resolution_for
from .config import settings
from .images import ImageResult, fetch_scene_images, fetch_scene_videos, fetch_single_image, fetch_single_video
from .script_gen import Scene, generate_script, generate_script_from_story
from .subtitles import SubtitleStyle, build_ass_subtitles, build_subtitles_from_text
from .voice import WordTiming, synthesize_voice

ProgressFn = Callable[[str, int], None]


def _noop(msg: str, pct: int) -> None:
    pass


def _slugify(text: str, maxlen: int = 40) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "" for c in text)
    keep = "_".join(keep.split())
    return (keep[:maxlen] or "video").strip("_")


# Palabras que activan el modo "voz automatica" (rotacion)
_RANDOM_VOICE_WORDS = {"random", "auto", "automatica", "automática", "aleatoria", "azar", ""}

# Atajos para elegir simplemente "voz de hombre" o "voz de mujer" desde la
# pantalla de revision (sin tener que conocer el nombre exacto de la voz).
_MALE_WORDS = {"hombre", "masculino", "man", "male", "h"}
_FEMALE_WORDS = {"mujer", "femenino", "woman", "female", "m"}
DEFAULT_MALE_VOICE = "es-MX-JorgeNeural"
DEFAULT_FEMALE_VOICE = "es-MX-DaliaNeural"

# Nombres comunes de voces FEMENINAS en espanol de Edge TTS. Sirve para saber,
# a partir del nombre de la voz, si debemos usar la foto de mujer o de hombre.
_FEMALE_VOICE_NAMES = {
    "dalia", "elvira", "salome", "paloma", "larissa", "ximena", "sabina",
    "tania", "marisol", "yolanda", "nuria", "renata", "emilia", "julia",
    "camila", "valentina", "abril", "luciana", "catalina", "amanda",
    "estrella", "vera", "marta", "irene",
}


def _voice_is_female(voice: str | None) -> bool:
    """Adivina si una voz es femenina por su nombre (para escoger la foto)."""
    name = (voice or "").lower()
    return any(fn in name for fn in _FEMALE_VOICE_NAMES)


def _pick_avatar_face(assets_dir: Path, voice: str | None) -> Path:
    """
    Elige la FOTO del avatar que combina con la voz:
      - voz de mujer  -> assets/avatar_mujer.jpg  (o .png)
      - voz de hombre -> assets/avatar_hombre.jpg (o .png)
    Si no existe la foto por genero, usa assets/avatar.jpg como respaldo.
    """
    if _voice_is_female(voice):
        candidates = ["avatar_mujer.jpg", "avatar_mujer.png", "avatar.jpg", "avatar.png"]
    else:
        candidates = ["avatar_hombre.jpg", "avatar_hombre.png", "avatar.jpg", "avatar.png"]
    for name in candidates:
        p = assets_dir / name
        if p.exists():
            return p
    # No encontramos ninguna; devolvemos la ruta por defecto para que el avatar
    # muestre un mensaje claro de "falta assets/avatar.jpg".
    return assets_dir / "avatar.jpg"


def _next_rotating_voice() -> str:
    """
    Devuelve la siguiente voz del grupo (rotando en cada llamada).
    Guarda el indice en un archivito para que la rotacion continue aunque
    se cierre y se vuelva a abrir el programa.

    Ejemplo: video 1 -> voz 1, video 2 -> voz 2, ... y al llegar al final
    vuelve a empezar.
    """
    pool = [v for v in settings.voice_pool if v] or ["es-MX-JorgeNeural"]
    state_file = settings.work_dir / "voice_rotation.txt"
    try:
        idx = int(state_file.read_text(encoding="utf-8").strip())
    except Exception:
        idx = 0
    voice = pool[idx % len(pool)]
    try:
        state_file.write_text(str((idx + 1) % 1_000_000), encoding="utf-8")
    except Exception:
        pass
    print(f"[voz] modo automatico -> voz {idx % len(pool) + 1} de {len(pool)}: {voice}")
    return voice


def _resolve_voice(voice: str | None) -> str:
    """Si el usuario pidio 'voz automatica', elige la siguiente del grupo.
    Tambien entiende los atajos 'hombre' y 'mujer'."""
    v = (voice or "").strip().lower()
    if v in _RANDOM_VOICE_WORDS:
        return _next_rotating_voice()
    if v in _MALE_WORDS:
        return DEFAULT_MALE_VOICE
    if v in _FEMALE_WORDS:
        return DEFAULT_FEMALE_VOICE
    return voice  # type: ignore[return-value]


@dataclass
class PreparedJob:
    """Estado intermedio: todo listo menos el video final (a la espera de revision)."""
    job_dir: Path
    title: str
    narration: str
    scenes: list[Scene]
    images: list[ImageResult] = field(default_factory=list)  # una por escena (editable)
    audio_path: Path | None = None
    audio_words: list[WordTiming] = field(default_factory=list)
    real_duration: float = 0.0
    titles: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    image_source: str = "hybrid"
    # Tipo de fondo: "image" (fotos) o "video" (videoclips de stock).
    media_type: str = "image"
    # Aviso para el usuario cuando NO se pudo llegar a la duracion pedida
    # (por falta de material). Cadena vacia = sin aviso.
    warning: str = ""
    # Datos para poder REGENERAR la voz si el usuario edita los dialogos:
    voice: str = "es-MX-JorgeNeural"
    rate: str = "+0%"
    synth_narration: str = ""           # narracion con la que se genero el audio actual
    # Musica de fondo opcional (la sube el usuario). None = sin musica.
    music_path: Path | None = None
    # Memoria de fotos de stock ya mostradas, por escena (para que "Otra foto"
    # entregue una DISTINTA en cada clic y no repita la misma).
    used_image_urls: dict[int, set] = field(default_factory=dict)

    def current_narration(self) -> str:
        """La narracion actual = union de los textos de las escenas (tras editar)."""
        return " ".join(s.text for s in self.scenes if s.text.strip()).strip()


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


def _fetch_media(
    scenes: list[Scene],
    images_dir: Path,
    media_type: str,
    image_source: str,
    progress: ProgressFn,
) -> list[ImageResult]:
    """
    Consigue el fondo de cada escena segun el tipo elegido:
      - "video" -> videoclips de stock (Pexels/Pixabay)
      - cualquier otro -> fotos/imagenes (comportamiento de siempre)
    """
    if (media_type or "image").lower() == "video":
        progress("Consiguiendo videoclips...", 60)
        print("[medios] tipo de fondo: videoclips de stock")
        return fetch_scene_videos(scenes, images_dir, progress=progress)
    progress(f"Generando imagenes ({image_source})...", 60)
    print(f"[medios] tipo de fondo: fotos (fuente: {image_source})")
    return fetch_scene_images(scenes, images_dir, source=image_source, progress=progress)


# ==========================================================================
#  PASO 1: preparar (guion + voz + imagenes) para revisar
# ==========================================================================
def prepare_video(
    url,
    *,
    duration: int | None = None,
    style: str | None = None,
    n_images=None,
    voice: str | None = None,
    rate: str | None = None,
    cta: str | None = None,
    image_source: str | None = None,
    media_type: str = "image",
    progress: ProgressFn = _noop,
) -> PreparedJob:
    cfg = settings
    # `url` puede ser un solo enlace (texto) o varios (lista). Normalizamos.
    urls = url if isinstance(url, list) else [url]
    duration = duration or cfg.video_duration
    voice = voice or cfg.tts_voice
    voice = _resolve_voice(voice)   # si es "automatica", elige una del grupo (rotando)
    rate = rate if rate is not None else cfg.tts_rate
    style = style or cfg.script_style
    cta = cta or cfg.call_to_action
    image_source = (image_source or cfg.image_source or "hybrid").lower()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_dir = cfg.work_dir / f"job_{stamp}"
    job_dir.mkdir(parents=True, exist_ok=True)
    images_dir = job_dir / "images"

    # 1) Leer la(s) noticia(s) y combinarlas
    n = len([u for u in urls if str(u).strip()])
    progress("Leyendo la noticia..." if n <= 1 else f"Leyendo {n} noticias...", 8)
    article = extract_articles(urls)

    # 2) Guion en escenas
    progress("Escribiendo el guion viral con IA...", 25)
    script = generate_script(article, duration=duration, style=style, cta=cta, n_images=n_images)
    print(f"[guion] {len(script.scenes)} escenas generadas")

    # 3) Voz
    progress("Generando la voz en espanol...", 45)
    audio = synthesize_voice(
        script.narration, voice=voice, rate=rate, out_path=job_dir / "voz.mp3"
    )
    real_duration = probe_duration(audio.audio_path) or audio.duration or float(duration)

    # 4) Medios por escena (fotos o videoclips)
    images = _fetch_media(script.scenes, images_dir, media_type, image_source, progress)
    for im in images:
        print(f"[medios] {im.source}: {im.query[:60]}")

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
        media_type=media_type,
        warning=script.warning,
        voice=voice,
        rate=rate,
        synth_narration=script.narration,
    )


# ==========================================================================
#  PASO 1 (YOUTUBE): preparar (subtitulos -> guion + voz + imagenes) a revisar
# ==========================================================================
def prepare_youtube(
    url,
    *,
    duration: int | None = None,
    style: str | None = None,
    n_images=None,
    voice: str | None = None,
    rate: str | None = None,
    cta: str | None = None,
    image_source: str | None = None,
    media_type: str = "image",
    progress: ProgressFn = _noop,
) -> PreparedJob:
    """
    Igual que prepare_video, pero el texto sale de uno o VARIOS VIDEOS DE YOUTUBE
    (sus subtitulos) en vez de una noticia. El resto del flujo es identico.
    """
    # Import "perezoso": asi runner.py se importa bien aunque youtube.py todavia
    # no se haya descargado (la auto-reparacion de app.py lo trae al arrancar).
    from .youtube import extract_youtubes

    cfg = settings
    # `url` puede ser un solo enlace (texto) o varios (lista). Normalizamos.
    urls = url if isinstance(url, list) else [url]
    duration = duration or cfg.video_duration
    voice = voice or cfg.tts_voice
    voice = _resolve_voice(voice)   # si es "automatica", elige una del grupo (rotando)
    rate = rate if rate is not None else cfg.tts_rate
    style = style or cfg.script_style
    cta = cta or cfg.call_to_action
    image_source = (image_source or cfg.image_source or "hybrid").lower()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_dir = cfg.work_dir / f"job_{stamp}"
    job_dir.mkdir(parents=True, exist_ok=True)
    images_dir = job_dir / "images"

    # 1) Leer los subtitulos del/los video(s) de YouTube y combinarlos
    n = len([u for u in urls if str(u).strip()])
    progress(
        "Leyendo los subtitulos del video de YouTube..." if n <= 1
        else f"Leyendo los subtitulos de {n} videos de YouTube...",
        8,
    )
    article = extract_youtubes(urls)

    # 2) Guion en escenas (mismo motor que el modo noticia)
    progress("Escribiendo el guion viral con IA...", 25)
    script = generate_script(article, duration=duration, style=style, cta=cta, n_images=n_images)
    print(f"[guion] {len(script.scenes)} escenas generadas (desde YouTube)")

    # 3) Voz
    progress("Generando la voz en espanol...", 45)
    audio = synthesize_voice(
        script.narration, voice=voice, rate=rate, out_path=job_dir / "voz.mp3"
    )
    real_duration = probe_duration(audio.audio_path) or audio.duration or float(duration)

    # 4) Medios por escena (fotos o videoclips)
    images = _fetch_media(script.scenes, images_dir, media_type, image_source, progress)
    for im in images:
        print(f"[medios] {im.source}: {im.query[:60]}")

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
        media_type=media_type,
        warning=script.warning,
        voice=voice,
        rate=rate,
        synth_narration=script.narration,
    )


# ==========================================================================
#  MODO HISTORIA - PASO A: crear el BORRADOR (guion + prompts, SIN imagenes)
# ==========================================================================
def draft_story(
    story: str,
    *,
    duration: int | None = None,
    n_images=8,
    voice: str | None = None,
    rate: str | None = None,
    cta: str | None = None,
    image_source: str | None = None,
    media_type: str = "image",
    progress: ProgressFn = _noop,
) -> PreparedJob:
    """
    Convierte la HISTORIA del usuario en un guion dividido en escenas con su
    prompt de imagen, PERO todavia NO genera imagenes ni voz.

    Devuelve un PreparedJob "borrador" para que el usuario revise y edite los
    prompts (y el dialogo) antes de gastar tiempo generando nada.
    """
    cfg = settings
    duration = duration or cfg.video_duration
    voice = _resolve_voice(voice or cfg.tts_voice)
    rate = rate if rate is not None else cfg.tts_rate
    cta = cta or cfg.call_to_action
    image_source = (image_source or cfg.image_source or "hybrid").lower()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_dir = cfg.work_dir / f"job_{stamp}"
    job_dir.mkdir(parents=True, exist_ok=True)

    progress("Escribiendo el guion y los prompts con IA...", 40)
    script = generate_script_from_story(
        story, duration=duration, n_images=n_images, cta=cta
    )
    print(f"[historia] {len(script.scenes)} escenas/prompts generados")

    # Titulo amigable: el primero sugerido o las primeras palabras de la historia
    title = (script.titles[0] if script.titles else "").strip()
    if not title:
        title = " ".join(story.strip().split()[:8]) or "Mi historia"

    progress("Borrador listo para revisar!", 100)

    return PreparedJob(
        job_dir=job_dir,
        title=title,
        narration=script.narration,
        scenes=script.scenes,
        images=[],                 # aun no hay imagenes (se generan al aprobar)
        audio_path=None,           # aun no hay voz
        audio_words=[],
        real_duration=float(duration),
        titles=script.titles,
        hashtags=script.hashtags,
        image_source=image_source,
        media_type=media_type,
        warning=script.warning,
        voice=voice,
        rate=rate,
        synth_narration="",
    )


# ==========================================================================
#  Editar el PROMPT de imagen de una escena (en el borrador)
# ==========================================================================
def update_scene_prompt(prepared: PreparedJob, index: int, new_prompt: str) -> None:
    """Cambia la descripcion de imagen (image_prompt) de una escena."""
    if index < 0 or index >= len(prepared.scenes):
        raise ValueError("Escena fuera de rango.")
    prompt = (new_prompt or "").strip()
    if not prompt:
        raise ValueError("La descripcion de la imagen no puede quedar vacia.")
    prepared.scenes[index].image_prompt = prompt


# ==========================================================================
#  MODO HISTORIA - PASO B: generar VOZ + IMAGENES desde el borrador aprobado
# ==========================================================================
def prepare_from_draft(
    prepared: PreparedJob,
    *,
    progress: ProgressFn = _noop,
) -> PreparedJob:
    """
    Con los prompts y dialogos ya aprobados por el usuario, genera la VOZ y las
    IMAGENES. Despues el flujo continua igual que el modo noticia (revision de
    imagenes -> ensamblar video final).
    """
    cfg = settings
    job_dir = prepared.job_dir
    images_dir = job_dir / "images"

    narration = prepared.current_narration()

    # 1) Voz
    progress("Generando la voz en espanol...", 35)
    audio = synthesize_voice(
        narration, voice=prepared.voice, rate=prepared.rate, out_path=job_dir / "voz.mp3"
    )
    prepared.audio_path = audio.audio_path
    prepared.audio_words = audio.words
    prepared.real_duration = probe_duration(audio.audio_path) or audio.duration or prepared.real_duration
    prepared.narration = narration
    prepared.synth_narration = narration

    # 2) Medios por escena (fotos o videoclips, segun lo elegido)
    images = _fetch_media(
        prepared.scenes, images_dir, prepared.media_type, prepared.image_source, progress
    )
    prepared.images = images

    progress("Listo para revisar imagenes!", 100)
    return prepared


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

    mode       : "together" | "gemini" | "ai" | "stock" | "hybrid"
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
    ts = datetime.now().strftime("%H%M%S")

    used = prepared.used_image_urls.setdefault(index, set())
    current = prepared.images[index] if index < len(prepared.images) else None
    if current is not None and getattr(current, "url", ""):
        used.add(current.url)

    # --- Caso VIDEOCLIP: el usuario pidio "otro videoclip" ---
    if (mode or "").lower() == "video":
        dest = images_dir / f"vid_{index:02d}_{ts}_{attempt}.mp4"
        result = fetch_single_video(scene.image_prompt, scene.keyword, dest, used_urls=used)
        if result is None:
            used.clear()
            result = fetch_single_video(scene.image_prompt, scene.keyword, dest, used_urls=used)
        if result is None:
            raise ValueError(
                "No pude encontrar otro videoclip. Prueba con otra descripcion, "
                "o cambia el fondo a 'Fotos'."
            )
        if getattr(result, "url", ""):
            used.add(result.url)
        prepared.images[index] = result
        return result

    # --- Caso FOTO/IMAGEN (comportamiento de siempre) ---
    # nombre nuevo en cada intento (evita que el navegador muestre la imagen vieja en cache)
    dest = images_dir / f"img_{index:02d}_{ts}_{attempt}.jpg"

    seed = 1000 + index * 100 + attempt + 1
    result = fetch_single_image(
        scene.image_prompt, scene.keyword, dest, mode=mode, seed=seed, used_urls=used
    )
    if result is None:
        # Quiza se agotaron las fotos nuevas para esta escena: reiniciamos la
        # memoria y reintentamos (asi vuelve a haber opciones en vez de fallar).
        used.clear()
        result = fetch_single_image(
            scene.image_prompt, scene.keyword, dest, mode=mode, seed=seed, used_urls=used
        )
    if result is None:
        raise ValueError(
            "No pude generar/encontrar una nueva imagen. "
            "Prueba con otra descripcion, o cambia a 'foto real'."
        )

    if getattr(result, "url", ""):
        used.add(result.url)
    prepared.images[index] = result
    return result


def set_scene_image(prepared: PreparedJob, index: int, image_path: Path, source: str = "subida") -> ImageResult:
    """Asigna un archivo ya guardado (imagen O video subido) a una escena."""
    if index < 0 or index >= len(prepared.scenes):
        raise ValueError("Escena fuera de rango.")
    is_video = Path(image_path).suffix.lower() in (".mp4", ".mov", ".webm", ".m4v")
    result = ImageResult(
        path=Path(image_path), source=source, query="archivo subido", is_video=is_video
    )
    prepared.images[index] = result
    return result


# ==========================================================================
#  Editar el DIALOGO (texto narrado) de una escena
# ==========================================================================
def update_scene_text(prepared: PreparedJob, index: int, new_text: str) -> None:
    """
    Cambia el dialogo (lo que se narra) de una escena.

    OJO: al cambiar el dialogo, la voz y los subtitulos quedaran desactualizados.
    Por eso 'assemble_prepared' detecta el cambio y REGENERA la voz automaticamente
    antes de armar el video, para que todo quede sincronizado.
    """
    if index < 0 or index >= len(prepared.scenes):
        raise ValueError("Escena fuera de rango.")
    text = (new_text or "").strip()
    if not text:
        raise ValueError("El dialogo no puede quedar vacio. Si no la quieres, elimina la escena.")
    prepared.scenes[index].text = text
    prepared.narration = prepared.current_narration()


# ==========================================================================
#  Eliminar una escena completa (su imagen + su dialogo)
# ==========================================================================
def delete_scene(prepared: PreparedJob, index: int) -> None:
    """Quita por completo una escena (imagen y dialogo) del video."""
    if index < 0 or index >= len(prepared.scenes):
        raise ValueError("Escena fuera de rango.")
    if len(prepared.scenes) <= 1:
        raise ValueError("No puedes eliminar la unica escena que queda.")
    prepared.scenes.pop(index)
    if index < len(prepared.images):
        prepared.images.pop(index)
    prepared.narration = prepared.current_narration()


# ==========================================================================
#  PASO 2: ensamblar el video final con las imagenes ya aprobadas
# ==========================================================================
def assemble_prepared(
    prepared: PreparedJob,
    *,
    subtitle_color: str = "amarillo",
    subtitle_position: str = "center",
    use_avatar: bool = False,
    voice: str | None = None,
    music_mode: str = "auto",
    music_volume: float = 0.15,
    aspect: str = "9:16",
    progress: ProgressFn = _noop,
) -> VideoJobResult:
    cfg = settings
    job_dir = prepared.job_dir

    # Formato del video (9:16 vertical, 16:9 horizontal, 1:1 cuadrado)
    video_w, video_h = resolution_for(aspect)

    # ¿El usuario eligio una voz distinta en la pantalla de revision?
    # (puede ser "hombre", "mujer", "automatica" o un nombre de voz concreto)
    desired_voice = _resolve_voice(voice) if voice else None
    voice_changed = desired_voice is not None and desired_voice != prepared.voice

    # Si el usuario edito dialogos o elimino escenas, la narracion cambio:
    # regeneramos la VOZ para que el audio y los subtitulos queden sincronizados.
    current = prepared.current_narration()
    narration_changed = bool(current) and current != prepared.synth_narration

    if voice_changed or narration_changed or prepared.audio_path is None:
        if voice_changed:
            prepared.voice = desired_voice  # type: ignore[assignment]
            print(f"[voz] el usuario cambio la voz -> {prepared.voice}")
        # Texto a narrar: el actual si cambio; si no, el mismo de antes.
        text_for_voice = current if narration_changed else (prepared.synth_narration or current)
        if not text_for_voice:
            text_for_voice = prepared.narration
        progress("Regenerando la voz...", 15)
        print("[voz] generando audio y tiempos")
        audio = synthesize_voice(
            text_for_voice, voice=prepared.voice, rate=prepared.rate, out_path=job_dir / "voz.mp3"
        )
        prepared.audio_path = audio.audio_path
        prepared.audio_words = audio.words
        prepared.real_duration = probe_duration(audio.audio_path) or audio.duration or prepared.real_duration
        prepared.narration = text_for_voice
        prepared.synth_narration = text_for_voice

    # Subtitulos
    progress("Creando los subtitulos sincronizados...", 30)
    sub_style = SubtitleStyle(
        name=subtitle_color, position=subtitle_position, lead_sec=cfg.subtitle_lead
    )
    if prepared.audio_words:
        print(f"[subtitulos] {len(prepared.audio_words)} palabras con tiempos exactos")
        subs = build_ass_subtitles(
            prepared.audio_words, job_dir / "subtitles.ass", style=sub_style,
            video_w=video_w, video_h=video_h,
        )
    else:
        print("[subtitulos] usando Plan B (reparto por texto)")
        subs = build_subtitles_from_text(
            prepared.narration, prepared.real_duration, job_dir / "subtitles.ass",
            style=sub_style, video_w=video_w, video_h=video_h,
        )

    # Avatar opcional
    avatar_video = None
    if use_avatar:
        progress("Generando el avatar en la nube...", 55)
        face = _pick_avatar_face(cfg.assets_dir, prepared.voice)
        print(f"[avatar] usando foto: {face.name}")
        avatar_video = avatar_mod.generate_avatar_video(
            prepared.audio_path, face, job_dir / "avatar.mp4"
        )

    # Duraciones sincronizadas por escena
    img_durations = _scene_durations(prepared.scenes, prepared.real_duration)
    if len(img_durations) != len(prepared.images):
        img_durations = [prepared.real_duration / max(1, len(prepared.images))] * len(prepared.images)

    # Musica de fondo segun el modo elegido:
    #   "off"  -> sin musica
    #   "own"  -> la que subio el usuario (si no hay, cae a automatica)
    #   "auto" -> una pista automatica generada (100% libre de derechos)
    mode = (music_mode or "auto").lower()
    music_file: Path | None = None
    if mode == "off":
        music_file = None
    elif mode == "own" and prepared.music_path and Path(prepared.music_path).exists():
        music_file = Path(prepared.music_path)
    else:
        music_file = None
        if music_mod is not None:
            progress("Preparando la musica de fondo...", 70)
            try:
                music_file = music_mod.pick_auto_music()
            except Exception as exc:  # noqa: BLE001
                print(f"[musica] no disponible: {exc}")
                music_file = None

    # Ensamblar
    progress("Ensamblando el video final...", 75)
    logo = cfg.assets_dir / "logo.png"
    out_name = f"{prepared.job_dir.name}_{_slugify(prepared.title)}.mp4"
    out_path = cfg.output_dir / out_name
    # Marca, por escena, si su fondo es un videoclip (para que el ensamblaje
    # lo trate como video en vez de aplicarle el zoom de fotos).
    media_is_video = [bool(getattr(im, "is_video", False)) for im in prepared.images]
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
        music_path=music_file,
        music_volume=music_volume,
        resolution=(video_w, video_h),
        media_is_video=media_is_video,
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
