"""
Paso 4 del pipeline: conseguir las IMAGENES de fondo del video.

Busca y descarga imagenes verticales (formato 9:16, ideal para Reels/Shorts)
desde Pexels y, si esta configurado, tambien Pixabay. Ambos son gratis.

Cada palabra clave del guion genera una imagen distinta, para que el video
vaya cambiando de escena al ritmo de la narracion.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import requests

from .config import settings

PEXELS_SEARCH = "https://api.pexels.com/v1/search"
PIXABAY_SEARCH = "https://pixabay.com/api/"

_HEADERS = {"User-Agent": "ViroFeedPersonal/1.0"}


@dataclass
class ImageResult:
    path: Path
    source: str       # "pexels" | "pixabay"
    query: str        # con que palabra clave se encontro


def _download(url: str, dest: Path, timeout: int = 30) -> bool:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout, stream=True)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return dest.exists() and dest.stat().st_size > 1024
    except requests.RequestException:
        return False


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


def fetch_images(
    keywords: list[str],
    dest_dir: Path,
    min_images: int = 4,
) -> list[ImageResult]:
    """
    Descarga una imagen por cada palabra clave. Si una busqueda falla,
    intenta con la siguiente. Garantiza al menos `min_images` si es posible.

    Devuelve la lista de imagenes descargadas, en orden.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    if not settings.pexels_api_key or settings.pexels_api_key.startswith("PEGA_AQUI"):
        if not settings.pixabay_api_key:
            raise ValueError(
                "Falta la clave de Pexels (PEXELS_API_KEY) en tu .env. "
                "Consiguela gratis en https://www.pexels.com/api/"
            )

    results: list[ImageResult] = []
    used_urls: set[str] = set()
    idx = 0

    # Repetimos la lista de keywords si hace falta para llegar al minimo
    queries = list(keywords)
    while len(queries) < min_images and keywords:
        queries.append(keywords[len(queries) % len(keywords)])

    for query in queries:
        candidates = _search_pexels(query) + _search_pixabay(query)
        downloaded = False
        for url in candidates:
            if url in used_urls:
                continue
            source = "pexels" if "pexels" in url else "pixabay"
            dest = dest_dir / f"img_{idx:02d}.jpg"
            if _download(url, dest):
                used_urls.add(url)
                results.append(ImageResult(path=dest, source=source, query=query))
                idx += 1
                downloaded = True
                break
        # Si no se descargo nada para esta keyword, seguimos con la siguiente
        if not downloaded:
            continue

    if not results:
        raise ValueError(
            "No pude descargar ninguna imagen. Revisa tu clave de Pexels/Pixabay "
            "y tu conexion a internet."
        )
    return results
