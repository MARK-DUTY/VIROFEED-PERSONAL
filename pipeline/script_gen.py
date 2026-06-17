"""
Paso 2 del pipeline: convertir el texto de la noticia en un GUION VIRAL.

Usa la API de Groq (gratis) con un modelo Llama. Le pedimos que devuelva
un JSON dividido en ESCENAS. Cada escena trae:
  - text         : la parte del guion que se narra en esa escena
  - image_prompt : descripcion visual detallada (en ingles) para GENERAR la
                   imagen con IA que concuerde con lo que se narra
  - keyword      : termino corto (en ingles) para buscar foto de stock (respaldo)

Asi cada imagen concuerda con lo que se esta diciendo en ese momento.
Tambien devuelve titulos y hashtags (la seccion "hooks & SEO" de ViroFeed).
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
class Scene:
    """Una escena del video: su texto narrado + como debe verse la imagen."""
    text: str
    image_prompt: str   # descripcion detallada en ingles para generar imagen IA
    keyword: str        # termino corto en ingles para buscar foto de stock


@dataclass
class VideoScript:
    """Todo lo que la IA genera para el video."""
    narration: str                       # texto completo a narrar (= union de escenas)
    scenes: list[Scene] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def image_keywords(self) -> list[str]:
        """Compatibilidad: lista de keywords de stock por escena."""
        return [s.keyword for s in self.scenes if s.keyword]


def _build_prompt(article: Article, duration: int, style: str, cta: str) -> list[dict]:
    target_words = int(duration * _WORDS_PER_SECOND)
    style_desc = _STYLE_DESC.get(style, _STYLE_DESC["breaking"])
    n_scenes = max(4, min(9, round(duration / 6)))

    system = (
        "Eres un guionista experto en videos cortos virales (Reels, TikTok, "
        "YouTube Shorts) en ESPANOL latino. Escribes guiones con un gancho "
        "potente en los primeros 3 segundos, ritmo agil y un cierre con "
        "llamada a la accion. Respondes SIEMPRE en espanol y SOLO con JSON valido."
    )

    user = f"""
A partir de esta noticia, crea un guion para un video vertical corto, DIVIDIDO EN ESCENAS.

TITULO DE LA NOTICIA:
{article.title}

CONTENIDO DE LA NOTICIA:
{article.text[:6000]}

REQUISITOS:
- Idioma del guion (campo "text"): espanol latino, cercano y natural.
- Estilo: {style_desc}.
- Duracion objetivo total: {duration} segundos (aprox. {target_words} palabras en total).
- Divide el guion en {n_scenes} escenas aproximadamente.
- La PRIMERA escena debe ser un GANCHO que enganche en los primeros 3 segundos.
- La ULTIMA escena debe cerrar con esta llamada a la accion (puedes adaptarla): "{cta}".
- En "text" NO pongas emojis, ni hashtags, ni acotaciones. Solo lo que se narra.

MUY IMPORTANTE sobre las imagenes (concordancia):
- Para CADA escena, "image_prompt" debe describir EN INGLES, de forma visual y
  concreta, una imagen que represente EXACTAMENTE lo que se narra en esa escena.
  Ejemplo: si la escena habla de gatos, image_prompt = "a cute domestic cat
  sitting on a sofa, photorealistic". Si habla del Dia de Muertos en Mexico,
  image_prompt = "Mexican Day of the Dead altar with marigolds, candles and
  sugar skulls, vibrant, photorealistic".
- "keyword" debe ser un termino corto EN INGLES (2 a 4 palabras) para buscar
  una foto de stock relacionada con esa escena (respaldo).

DEVUELVE EXCLUSIVAMENTE UN JSON con esta forma EXACTA (sin texto extra):
{{
  "scenes": [
    {{
      "text": "parte del guion que se narra en esta escena",
      "image_prompt": "detailed English visual description of the scene, photorealistic",
      "keyword": "short english stock term"
    }}
  ],
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
    content = re.sub(r"^```(?:json)?", "", content).strip()
    content = re.sub(r"```$", "", content).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
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
    """Llama a Groq y devuelve un VideoScript con escenas listo para usar."""
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
        "max_tokens": 2000,
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

    raw_scenes = parsed.get("scenes", [])
    scenes: list[Scene] = []
    for s in raw_scenes:
        text = (s.get("text") or "").strip()
        if not text:
            continue
        image_prompt = (s.get("image_prompt") or "").strip() or text
        keyword = (s.get("keyword") or "").strip() or image_prompt
        scenes.append(Scene(text=text, image_prompt=image_prompt, keyword=keyword))

    if not scenes:
        raise ValueError("La IA no genero escenas. Intenta de nuevo.")

    # La narracion completa es la union de los textos de las escenas.
    narration = " ".join(s.text for s in scenes).strip()

    titles = [str(t).strip() for t in parsed.get("titles", []) if str(t).strip()]
    hashtags = [str(h).strip().lstrip("#") for h in parsed.get("hashtags", []) if str(h).strip()]

    return VideoScript(
        narration=narration,
        scenes=scenes,
        titles=titles,
        hashtags=hashtags,
        raw=parsed,
    )
