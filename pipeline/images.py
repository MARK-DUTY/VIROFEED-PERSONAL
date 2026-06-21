"""
Paso 4 del pipeline: conseguir las IMAGENES de fondo del video.

Tres fuentes posibles (se elige con IMAGE_SOURCE en .env o desde la interfaz):
  - "together": genera imagenes con IA FLUX (Together AI). MAS REALISTA y gratis.
                Necesita TOGETHER_API_KEY. Genera directo en vertical 9:16.
  - "gemini" : genera con Google "Nano Banana" (necesita GEMINI_API_KEY).
  - "ai"     : genera imagenes con IA (Pollinations.ai) a partir de la
               descripcion de cada escena. GRATIS y sin clave.
  - "stock"  : busca fotos reales en Pexels / Pixabay por palabra clave.
  - "hybrid" : intenta IA y, si falla, usa stock (lo mejor de ambos).

Cada ESCENA del guion produce su propia imagen, para que el video concuerde
con lo que se esta narrando en cada momento.
"""
from __future__ import annotations

import base64
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import requests

from .config import settings
from .script_gen import Scene

PEXELS_SEARCH = "https://api.pexels.com/v1/search"
PIXABAY_SEARCH = "https://pixabay.com/api/"
UNSPLASH_SEARCH = "https://api.unsplash.com/search/photos"
OPENVERSE_SEARCH = "https://api.openverse.org/v1/images/"
POLLINATIONS = "https://image.pollinations.ai/prompt/"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
TOGETHER_IMAGES = "https://api.together.xyz/v1/images/generations"

_HEADERS = {"User-Agent": "ViroFeedPersonal/1.0"}

# Tamano de generacion IA (vertical 9:16). El ensamblaje luego lo ajusta a 1080x1920.
_AI_W, _AI_H = 768, 1344

# --------------------------------------------------------------------------
#  Mejora de PROMPTS para realismo (evita manos/caras deformes)
# --------------------------------------------------------------------------
# Lista de "cosas a evitar" que causan las imagenes raras (dos cabezas, dedos de mas...).
_NEGATIVE_PROMPT = (
    "deformed, disfigured, extra limbs, extra arms, extra legs, extra fingers, "
    "fused fingers, mutated hands, malformed hands, bad anatomy, bad proportions, "
    "two heads, cloned face, long neck, blurry, low quality, lowres, jpeg artifacts, "
    "watermark, text, logo, signature, cropped, out of frame, cartoon, 3d render, "
    "cgi, illustration, painting, drawing"
)

# Frases que empujan hacia una FOTO realista de alta calidad.
_REALISM_PREFIX = "Photorealistic editorial photograph, "
_REALISM_SUFFIX = (
    ", realistic natural lighting, sharp focus, high detail, 50mm lens, "
    "professional news photography, vertical 9:16 composition, realistic anatomy"
)


def _enhance_for_realism(prompt: str) -> str:
    """
    Envuelve la descripcion de la escena con instrucciones que mejoran el
    realismo y reducen los errores de anatomia. Se aplica a TODOS los motores
    de IA (Pollinations, Together, etc.).
    """
    clean = (prompt or "").strip().rstrip(".")
    if not clean:
        return clean
    return f"{_REALISM_PREFIX}{clean}{_REALISM_SUFFIX}"


@dataclass
class ImageResult:
    path: Path
    source: str       # "ai" | "pexels" | "pixabay"
    query: str        # con que descripcion/keyword se obtuvo
    url: str = ""     # URL original de la foto (para no repetirla al pulsar "Otra foto")


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
    clean = _enhance_for_realism(prompt)
    if not clean:
        return False
    encoded = urllib.parse.quote(clean, safe="")
    params = {
        "width": _AI_W,
        "height": _AI_H,
        "nologo": "true",
        "enhance": "true",   # mejora automatica del prompt -> mas calidad
        "model": "flux",
    }
    if seed is not None:
        params["seed"] = seed
    query = urllib.parse.urlencode(params)
    url = f"{POLLINATIONS}{encoded}?{query}"
    return _download(url, dest, timeout=90)


# --------------------------------------------------------------------------
#  Generacion con Together AI (FLUX.1 schnell Free) - mas REALISTA, gratis
#  Necesita TOGETHER_API_KEY. FLUX es el modelo #1 en realismo y genera
#  directamente en vertical 9:16.
# --------------------------------------------------------------------------
def generate_together_image(prompt: str, dest: Path, seed: int | None = None, timeout: int = 120) -> bool:
    """
    Genera una imagen realista con Together AI usando FLUX.
    Devuelve True si se guardo la imagen correctamente.
    """
    key = settings.together_api_key
    if not key or key.startswith("PEGA_AQUI"):
        print("[together] falta TOGETHER_API_KEY en .env")
        return False
    clean = _enhance_for_realism(prompt)
    if not clean:
        return False

    model = settings.together_image_model or "black-forest-labs/FLUX.1-schnell-Free"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "prompt": clean,
        "width": _AI_W,
        "height": _AI_H,
        "steps": 4,            # FLUX schnell rinde bien con pocos pasos (gratis: max 4)
        "n": 1,
        "response_format": "b64_json",
    }
    if seed is not None:
        body["seed"] = seed
    try:
        resp = requests.post(TOGETHER_IMAGES, headers=headers, json=body, timeout=timeout)
        if resp.status_code >= 400:
            print(f"[together] error {resp.status_code}: {resp.text[:200]}")
            return False
        data = resp.json()
        items = data.get("data") or []
        if not items:
            print("[together] respuesta sin imagenes")
            return False
        first = items[0]
        # La respuesta puede venir como base64 (b64_json) o como una URL
        b64 = first.get("b64_json")
        if b64:
            dest.write_bytes(base64.b64decode(b64))
            return dest.exists() and dest.stat().st_size > 2048
        url = first.get("url")
        if url:
            return _download(url, dest, timeout=timeout)
        print("[together] la respuesta no traia imagen")
        return False
    except requests.RequestException as exc:
        print(f"[together] excepcion de red: {exc}")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"[together] excepcion: {exc}")
        return False


# --------------------------------------------------------------------------
#  Generacion con Gemini "Nano Banana" (mas realista) - necesita GEMINI_API_KEY
# --------------------------------------------------------------------------
def generate_gemini_image(prompt: str, dest: Path, timeout: int = 120) -> bool:
    """
    Genera una imagen realista con Google Gemini (Nano Banana).
    Devuelve True si se guardo la imagen correctamente.
    """
    key = settings.gemini_api_key
    if not key:
        print("[gemini] falta GEMINI_API_KEY en .env")
        return False
    clean = (prompt or "").strip()
    if not clean:
        return False

    model = settings.gemini_image_model or "gemini-2.5-flash-image"
    url = f"{GEMINI_BASE}/{model}:generateContent?key={key}"
    full_prompt = (
        "Generate a photorealistic, high-quality vertical 9:16 portrait image, "
        "natural lighting, realistic, no text, no watermark. Scene: " + clean
    )
    body = {
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    try:
        resp = requests.post(url, json=body, timeout=timeout)
        if resp.status_code >= 400:
            print(f"[gemini] error {resp.status_code}: {resp.text[:200]}")
            return False
        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            print("[gemini] respuesta sin candidates")
            return False
        parts = candidates[0].get("content", {}).get("parts", [])
        for p in parts:
            inline = p.get("inlineData") or p.get("inline_data")
            if inline and inline.get("data"):
                raw = base64.b64decode(inline["data"])
                dest.write_bytes(raw)
                return dest.exists() and dest.stat().st_size > 2048
        print("[gemini] la respuesta no traia imagen (posible limite o modelo distinto)")
        return False
    except requests.RequestException as exc:
        print(f"[gemini] excepcion de red: {exc}")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"[gemini] excepcion: {exc}")
        return False


# --------------------------------------------------------------------------
#  Busqueda en stock (Pexels / Pixabay)
# --------------------------------------------------------------------------
def _search_pexels(query: str, want: int = 1) -> list[str]:
    if not settings.pexels_api_key or settings.pexels_api_key.startswith("PEGA_AQUI"):
        return []
    headers = {"Authorization": settings.pexels_api_key}
    params = {"query": query, "per_page": min(80, max(15, want * 2)), "orientation": "portrait"}
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
        "per_page": min(200, max(15, want * 2)),
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


def _search_unsplash(query: str, want: int = 1) -> list[str]:
    """Busca fotos profesionales en Unsplash. Necesita UNSPLASH_ACCESS_KEY (gratis)."""
    key = settings.unsplash_access_key
    if not key or key.startswith("PEGA_AQUI"):
        return []
    headers = {"Authorization": f"Client-ID {key}", **_HEADERS}
    params = {"query": query, "per_page": min(30, max(15, want * 2)), "orientation": "portrait"}
    try:
        resp = requests.get(UNSPLASH_SEARCH, headers=headers, params=params, timeout=25)
        if resp.status_code != 200:
            return []
        results = resp.json().get("results", [])
        urls = []
        for p in results:
            u = p.get("urls", {})
            url = u.get("regular") or u.get("full") or u.get("raw")
            if url:
                urls.append(url)
        return urls
    except requests.RequestException:
        return []


def _search_openverse(query: str, want: int = 1) -> list[str]:
    """Busca en Openverse (700M+ imagenes). NO necesita clave (gratis)."""
    params = {
        "q": query,
        "license_type": "commercial",   # solo imagenes de uso comercial
        "aspect_ratio": "tall",         # verticales, para formato 9:16
        "page_size": min(20, max(15, want * 2)),
    }
    try:
        resp = requests.get(OPENVERSE_SEARCH, headers=_HEADERS, params=params, timeout=25)
        if resp.status_code != 200:
            return []
        results = resp.json().get("results", [])
        return [r.get("url") for r in results if r.get("url")]
    except requests.RequestException:
        return []


def _download_stock(query: str, dest: Path, used_urls: set[str], want: int = 12) -> tuple[str, str] | None:
    """
    Intenta descargar una foto de stock para la query, SALTANDO las que ya se
    mostraron antes (las que estan en used_urls). Devuelve (fuente, url) o None.
    """
    # Mezclamos varias fuentes (mejores primero) para mas variedad y concordancia.
    candidates = (
        [(u, "pexels") for u in _search_pexels(query, want)]
        + [(u, "unsplash") for u in _search_unsplash(query, want)]
        + [(u, "pixabay") for u in _search_pixabay(query, want)]
        + [(u, "openverse") for u in _search_openverse(query, want)]
    )
    for url, source in candidates:
        if not url or url in used_urls:
            continue
        if _download(url, dest):
            used_urls.add(url)
            return source, url
    return None


def fetch_single_image(
    image_prompt: str,
    keyword: str,
    dest: Path,
    mode: str = "hybrid",
    seed: int | None = None,
    used_urls: set[str] | None = None,
) -> ImageResult | None:
    """
    Consigue UNA sola imagen para una escena (se usa al REGENERAR una imagen
    que salio mal o no concuerda).

    mode: "together" | "gemini" | "ai" | "stock" | "hybrid"
    seed: cambia la semilla para que la IA genere una imagen DISTINTA cada vez.
    used_urls: conjunto de URLs ya mostradas (para no repetir foto al pulsar
               "Otra foto"). Si es None, se usa uno nuevo (sin memoria).
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    used: set[str] = used_urls if used_urls is not None else set()
    return _make_one(image_prompt, keyword, dest, mode, used, seed)


def _make_one(
    image_prompt: str,
    keyword: str,
    dest: Path,
    mode: str,
    used_urls: set[str],
    seed: int | None,
) -> ImageResult | None:
    """Logica compartida: genera/consigue UNA imagen segun la fuente elegida."""
    mode = (mode or "hybrid").lower()

    # 1) Generadores de IA segun el modo
    if mode == "together":
        if generate_together_image(image_prompt, dest, seed=seed):
            return ImageResult(path=dest, source="together", query=image_prompt)
        # respaldo: IA gratis (pollinations)
        if generate_ai_image(image_prompt, dest, seed=seed):
            return ImageResult(path=dest, source="ai", query=image_prompt)
    elif mode == "gemini":
        if generate_gemini_image(image_prompt, dest):
            return ImageResult(path=dest, source="gemini", query=image_prompt)
        # respaldo: IA gratis (pollinations)
        if generate_ai_image(image_prompt, dest, seed=seed):
            return ImageResult(path=dest, source="ai", query=image_prompt)
    elif mode in ("ai", "hybrid"):
        if generate_ai_image(image_prompt, dest, seed=seed):
            return ImageResult(path=dest, source="ai", query=image_prompt)

    # 2) Respaldo a foto de stock (sirve para todos los modos)
    got = _download_stock(keyword, dest, used_urls)
    if got is None and image_prompt:
        got = _download_stock(image_prompt.split(",")[0], dest, used_urls)
    if got:
        source, url = got
        return ImageResult(path=dest, source=source, query=keyword, url=url)

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

    # Validacion de claves para modos que usan stock.
    # Openverse NO necesita clave, asi que el stock SIEMPRE esta disponible;
    # Pexels/Pixabay/Unsplash solo mejoran la variedad y calidad.
    stock_available = True  # gracias a Openverse (sin clave)
    if source == "stock" and not stock_available:
        raise ValueError(
            "Elegiste fotos de stock pero no hay ninguna fuente disponible."
        )

    results: list[ImageResult] = []
    used_urls: set[str] = set()
    total = len(scenes)

    for i, scene in enumerate(scenes):
        dest = dest_dir / f"img_{i:02d}.jpg"

        if progress:
            progress(f"Imagen {i + 1} de {total}...", 58 + int(8 * (i / max(1, total))))

        got = _make_one(
            scene.image_prompt, scene.keyword, dest, source, used_urls, seed=1000 + i
        )

        # Si no se consiguio imagen, reutilizar la anterior (para no romper el video)
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
