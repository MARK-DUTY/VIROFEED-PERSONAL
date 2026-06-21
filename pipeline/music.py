"""
Musica de fondo AUTOMATICA y 100% LIBRE DE DERECHOS.

En vez de descargar canciones (que podrian tener copyright), aqui GENERAMOS la
musica con FFmpeg directamente en tu PC, a partir de tonos (acordes) creados con
matematicas. Como no usa ninguna grabacion ni sample de nadie, es IMPOSIBLE que
tenga problemas de derechos de autor: es musica original generada al momento.

Crea varias pistas instrumentales suaves (tipo ambiente/cinematico) que quedan
muy bien de fondo debajo de la voz. Se generan una sola vez y se guardan en
assets/music/. Despues solo se eligen al azar.

DISENO A PRUEBA DE FALLOS (importante):
  - Solo se usan filtros de FFmpeg que existen en TODAS las versiones (nada de
    'tremolo' ni 'alimiter', que en algunas instalaciones de Windows fallan).
  - Cada pista se VALIDA despues de crearla (que exista y tenga audio real).
    Si salio danada, se borra y se vuelve a intentar.
  - Hay un PLAN DE RESPALDO en cascada: si la version "bonita" falla, se intenta
    una mas simple, y si esa tambien falla, una minima que practicamente siempre
    funciona. Asi NUNCA te quedas sin musica automatica.
"""
from __future__ import annotations

import random
from pathlib import Path

from .assemble import _run, find_ffmpeg, probe_duration
from .config import settings

MUSIC_DIR = settings.assets_dir / "music"

# Largo (segundos) de cada acorde en la version "bonita".
_CHORD_LEN = 5.0

# Cada "mood" (ambiente) es una progresion de acordes. Cada acorde son 3 notas
# (frecuencias en Hz). Estan elegidas para sonar agradables de fondo.
_MOODS: dict[str, list[list[float]]] = {
    # Inspirador / motivacional (mayor, alegre)
    "inspirador": [
        [261.63, 329.63, 392.00],   # Do mayor
        [196.00, 246.94, 293.66],   # Sol mayor
        [220.00, 261.63, 329.63],   # La menor
        [174.61, 220.00, 261.63],   # Fa mayor
    ],
    # Emotivo / sentimental (empieza menor)
    "emotivo": [
        [220.00, 261.63, 329.63],   # La menor
        [174.61, 220.00, 261.63],   # Fa mayor
        [261.63, 329.63, 392.00],   # Do mayor
        [196.00, 246.94, 293.66],   # Sol mayor
    ],
    # Epico / cinematico (menor, mas dramatico)
    "epico": [
        [146.83, 174.61, 220.00],   # Re menor
        [233.08, 293.66, 349.23],   # Si bemol mayor
        [174.61, 220.00, 261.63],   # Fa mayor
        [130.81, 164.81, 196.00],   # Do mayor (grave)
    ],
    # Tranquilo / suave (relajado)
    "tranquilo": [
        [261.63, 329.63, 392.00],   # Do
        [293.66, 349.23, 440.00],   # Re menor-ish
        [220.00, 261.63, 329.63],   # La menor
        [196.00, 246.94, 293.66],   # Sol
    ],
}


# --------------------------------------------------------------------------
#  Validacion: una pista es valida si existe, pesa algo y tiene audio real.
# --------------------------------------------------------------------------
def _is_valid_track(path: Path, min_seconds: float = 3.0) -> bool:
    """True si el archivo de musica existe y contiene audio de verdad."""
    try:
        if not path.exists() or path.stat().st_size < 2048:
            return False
    except OSError:
        return False
    dur = probe_duration(path)
    if dur is None:
        # No hay ffprobe para medir: nos fiamos del tamano (un mp3 real pesa mas).
        try:
            return path.stat().st_size > 8192
        except OSError:
            return False
    return dur >= min_seconds


# --------------------------------------------------------------------------
#  Constructores de filtro (3 niveles, del mas bonito al mas a prueba de fallos)
# --------------------------------------------------------------------------
def _filter_chords(chords: list[list[float]], chord_len: float) -> tuple[str, float]:
    """Nivel 1 (bonito): progresion de acordes con entradas/salidas suaves."""
    parts: list[str] = []
    labels: list[str] = []
    idx = 0
    for ci, chord in enumerate(chords):
        start_s = ci * chord_len
        start_ms = int(start_s * 1000)
        for freq in chord:
            src = f"n{idx}"
            out = f"c{idx}"
            parts.append(
                f"sine=frequency={freq:.2f}:sample_rate=44100:duration={chord_len:.2f}[{src}]"
            )
            # Subimos el volumen de CADA nota a un nivel alto (la pista queda
            # cerca de escala completa). El volumen final de fondo se controla
            # despues, al mezclar con la voz. Antes estaba en 0.16 y, al
            # multiplicarlo otra vez en la mezcla, la musica quedaba casi muda.
            parts.append(
                f"[{src}]volume=0.30,adelay={start_ms}:all=1,"
                f"afade=t=in:st={start_s:.2f}:d=0.40,"
                f"afade=t=out:st={start_s + chord_len - 0.50:.2f}:d=0.50[{out}]"
            )
            labels.append(f"[{out}]")
            idx += 1

    total = len(chords) * chord_len
    mix = (
        "".join(labels)
        + f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
        + "lowpass=f=3200[out]"
    )
    parts.append(mix)
    return ";".join(parts), total


def _filter_simple(freqs: list[float], total: float) -> tuple[str, float]:
    """Nivel 2 (respaldo): un solo acorde sostenido toda la pista."""
    parts: list[str] = []
    labels: list[str] = []
    for i, freq in enumerate(freqs):
        parts.append(
            f"sine=frequency={freq:.2f}:sample_rate=44100:duration={total:.2f}[s{i}]"
        )
        parts.append(f"[s{i}]volume=0.30[v{i}]")
        labels.append(f"[v{i}]")
    parts.append(
        "".join(labels)
        + f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
        + f"afade=t=in:st=0:d=1.0,afade=t=out:st={total - 1.5:.2f}:d=1.5,"
        + "lowpass=f=3000[out]"
    )
    return ";".join(parts), total


def _filter_minimal(freq: float, total: float) -> tuple[str, float]:
    """Nivel 3 (minimo, casi infalible): una sola nota suave con fundidos."""
    filt = (
        f"sine=frequency={freq:.2f}:sample_rate=44100:duration={total:.2f},"
        f"volume=0.85,afade=t=in:st=0:d=1.0,afade=t=out:st={total - 1.5:.2f}:d=1.5,"
        f"lowpass=f=2800[out]"
    )
    return filt, total


def generate_track(
    name: str, chords: list[list[float]], out_path: Path, chord_len: float = _CHORD_LEN
) -> bool:
    """
    Genera UNA pista de musica y la guarda en out_path (.mp3).

    Intenta primero la version bonita; si FFmpeg la rechaza o el archivo sale
    danado, baja a una version mas simple, y luego a una minima. Devuelve True
    en cuanto consigue una pista VALIDA.
    """
    try:
        ffmpeg = find_ffmpeg()
    except Exception as exc:  # noqa: BLE001
        print(f"[musica] no encontre FFmpeg: {exc}")
        return False

    total_simple = max(12.0, len(chords) * chord_len)
    base_freqs = chords[0] if chords else [261.63, 329.63, 392.00]

    attempts = [
        ("bonito", lambda: _filter_chords(chords, chord_len)),
        ("simple", lambda: _filter_simple(base_freqs, total_simple)),
        ("minimo", lambda: _filter_minimal(base_freqs[0], total_simple)),
    ]

    for label, build in attempts:
        try:
            filt, total = build()
        except Exception:  # noqa: BLE001
            continue
        cmd = [
            ffmpeg, "-y",
            "-filter_complex", filt,
            "-map", "[out]",
            "-t", f"{total:.2f}",
            "-ar", "44100", "-ac", "2",
            "-c:a", "libmp3lame", "-q:a", "4",
            str(out_path.resolve()),
        ]
        try:
            _run(cmd)
        except Exception as exc:  # noqa: BLE001
            print(f"[musica] intento '{label}' fallo para '{name}': {exc}")
            continue

        if _is_valid_track(out_path):
            if label != "bonito":
                print(f"[musica] '{name}': generada con modo de respaldo '{label}'.")
            return True

        # Salio un archivo invalido: lo borramos y probamos algo mas simple.
        print(f"[musica] '{name}': el intento '{label}' salio danado, probando mas simple...")
        try:
            out_path.unlink()
        except OSError:
            pass

    print(f"[musica] NO se pudo generar la pista '{name}' por ningun metodo.")
    return False


def ensure_default_music() -> list[Path]:
    """
    Se asegura de que existan pistas automaticas VALIDAS. Revisa las que ya
    estan; si alguna falta o esta danada, la (re)genera. Devuelve la lista de
    pistas validas disponibles.
    """
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    valid: list[Path] = []

    # Limpieza: las pistas viejas pudieron quedar mudas/muy bajitas con versiones
    # anteriores. Borramos los formatos antiguos ('auto_*.mp3' y 'bgm_*.mp3') para
    # regenerarlas con el volumen nuevo (audible). Las nuevas usan 'bgm2_*.mp3'.
    for pattern in ("auto_*.mp3", "bgm_*.mp3"):
        for old in MUSIC_DIR.glob(pattern):
            try:
                old.unlink()
            except OSError:
                pass

    for name, chords in _MOODS.items():
        dest = MUSIC_DIR / f"bgm2_{name}.mp3"

        if _is_valid_track(dest):
            valid.append(dest)
            continue

        # Falta o esta danada -> (re)generar.
        if dest.exists():
            print(f"[musica] '{dest.name}' estaba danada o vacia; la vuelvo a generar...")
            try:
                dest.unlink()
            except OSError:
                pass
        else:
            print(f"[musica] generando '{dest.name}' (libre de derechos, solo la primera vez)...")

        if generate_track(name, chords, dest) and _is_valid_track(dest):
            valid.append(dest)
            print(f"[musica] lista: {dest.name}")

    if not valid:
        print("[musica] ATENCION: no se pudo dejar ninguna pista automatica lista.")
    return valid


def pick_auto_music(seed: int | None = None) -> Path | None:
    """Devuelve una pista automatica VALIDA al azar (generandolas si hace falta)."""
    tracks = ensure_default_music()
    if not tracks:
        return None
    rng = random.Random(seed) if seed is not None else random
    return rng.choice(tracks)
