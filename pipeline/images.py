"""
Paso 4 del pipeline: conseguir las IMAGENES de fondo del video.

Tres fuentes posibles (se elige con IMAGE_SOURCE en .env o desde la interfaz):
  - "ai"     : genera imagenes con IA (Pollinations.ai) a partir de la
               descripcion de cada escena. GRATIS y sin clave. Maxima concordancia.
  - "stock"  : busca fotos reales en Pexels / Pixabay por palabra clave.
  - "hybrid" : intenta IA y, si falla, usa stock (lo mejor de ambos).

Cada ESCENA del guion produce su propia imagen, para que el video concuerde
con lo que se esta narrando en cada momento.
"""
from __future__ import annotations

import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import requests

from .config import settings
from .script_gen import Scene

PEXELS_SEARCH = "https://api.pexels.com/v1/search"
PIXABAY_SEARCH = "https://pixabay.com/api/"
POLLINATIONS = "https://image.pollinations.ai/prompt/"

_HEADERS = {"User-Agent": "ViroFeedPersonal/1.0"}

# Tamano de generacion IA (vertical 9:16). El ensamblaje luego lo ajusta a 1080x1920.
_AI_W, _AI_H = 768, 1344


@dataclass
class ImageResult:
    path: Path
    source: str       # "ai" | "pexels" | "pixabay"
    query: str        # con que descripcion/keyword se obtuvo


def _download(url: str, dest: Path, timeout: int = 60) -> bool:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout, stream=True)
        resp.raise_for_status()
        ctype = resp.headers.get("Content-Type", "")
        if "image" not in ctype and not str(dest).endswith((".jpg", ".png")):
            # Si no es imagen, descartamos
            return False
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return dest.exists() and dest.stat().st_size > 2048
    except requests.RequestException:
        return False


# --------------------------------------------------------------------------
#  Generacion con IA (Pollinations) - gratis, sin clave
# --------------------------------------------------------------------------
def generate_ai_image(prompt: str, dest: Path, seed: int | None = None) -> bool:
    """Genera una imagen con IA a partir de la descripcion. Devuelve True si ok."""
    clean = prompt.strip()
    if not clean:
        return False
    encoded = urllib.parse.quote(clean, safe="")
    params = {
        "width": _AI_W,
        "height": _AI_H,
        "nologo": "true",
        "model": "flux",
    }
    if seed is not None:
        params["seed"] = seed
    query = urllib.parse.urlencode(params)
    url = f"{POLLINATIONS}{encoded}?{query}"
    return _download(url, dest, timeout=90)


# --------------------------------------------------------------------------
#  Busqueda en stock (Pexels / Pixabay)
# --------------------------------------------------------------------------
def _search_pexels(query: str, want: int = 1) -> list[str]:
    if not settings.pexels_api_key or settings.pexels_api_key.startswith("PEGA_AQUI"):
        return []
    headers = {"Authorization": settings.pexels_api_key}
    params = {"query": query, "per_page": max(1, want * 3), "orientation": "portrait"}
    try:
        resp = requests.get(PEXELS_SEARCH, headers=headers, params=params, timeout=25)
        if resp.status_code != 200:
            return []
        photos = resp.json().get("photos", [])
        urls = []
        for p in photos:
            src = p.get("src", {})
            url = src.get("portrait") or src.get("large2x") or src.get("large") or src.get("original")
            if url:
                urls.append(url)
        return urls
    except requests.RequestException:
        return []


def _search_pixabay(query: str, want: int = 1) -> list[str]:
    if not settings.pixabay_api_key:
        return []
    params = {
        "key": settings.pixabay_api_key,
        "q": query,
        "image_type": "photo",
        "orientation": "vertical",
        "per_page": max(3, want * 3),
        "safesearch": "true",
    }
    try:
        resp = requests.get(PIXABAY_SEARCH, params=params, timeout=25)
        if resp.status_code != 200:
            return []
        hits = resp.json().get("hits", [])
        return [h.get("largeImageURL") for h in hits if h.get("largeImageURL")]
    except requests.RequestException:
        return []


def _download_stock(query: str, dest: Path, used_urls: set[str]) -> str | None:
    """Intenta descargar una foto de stock para la query. Devuelve la fuente o None."""
    candidates = _search_pexels(query) + _search_pixabay(query)
    for url in candidates:
        if url in used_urls:
            continue
        source = "pexels" if "pexels" in url else "pixabay"
        if _download(url, dest):
            used_urls.add(url)
            return source
    return None


# --------------------------------------------------------------------------
#  Funcion principal: una imagen por escena
# --------------------------------------------------------------------------
def fetch_scene_images(
    scenes: list[Scene],
    dest_dir: Path,
    source: str = "hybrid",
    progress=None,
) -> list[ImageResult]:
    """
    Consigue una imagen por cada escena, segun la fuente elegida.

    source: "ai" | "stock" | "hybrid"
    progress: funcion opcional progress(msg, pct) para informar avance.

    Garantiza que el numero de imagenes coincide con el numero de escenas
    (si una falla del todo, reutiliza la ultima imagen valida para no romper).
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    source = (source or "hybrid").lower()

    # Validacion de claves para modos que usan stock
    stock_available = (
        settings.pexels_api_key and not settings.pexels_api_key.startswith("PEGA_AQUI")
    ) or bool(settings.pixabay_api_key)
    if source == "stock" and not stock_available:
        raise ValueError(
            "Elegiste fotos de stock pero falta la clave de Pexels en tu .env."
        )

    results: list[ImageResult] = []
    used_urls: set[str] = set()
    total = len(scenes)

    for i, scene in enumerate(scenes):
        dest = dest_dir / f"img_{i:02d}.jpg"
        got: ImageResult | None = None

        if progress:
            progress(f"Imagen {i + 1} de {total}...", 58 + int(8 * (i / max(1, total))))

        # 1) Intentar IA si corresponde
        if source in ("ai", "hybrid"):
            if generate_ai_image(scene.image_prompt, dest, seed=1000 + i):
                got = ImageResult(path=dest, source="ai", query=scene.image_prompt)

        # 2) Intentar stock si no hay imagen aun (modo stock, o respaldo de hybrid/ai)
        if got is None and (source in ("stock", "hybrid", "ai")):
            src = _download_stock(scene.keyword, dest, used_urls)
            if src is None:
                # ultimo intento con un termino mas generico
                src = _download_stock(scene.image_prompt.split(",")[0], dest, used_urls)
            if src:
                got = ImageResult(path=dest, source=src, query=scene.keyword)

        # 3) Si aun no hay imagen, reutilizar la anterior (para no romper el video)
        if got is None and results:
            prev = results[-1]
            try:
                dest.write_bytes(prev.path.read_bytes())
                got = ImageResult(path=dest, source=prev.source, query=scene.keyword)
            except Exception:
                got = None

        if got is not None:
            results.append(got)

    if not results:
        raise ValueError(
            "No pude conseguir ninguna imagen (ni IA ni stock). "
            "Revisa tu conexion a internet y tu clave de Pexels."
        )
    return results


# --------------------------------------------------------------------------
#  Compatibilidad: version antigua basada en keywords sueltas
# --------------------------------------------------------------------------
def fetch_images(
    keywords: list[str],
    dest_dir: Path,
    min_images: int = 4,
) -> list[ImageResult]:
    """Version simple (solo stock) que se conserva por compatibilidad."""
    scenes = [Scene(text="", image_prompt=k, keyword=k) for k in keywords]
    return fetch_scene_images(scenes, dest_dir, source="stock")
