"""
Paso 1 del pipeline: leer una noticia desde su URL y sacar el texto limpio.

Usa `trafilatura` (muy bueno quitando menus, anuncios y dejando solo el
articulo). Si por alguna razon falla, intenta un metodo de respaldo simple.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import requests
import trafilatura

# Cabecera para que las webs nos respondan como si fueramos un navegador normal
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


@dataclass
class Article:
    """Resultado de leer una noticia."""
    url: str
    title: str
    text: str

    @property
    def is_usable(self) -> bool:
        # Necesitamos al menos un poco de texto para generar un guion
        return len(self.text.strip()) >= 120


def _clean(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text or "")
    return text.strip()


def extract_article(url: str, timeout: int = 25) -> Article:
    """
    Descarga la pagina de la URL y extrae titulo + texto del articulo.

    Lanza ValueError con un mensaje claro si no se pudo leer nada util.
    """
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError(
            "La URL no parece valida. Debe empezar con http:// o https://"
        )

    # Descargar el HTML
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        html = resp.text
    except requests.RequestException as exc:
        raise ValueError(
            f"No se pudo abrir la pagina. Revisa la URL o tu internet. Detalle: {exc}"
        ) from exc

    # Extraer el contenido principal con trafilatura
    title = ""
    text = ""
    try:
        meta = trafilatura.extract_metadata(html)
        if meta and meta.title:
            title = meta.title
    except Exception:
        pass

    try:
        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
            url=url,
        )
        if extracted:
            text = extracted
    except Exception:
        text = ""

    # Metodo de respaldo: si trafilatura no saco texto, intentamos algo simple
    if not text:
        text = _fallback_text(html)
    if not title:
        title = _fallback_title(html) or "Noticia"

    article = Article(url=url, title=_clean(title), text=_clean(text))

    if not article.is_usable:
        raise ValueError(
            "Pude abrir la pagina pero no encontre suficiente texto de noticia. "
            "Prueba con la URL directa del articulo (no la portada del sitio)."
        )
    return article


def extract_articles(urls: list[str], timeout: int = 25) -> Article:
    """
    Lee VARIAS noticias (varias URLs del mismo tema) y las combina en un solo
    Article con todo el texto junto. Asi hay material de sobra para videos largos.

    - Lee cada URL; si alguna falla, la salta (no rompe todo el proceso).
    - El titulo es el de la primera noticia que se pudo leer.
    - El texto es la union de todas, separadas por una linea en blanco.

    Lanza ValueError solo si NINGUNA de las URLs se pudo leer.
    """
    urls = [u.strip() for u in (urls or []) if u and u.strip()]
    if not urls:
        raise ValueError("No diste ninguna URL de noticia.")
    # Si es una sola, usamos el lector normal de siempre.
    if len(urls) == 1:
        return extract_article(urls[0], timeout=timeout)

    title = ""
    parts: list[str] = []
    errors: list[str] = []
    for u in urls:
        try:
            art = extract_article(u, timeout=timeout)
            if not title:
                title = art.title
            parts.append(art.text)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"- {u}: {exc}")

    if not parts:
        raise ValueError(
            "No pude leer NINGUNA de las paginas que pegaste. Revisa que sean "
            "enlaces directos a articulos. Detalle:\n" + "\n".join(errors)
        )

    combined = "\n\n".join(parts)
    article = Article(url=urls[0], title=title or "Noticia", text=_clean(combined))
    print(f"[articulo] {len(parts)} de {len(urls)} fuentes combinadas")
    return article


def _fallback_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return ""


def _fallback_text(html: str) -> str:
    # Quitar scripts y estilos, luego todas las etiquetas
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", html, flags=re.IGNORECASE | re.DOTALL)
    chunks = []
    for p in paragraphs:
        clean = re.sub(r"<[^>]+>", "", p)
        clean = re.sub(r"\s+", " ", clean).strip()
        if len(clean) > 40:
            chunks.append(clean)
    return "\n\n".join(chunks)
