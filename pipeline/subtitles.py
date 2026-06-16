"""
Paso 5 del pipeline: crear los SUBTITULOS sincronizados (estilo viral).

A partir de los tiempos de cada palabra (que nos dio Edge TTS), generamos un
archivo .ass con subtitulos que aparecen en grupos cortos de palabras,
grandes y centrados, como en TikTok/Reels. FFmpeg los "quema" sobre el video.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .voice import WordTiming

# Estilos de subtitulos disponibles (color primario, color de borde)
SUBTITLE_STYLES = {
    "blanco":   {"primary": "&H00FFFFFF", "outline": "&H00000000"},
    "amarillo": {"primary": "&H0000F7FF", "outline": "&H00000000"},
    "verde":    {"primary": "&H0000FF00", "outline": "&H00000000"},
    "rojo":     {"primary": "&H000000FF", "outline": "&H00000000"},
}


@dataclass
class SubtitleStyle:
    name: str = "amarillo"
    font: str = "Arial Black"
    font_size: int = 54
    position: str = "center"   # top | center | bottom
    words_per_group: int = 3


def _fmt_time(seconds: float) -> str:
    """Convierte segundos a formato ASS  H:MM:SS.cc"""
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs == 100:  # redondeo
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").strip()


def _alignment(position: str) -> int:
    # Numpad alignment de ASS: 2=abajo, 5=centro, 8=arriba (centrado horizontal)
    return {"top": 8, "center": 5, "bottom": 2}.get(position, 5)


def _group_words(words: list[WordTiming], per_group: int) -> list[tuple[float, float, str]]:
    groups: list[tuple[float, float, str]] = []
    for i in range(0, len(words), per_group):
        chunk = words[i : i + per_group]
        if not chunk:
            continue
        start = chunk[0].start
        end = chunk[-1].end
        text = " ".join(w.word for w in chunk).upper()
        groups.append((start, end, text))
    # Evitar solapes y huecos: el final de un grupo es el inicio del siguiente
    for i in range(len(groups) - 1):
        s, e, t = groups[i]
        next_start = groups[i + 1][0]
        if e < next_start:
            groups[i] = (s, next_start, t)
    return groups


def build_ass_subtitles(
    words: list[WordTiming],
    out_path: Path,
    style: SubtitleStyle | None = None,
    video_w: int = 1080,
    video_h: int = 1920,
) -> Path:
    """Genera el archivo .ass de subtitulos y devuelve su ruta."""
    style = style or SubtitleStyle()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    colors = SUBTITLE_STYLES.get(style.name, SUBTITLE_STYLES["amarillo"])
    align = _alignment(style.position)

    # Margen vertical segun posicion
    margin_v = {"top": 220, "center": 0, "bottom": 320}.get(style.position, 0)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_w}
PlayResY: {video_h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Viral,{style.font},{style.font_size},{colors['primary']},&H000000FF,{colors['outline']},&H64000000,-1,0,0,0,100,100,0,0,1,4,2,{align},80,80,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]
    for start, end, text in _group_words(words, style.words_per_group):
        text = _escape(text)
        # \fad = fundido de entrada/salida; pequeno "pop" visual
        dialogue = (
            f"Dialogue: 0,{_fmt_time(start)},{_fmt_time(end)},Viral,,0,0,0,,"
            f"{{\\fad(60,60)}}{text}"
        )
        lines.append(dialogue)

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
