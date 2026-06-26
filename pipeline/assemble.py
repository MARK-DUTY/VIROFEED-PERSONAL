"""
Paso 6 del pipeline: ENSAMBLAR el video final con FFmpeg.

Toma las imagenes + la voz + los subtitulos y produce un .mp4 vertical
(1080x1920, formato Reels/TikTok/Shorts) con:
  - efecto de zoom suave (Ken Burns) en cada imagen
  - la voz como audio
  - los subtitulos "quemados" encima
  - (opcional) un logo de marca
  - (opcional) un avatar hablando superpuesto en una esquina

No depende de ninguna GPU: FFmpeg trabaja con el procesador, perfecto para
tu PC.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

VIDEO_W = 1080
VIDEO_H = 1920
FPS = 30

# Formatos disponibles (relacion de aspecto -> tamano en pixeles).
#   "9:16" -> vertical (Reels / TikTok / Shorts)
#   "16:9" -> horizontal (YouTube clasico)
#   "1:1"  -> cuadrado (feed de Instagram / Facebook)
ASPECT_RESOLUTIONS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}


def resolution_for(aspect: str | None) -> tuple[int, int]:
    """Devuelve (ancho, alto) en pixeles para el formato pedido (por defecto 9:16)."""
    return ASPECT_RESOLUTIONS.get((aspect or "9:16").strip(), (VIDEO_W, VIDEO_H))


@dataclass
class AssembleResult:
    video_path: Path
    duration: float


def find_ffmpeg() -> str:
    """Localiza el ejecutable de ffmpeg. Lanza error claro si no esta."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    # Rutas comunes en Windows si el usuario lo descomprimio junto al programa
    for candidate in ("ffmpeg.exe", "bin/ffmpeg.exe", "ffmpeg/bin/ffmpeg.exe"):
        p = Path(candidate)
        if p.exists():
            return str(p.resolve())
    raise ValueError(
        "No encontre FFmpeg. Instalalo y asegurate de que este en el PATH. "
        "En Windows puedes usar:  winget install Gyan.FFmpeg"
    )


def find_ffprobe() -> str | None:
    return shutil.which("ffprobe")


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-1200:]
        raise RuntimeError(f"FFmpeg fallo:\n{tail}")


def probe_duration(media_path: Path) -> float | None:
    """Devuelve la duracion en segundos de un audio/video, o None si no se puede."""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return None
    try:
        out = subprocess.check_output(
            [
                ffprobe, "-v", "quiet", "-print_format", "json",
                "-show_format", str(media_path),
            ],
            text=True,
        )
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return None


def _make_clip(
    ffmpeg: str,
    image: Path,
    duration: float,
    out_clip: Path,
    zoom_in: bool,
    video_w: int = VIDEO_W,
    video_h: int = VIDEO_H,
) -> None:
    """Crea un clip de video a partir de una imagen, con zoom suave."""
    frames = max(1, int(round(duration * FPS)))

    # Ken Burns CONTINUO (no se congela nunca).
    #
    # Antes el zoom subia poquito a poquito hasta un tope (1.18) y se quedaba
    # ahi. En videos cortos no se notaba porque cada imagen duraba poco; pero en
    # videos largos, donde cada imagen aparece mucho tiempo en pantalla, llegaba
    # al tope y se quedaba CONGELADA el resto del tiempo.
    #
    # Ahora usamos un vaiven suave (onda de coseno) ligado al numero de cuadro
    # (la variable "on" de FFmpeg). La imagen se acerca, y al llegar al maximo
    # regresa suavemente al inicio y vuelve a empezar: nunca se detiene, sin
    # importar cuanto dure la imagen ni cuanto dure el video.
    cycle_frames = max(1, int(round(8.0 * FPS)))  # un ciclo (acercar+alejar) ~8 s
    zoom_min = 1.0
    zoom_max = 1.18
    amp = zoom_max - zoom_min
    # "osc" va suavemente de 0 -> 1 -> 0 a lo largo de cada ciclo
    osc = f"(1-cos(2*PI*on/{cycle_frames}))/2"
    if zoom_in:
        # arranca normal, se acerca y regresa
        z_expr = f"{zoom_min:.3f}+{amp:.3f}*{osc}"
    else:
        # arranca acercada, se aleja y regresa (alterna el ritmo entre imagenes)
        z_expr = f"{zoom_max:.3f}-{amp:.3f}*{osc}"

    # Mantenemos el zoom CENTRADO en la imagen (se ve mas natural que desde la esquina).
    x_expr = "iw/2-(iw/zoom/2)"
    y_expr = "ih/2-(ih/zoom/2)"

    # Escalamos grande primero para que el zoom no pixele, recortamos al formato
    # elegido, aplicamos zoompan y fijamos tamano final.
    vf = (
        f"scale={video_w*2}:{video_h*2}:force_original_aspect_ratio=increase,"
        f"crop={video_w*2}:{video_h*2},"
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':"
        f"d={frames}:s={video_w}x{video_h}:fps={FPS},"
        f"setsar=1,format=yuv420p"
    )
    cmd = [
        ffmpeg, "-y", "-loop", "1", "-i", str(image),
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-r", str(FPS),
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        str(out_clip),
    ]
    _run(cmd)


def build_video(
    images: list[Path],
    audio_path: Path,
    subtitles_path: Path | None,
    out_path: Path,
    work_dir: Path,
    logo_path: Path | None = None,
    avatar_video: Path | None = None,
    target_duration: float | None = None,
    image_durations: list[float] | None = None,
    music_path: Path | None = None,
    music_volume: float = 0.15,
    resolution: tuple[int, int] = (VIDEO_W, VIDEO_H),
) -> AssembleResult:
    """
    Ensambla el video final y lo guarda en out_path.

    images          : lista de imagenes de fondo (en orden)
    audio_path      : la voz (mp3)
    subtitles_path  : archivo .ass (o None para sin subtitulos)
    logo_path       : png con transparencia para marca de agua (opcional)
    avatar_video    : video del avatar para superponer en esquina (opcional)
    image_durations : duracion (segundos) de cada imagen, para sincronizar cada
                      imagen con su escena. Si es None, se reparte por igual.
    music_path      : musica de fondo opcional (la voz manda; la musica va baja).
    music_volume    : volumen de la musica (0.0 a 1.0). La voz se mantiene a 1.0.
    resolution      : (ancho, alto) del video final. Por defecto 1080x1920 (9:16).
                      Tambien admite 1920x1080 (16:9) y 1080x1080 (1:1).
    """
    ffmpeg = find_ffmpeg()
    video_w, video_h = resolution
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not images:
        raise ValueError("No hay imagenes para armar el video.")

    # Duracion real del audio (mas fiable que el calculo por palabras)
    duration = probe_duration(audio_path) or target_duration or 45.0
    duration = max(5.0, duration + 0.4)  # pequena cola al final

    n = len(images)

    # Duracion de cada imagen: la indicada (sincronizada con escenas) o pareja
    if image_durations and len(image_durations) == n:
        total = sum(image_durations) or duration
        # Reescalar para que sumen exactamente la duracion del audio
        factor = duration / total
        per_image_list = [max(1.2, d * factor) for d in image_durations]
    else:
        per_image_list = [duration / n] * n

    # 1) Crear un clip por imagen
    clips_dir = work_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    clip_paths: list[Path] = []
    for i, img in enumerate(images):
        clip = clips_dir / f"clip_{i:02d}.mp4"
        _make_clip(
            ffmpeg, Path(img), per_image_list[i], clip,
            zoom_in=(i % 2 == 0), video_w=video_w, video_h=video_h,
        )
        clip_paths.append(clip)

    # 2) Concatenar los clips
    concat_list = work_dir / "concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{c.resolve().as_posix()}'" for c in clip_paths),
        encoding="utf-8",
    )
    silent_video = work_dir / "slideshow.mp4"
    _run([
        ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c", "copy", str(silent_video),
    ])

    # 3) Componer pista final: video + audio + subtitulos + logo + avatar
    # Trabajamos con cwd = work_dir para evitar problemas de rutas en Windows
    # (sobre todo con el filtro de subtitulos y los dos puntos de "C:").
    if subtitles_path:
        subs_local = work_dir / "subtitles.ass"
        if Path(subtitles_path).resolve() != subs_local.resolve():
            shutil.copy(Path(subtitles_path), subs_local)

    inputs = ["-i", str(silent_video.resolve()), "-i", str(Path(audio_path).resolve())]
    next_idx = 2
    logo_idx = avatar_idx = None
    if logo_path and Path(logo_path).exists():
        inputs += ["-i", str(Path(logo_path).resolve())]
        logo_idx = next_idx
        next_idx += 1
    if avatar_video and Path(avatar_video).exists():
        inputs += ["-i", str(Path(avatar_video).resolve())]
        avatar_idx = next_idx
        next_idx += 1
    # Musica de fondo (opcional). -stream_loop -1 hace que se repita si es mas
    # corta que el video; luego amix con duration=first la corta al terminar la voz.
    music_idx = None
    if music_path and Path(music_path).exists():
        inputs += ["-stream_loop", "-1", "-i", str(Path(music_path).resolve())]
        music_idx = next_idx
        next_idx += 1

    # Construimos la cadena de filtros paso a paso
    filters = []
    last = "0:v"

    # Tamanos y margenes RELATIVOS al formato (asi se ven bien en 9:16, 16:9 y 1:1)
    margin_x = max(20, int(video_w * 0.045))
    margin_y = max(20, int(video_h * 0.045))
    avatar_w = max(220, int(video_w * 0.22))
    logo_w = max(110, int(video_w * 0.18))

    if avatar_idx is not None:
        # Avatar como cabeza parlante pequena en la esquina superior derecha
        filters.append(
            f"[{avatar_idx}:v]scale={avatar_w}:-1,setsar=1[av]"
        )
        filters.append(f"[{last}][av]overlay=W-w-{margin_x}:{margin_y}[vav]")
        last = "vav"

    if logo_idx is not None:
        filters.append(f"[{logo_idx}:v]scale={logo_w}:-1[lg]")
        filters.append(f"[{last}][lg]overlay=W-w-{margin_x}:H-h-{margin_y}[vlogo]")
        last = "vlogo"

    if subtitles_path:
        filters.append(f"[{last}]ass=subtitles.ass[vsub]")
        last = "vsub"

    # Mapa del video: con corchetes solo si hubo filtros de video
    video_map = f"[{last}]" if filters else "0:v"

    # --- Audio: voz sola, o voz + musica de fondo mezclada ---
    audio_map = "1:a"
    if music_idx is not None:
        vol = max(0.0, min(1.0, float(music_volume)))
        fade_start = max(0.1, duration - 2.0)
        # Igualamos frecuencia y canales de ambas pistas (si no, amix falla).
        # La voz se mantiene a tope; la musica va baja, con fade out al final.
        filters.append(
            f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo[voz]"
        )
        filters.append(
            f"[{music_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
            f"volume={vol:.3f},afade=t=out:st={fade_start:.2f}:d=2[bgm]"
        )
        filters.append(
            "[voz][bgm]amix=inputs=2:duration=first:dropout_transition=3:normalize=0[aout]"
        )
        audio_map = "[aout]"

    cmd = [ffmpeg, "-y", *inputs]
    if filters:
        cmd += ["-filter_complex", ";".join(filters)]
    cmd += ["-map", video_map, "-map", audio_map]
    cmd += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-shortest", "-movflags", "+faststart",
        str(out_path.resolve()),
    ]
    _run(cmd, cwd=work_dir)

    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError("El video final no se genero correctamente.")

    return AssembleResult(video_path=out_path, duration=duration)
