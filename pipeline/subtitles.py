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
    font_size: int = 88          # bien grandes, estilo viral (era 54, luego 64)
    position: str = "center"     # top | center | bottom
    words_per_group: int = 3
    # Cuanto ADELANTAR los subtitulos respecto a la voz, en segundos.
    # Edge TTS nos da el tiempo de cada palabra, pero al ver el video los
    # subtitulos se pueden sentir "atrasados". Restamos este valor a los tiempos
    # para que el texto aparezca justo cuando se empieza a decir (o un pelin antes).
    lead_sec: float = 0.25
    # Cuanto BAJAR los subtitulos respecto a su posicion base, en pixeles.
    # El video mide 1920px de alto; ~75px equivale aprox. a 1 cm en pantalla.
    # 525px equivale aprox. a 7 cm mas abajo del centro (4 cm + 3 cm pedidos).
    drop_px: int = 525


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


def _base_y(position: str, video_h: int) -> int:
    """Posicion vertical BASE (centro del texto) segun la posicion elegida."""
    fractions = {"top": 0.20, "center": 0.50, "bottom": 0.80}
    return int(video_h * fractions.get(position, 0.50))


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

    # Posicion vertical EXACTA (centro del bloque de texto), en pixeles.
    # Partimos de la posicion base y la bajamos 'drop_px'. Como drop_px esta
    # pensado para video vertical (1920px de alto), lo escalamos en proporcion
    # a la altura real para que en 16:9 (1080px) o 1:1 (1080px) el subtitulo
    # quede a la MISMA altura relativa y no se salga de la pantalla.
    center_x = video_w // 2
    drop = int(max(0, style.drop_px) * (video_h / 1920))
    target_y = _base_y(style.position, video_h) + drop
    # Evitamos que se salga de la pantalla (dejamos margen arriba y abajo).
    target_y = max(int(video_h * 0.12), min(target_y, int(video_h * 0.90)))

    # Usamos alineacion 5 (centrado) porque colocamos el texto con \pos de forma
    # exacta; asi el movimiento hacia abajo es predecible en cualquier reproductor.
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_w}
PlayResY: {video_h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Viral,{style.font},{style.font_size},{colors['primary']},&H000000FF,{colors['outline']},&H64000000,-1,0,0,0,100,100,0,0,1,4,2,5,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]
    # Adelantamos los subtitulos restando 'lead_sec' a sus tiempos, para que no
    # se sientan atrasados respecto a la voz. Nunca dejamos tiempos negativos.
    lead = max(0.0, float(getattr(style, "lead_sec", 0.0)))
    for start, end, text in _group_words(words, style.words_per_group):
        start = max(0.0, start - lead)
        end = max(start + 0.1, end - lead)
        text = _escape(text)
        # \pos coloca el texto en la posicion exacta; \fad da el fundido de entrada/salida
        dialogue = (
            f"Dialogue: 0,{_fmt_time(start)},{_fmt_time(end)},Viral,,0,0,0,,"
            f"{{\\pos({center_x},{target_y})\\fad(60,60)}}{text}"
        )
        lines.append(dialogue)

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path



def build_subtitles_from_text(
    text: str,
    duration: float,
    out_path: Path,
    style: SubtitleStyle | None = None,
    video_w: int = 1080,
    video_h: int = 1920,
) -> Path | None:
    """
    Plan B de subtitulos: cuando Edge TTS NO devuelve los tiempos por palabra,
    repartimos el texto de forma pareja a lo largo de la duracion del audio.

    No queda tan perfectamente sincronizado como con los tiempos reales, pero
    garantiza que el video SIEMPRE tenga subtitulos.
    """
    words_raw = (text or "").split()
    if not words_raw or duration <= 0:
        return None

    per = duration / len(words_raw)
    timings: list[WordTiming] = []
    t = 0.0
    for w in words_raw:
        timings.append(WordTiming(word=w, start=round(t, 3), end=round(t + per, 3)))
        t += per

    return build_ass_subtitles(
        timings, out_path, style=style, video_w=video_w, video_h=video_h
    )
