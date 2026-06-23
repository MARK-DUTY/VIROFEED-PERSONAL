"""
Lector de YouTube (Opcion 3 del programa).

Saca el TEXTO de un video de YouTube (subtitulos + titulo + descripcion) y lo
entrega como un `Article`, EXACTAMENTE igual que `article.py` hace con una
noticia. Asi el resto del programa (guion, voz, imagenes, video) funciona sin
ningun cambio: solo cambiamos de donde sale el texto.

IMPORTANTE: este lector usa SOLO `requests` (que ya viene instalado). No hace
falta instalar ninguna libreria nueva, asi el modo YouTube funciona sin que
tengas que ejecutar comandos tecnicos.
"""
from __future__ import annotations

import html as _html
import json
import random
import re
import time

import requests

from .article import Article

# Varios "User-Agent" (navegadores) para rotar y parecer mas humano. Asi es
# menos probable que YouTube nos confunda con un robot y nos bloquee.
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

# Cabecera base para que YouTube nos responda como si fueramos un navegador normal.
_HEADERS = {
    "User-Agent": _USER_AGENTS[0],
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    # Cookies de consentimiento: saltan la pantalla de "aceptar cookies" de Google
    # (CONSENT) y el aviso de privacidad (SOCS). Reducen el riesgo de bloqueo.
    "Cookie": "CONSENT=YES+cb.20210328-17-p0.en+FX+999; SOCS=CAISNQgDEitib3FfaWRlbnRpdHlmcm9udGVuZHVpc2VydmVyXzIwMjQwMTIzLjA2X3AwGgJlcyADGgYIgL2vrwY",
}


class YouTubeBlockedError(ValueError):
    """YouTube bloqueo temporalmente la peticion (429 / pantalla 'sorry')."""


def _looks_blocked(resp: requests.Response) -> bool:
    """Detecta si Google nos mando a su pantalla de 'demuestra que eres humano'."""
    final_url = (resp.url or "").lower()
    if resp.status_code == 429:
        return True
    if "/sorry/" in final_url or "consent.google" in final_url or "consent.youtube" in final_url:
        return True
    return False


def _http_get(url: str, timeout: int = 25, max_retries: int = 3) -> requests.Response:
    """
    Descarga una URL con reintentos y deteccion del bloqueo de YouTube.

    Si Google nos bloquea (429 o pantalla 'sorry'), espera un poco y reintenta
    con otro navegador. Si tras los reintentos sigue bloqueado, lanza un mensaje
    claro en espanol para el usuario.
    """
    last_error: Exception | None = None
    for attempt in range(max_retries):
        headers = dict(_HEADERS)
        # Rotamos el navegador en cada intento
        headers["User-Agent"] = _USER_AGENTS[attempt % len(_USER_AGENTS)]
        try:
            resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1) + random.uniform(0, 1))
            continue

        if _looks_blocked(resp):
            last_error = YouTubeBlockedError("bloqueo temporal de YouTube")
            # Espera creciente (2s, 4s, 6s...) antes de reintentar
            if attempt < max_retries - 1:
                time.sleep(2.0 * (attempt + 1) + random.uniform(0, 1))
            continue

        if resp.status_code >= 400:
            last_error = ValueError(f"{resp.status_code} al abrir YouTube")
            time.sleep(1.0 + random.uniform(0, 0.5))
            continue

        return resp  # todo bien

    # Si llegamos aqui, no se pudo. Mensaje claro segun el motivo.
    if isinstance(last_error, YouTubeBlockedError):
        raise YouTubeBlockedError(
            "YouTube bloqueo la peticion por ahora (te pidio demostrar que no "
            "eres un robot). Esto pasa cuando se hacen varias peticiones seguidas. "
            "Soluciones: 1) espera de 15 a 30 minutos y vuelve a intentar, "
            "2) usa el modo 'Noticia (URL)' mientras tanto, o "
            "3) prueba con otro video."
        )
    raise ValueError(
        f"No pude abrir el video de YouTube. Revisa el enlace o tu internet. "
        f"Detalle: {last_error}"
    )


def _clean(text: str) -> str:
    """Limpia el texto: quita [Music], [Applause], saltos de linea y espacios dobles."""
    text = _html.unescape(text or "")
    text = re.sub(r"\[[^\]]{0,40}\]", " ", text)   # quitar [Music], [Applause], etc.
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _video_id(url: str) -> str:
    """Saca el ID del video (11 caracteres) de cualquier forma de enlace de YouTube."""
    url = (url or "").strip()
    # youtu.be/VIDEOID
    m = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)
    # youtube.com/watch?v=VIDEOID
    m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)
    # youtube.com/shorts/VIDEOID  |  /embed/VIDEOID  |  /live/VIDEOID  |  /v/VIDEOID
    m = re.search(r"/(?:shorts|embed|live|v)/([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)
    # por si pegan solo el ID
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url
    raise ValueError(
        "No reconoci el enlace de YouTube. Pega el enlace completo del video, "
        "por ejemplo: https://www.youtube.com/watch?v=XXXXXXXXXXX"
    )


def _find_json_object(text: str, marker: str) -> dict | None:
    """
    Busca `marker` dentro del HTML y extrae el objeto JSON {...} que viene
    justo despues, contando llaves para tomar el objeto completo (sin libreria).
    """
    idx = text.find(marker)
    if idx == -1:
        return None
    start = text.find("{", idx)
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    blob = text[start : i + 1]
                    try:
                        return json.loads(blob)
                    except json.JSONDecodeError:
                        return None
    return None


def _pick_caption_track(player: dict) -> dict | None:
    """Elige la mejor pista de subtitulos: preferimos espanol y subtitulos manuales."""
    try:
        tracks = player["captions"]["playerCaptionsTracklistRenderer"]["captionTracks"]
    except (KeyError, TypeError):
        return None
    if not tracks:
        return None

    def score(t: dict) -> tuple:
        lang = (t.get("languageCode") or "").lower()
        is_spanish = lang.startswith("es")
        is_manual = t.get("kind") != "asr"   # "asr" = generado automaticamente
        return (is_spanish, is_manual)

    return sorted(tracks, key=score, reverse=True)[0]


def _fetch_transcript(track: dict) -> str:
    """Descarga y arma el texto de los subtitulos de la pista elegida."""
    base = track.get("baseUrl")
    if not base:
        return ""

    # Primero intentamos el formato json3 (facil de parsear).
    sep = "&" if "?" in base else "?"
    try:
        resp = requests.get(base + sep + "fmt=json3", headers=_HEADERS, timeout=25)
        resp.raise_for_status()
        data = resp.json()
        parts: list[str] = []
        for event in data.get("events", []):
            for seg in event.get("segs", []) or []:
                piece = seg.get("utf8")
                if piece:
                    parts.append(piece)
        text = _clean("".join(parts))
        if text:
            return text
    except Exception:
        pass

    # Respaldo: el formato XML clasico con etiquetas <text>.
    try:
        resp = requests.get(base, headers=_HEADERS, timeout=25)
        resp.raise_for_status()
        chunks = re.findall(r"<text[^>]*>(.*?)</text>", resp.text, re.DOTALL)
        clean_chunks = [re.sub(r"<[^>]+>", "", c) for c in chunks]
        return _clean(" ".join(clean_chunks))
    except Exception:
        return ""


def extract_youtube(url: str, timeout: int = 25) -> Article:
    """
    Lee un video de YouTube y devuelve un Article (url + titulo + texto).

    El texto sale de los SUBTITULOS del video. Si el video no tiene subtitulos,
    usamos su DESCRIPCION como respaldo. Lanza ValueError con un mensaje claro
    si no hay suficiente texto para crear un guion.
    """
    vid = _video_id(url)
    watch_url = f"https://www.youtube.com/watch?v={vid}&hl=es&bpctr=9999999999&has_verified=1"

    # Descarga robusta: reintenta y detecta el bloqueo de YouTube (429 / sorry).
    page = _http_get(watch_url, timeout=timeout).text

    title = ""
    description = ""
    transcript = ""

    player = _find_json_object(page, "ytInitialPlayerResponse")
    if player:
        details = player.get("videoDetails") or {}
        title = (details.get("title") or "").strip()
        description = (details.get("shortDescription") or "").strip()
        track = _pick_caption_track(player)
        if track:
            transcript = _fetch_transcript(track)

    # Respaldo del titulo: la etiqueta <title> de la pagina
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", page, re.IGNORECASE | re.DOTALL)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).replace(" - YouTube", "").strip()
    title = _clean(title) or "Video de YouTube"

    # Texto base: preferimos los subtitulos; si no hay, la descripcion del video.
    text = _clean(transcript or description)

    article = Article(url=url, title=title, text=text)
    if not article.is_usable:
        raise ValueError(
            "Pude abrir el video, pero no encontre subtitulos ni una descripcion "
            "con suficiente texto. Prueba con un video que tenga subtitulos (la "
            "mayoria los tienen) o cuya descripcion sea mas larga."
        )
    return article


def extract_youtubes(urls: list[str], timeout: int = 25) -> Article:
    """
    Lee VARIOS videos de YouTube (del mismo tema) y combina sus subtitulos en un
    solo Article. Asi hay material de sobra para videos largos.

    - Lee cada video; si alguno falla, lo salta (no rompe todo el proceso).
    - El titulo es el del primer video que se pudo leer.
    - El texto es la union de todos.

    Lanza ValueError solo si NINGUNO de los videos se pudo leer.
    """
    urls = [u.strip() for u in (urls or []) if u and u.strip()]
    if not urls:
        raise ValueError("No diste ningun enlace de YouTube.")
    if len(urls) == 1:
        return extract_youtube(urls[0], timeout=timeout)

    title = ""
    parts: list[str] = []
    errors: list[str] = []
    blocked = False
    for u in urls:
        try:
            art = extract_youtube(u, timeout=timeout)
            if not title:
                title = art.title
            parts.append(art.text)
        except YouTubeBlockedError as exc:
            blocked = True
            errors.append(f"- {u}: {exc}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"- {u}: {exc}")

    if not parts:
        if blocked:
            raise YouTubeBlockedError(
                "YouTube bloqueo las peticiones por ahora (te pidio demostrar que "
                "no eres un robot). Espera de 15 a 30 minutos y reintenta, usa el "
                "modo 'Noticia (URL)' mientras tanto, o prueba con otros videos."
            )
        raise ValueError(
            "No pude leer NINGUNO de los videos que pegaste. Revisa que tengan "
            "subtitulos. Detalle:\n" + "\n".join(errors)
        )

    combined = "\n\n".join(parts)
    article = Article(url=urls[0], title=title or "Video de YouTube", text=_clean(combined))
    print(f"[youtube] {len(parts)} de {len(urls)} videos combinados")
    return article
