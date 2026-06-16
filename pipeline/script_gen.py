"""
Paso 2 del pipeline: convertir el texto de la noticia en un GUION VIRAL.

Usa la API de Groq (gratis) con un modelo Llama. Le pedimos que devuelva
un JSON con: guion narrado, palabras clave para buscar imagenes, titulos
y hashtags (igual que hace ViroFeed con su seccion de "hooks & SEO").
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import requests

from .article import Article
from .config import settings

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Cuantas palabras caben aproximadamente segun la duracion (locucion ~2.6 pal/seg)
_WORDS_PER_SECOND = 2.6

_STYLE_DESC = {
    "breaking": "estilo NOTICIA DE ULTIMO MINUTO, urgente y con gancho",
    "resumen": "estilo RESUMEN RAPIDO, claro y directo",
    "top3": "estilo TOP 3 CLAVES, enumerando los 3 puntos mas importantes",
}


@dataclass
class VideoScript:
    """Todo lo que la IA genera para el video."""
    narration: str               # el texto que dira la voz (sin emojis ni hashtags)
    image_keywords: list[str] = field(default_factory=list)  # busquedas para imagenes
    titles: list[str] = field(default_factory=list)          # titulos/hooks para publicar
    hashtags: list[str] = field(default_factory=list)        # hashtags
    raw: dict = field(default_factory=dict)                  # respuesta cruda por si acaso


def _build_prompt(article: Article, duration: int, style: str, cta: str) -> list[dict]:
    target_words = int(duration * _WORDS_PER_SECOND)
    style_desc = _STYLE_DESC.get(style, _STYLE_DESC["breaking"])
    n_images = max(4, min(8, round(duration / 7)))

    system = (
        "Eres un guionista experto en videos cortos virales (Reels, TikTok, "
        "YouTube Shorts) en ESPANOL latino. Escribes guiones con un gancho "
        "potente en los primeros 3 segundos, ritmo agil y un cierre con "
        "llamada a la accion. Respondes SIEMPRE en espanol y SOLO con JSON valido."
    )

    user = f"""
A partir de esta noticia, crea un guion para un video vertical corto.

TITULO DE LA NOTICIA:
{article.title}

CONTENIDO DE LA NOTICIA:
{article.text[:6000]}

REQUISITOS DEL GUION:
- Idioma: espanol latino, cercano y natural (como hablandole a un amigo).
- Estilo: {style_desc}.
- Duracion objetivo: {duration} segundos (aprox. {target_words} palabras).
- El PRIMER renglon debe ser un GANCHO que enganche en los primeros 3 segundos.
- Termina con esta llamada a la accion (puedes adaptarla levemente): "{cta}".
- NO incluyas emojis, ni hashtags, ni acotaciones de escena dentro de 'narration'.
- 'narration' es SOLO lo que se va a narrar en voz alta, en texto corrido.

DEVUELVE EXCLUSIVAMENTE UN JSON con esta forma EXACTA (sin texto extra):
{{
  "narration": "el guion completo para narrar...",
  "image_keywords": ["{n_images} busquedas en INGLES para encontrar imagenes de stock, una por escena"],
  "titles": ["3 titulos virales para publicar el video"],
  "hashtags": ["8 a 12 hashtags relevantes sin el simbolo #"]
}}
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user.strip()},
    ]


def _extract_json(content: str) -> dict:
    """La IA a veces envuelve el JSON en texto o ```; lo limpiamos."""
    content = content.strip()
    # Quitar vallas de codigo ```json ... ```
    content = re.sub(r"^```(?:json)?", "", content).strip()
    content = re.sub(r"```$", "", content).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Buscar el primer { ... } balanceado
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(content[start : end + 1])
        raise


def generate_script(
    article: Article,
    duration: int | None = None,
    style: str | None = None,
    cta: str | None = None,
    timeout: int = 60,
) -> VideoScript:
    """Llama a Groq y devuelve un VideoScript listo para usar."""
    if not settings.groq_api_key or settings.groq_api_key.startswith("PEGA_AQUI"):
        raise ValueError(
            "Falta la clave de Groq (GROQ_API_KEY) en tu archivo .env. "
            "Consiguela gratis en https://console.groq.com"
        )

    duration = duration or settings.video_duration
    style = style or settings.script_style
    cta = cta or settings.call_to_action

    payload = {
        "model": settings.groq_model,
        "messages": _build_prompt(article, duration, style, cta),
        "temperature": 0.8,
        "max_tokens": 1500,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(GROQ_URL, json=payload, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise ValueError(f"No pude conectar con Groq. Revisa tu internet. Detalle: {exc}") from exc

    if resp.status_code == 401:
        raise ValueError("Groq rechazo la clave (401). Revisa tu GROQ_API_KEY en .env")
    if resp.status_code == 429:
        raise ValueError("Groq dice que excediste el limite gratis por ahora (429). Espera unos minutos.")
    if resp.status_code >= 400:
        raise ValueError(f"Groq devolvio un error {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    content = data["choices"][0]["message"]["content"]

    try:
        parsed = _extract_json(content)
    except Exception as exc:
        raise ValueError(f"La IA no devolvio un JSON valido. Detalle: {exc}") from exc

    narration = (parsed.get("narration") or "").strip()
    if not narration:
        raise ValueError("La IA no genero texto de narracion. Intenta de nuevo.")

    keywords = [str(k).strip() for k in parsed.get("image_keywords", []) if str(k).strip()]
    titles = [str(t).strip() for t in parsed.get("titles", []) if str(t).strip()]
    hashtags = [str(h).strip().lstrip("#") for h in parsed.get("hashtags", []) if str(h).strip()]

    # Respaldo: si la IA no dio keywords, usamos el titulo de la noticia
    if not keywords:
        keywords = [article.title]

    return VideoScript(
        narration=narration,
        image_keywords=keywords,
        titles=titles,
        hashtags=hashtags,
        raw=parsed,
    )
