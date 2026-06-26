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

CONTROL DE DURACION (lo importante):
La duracion del video la manda la VOZ, y la voz depende de cuantas PALABRAS
escribe la IA. La IA casi siempre se queda CORTA. Por eso, despues de generar
el guion, lo REVISAMOS: si quedo corto, le pedimos a la IA que lo ALARGUE
(bucle de expansion). Si aun asi no alcanza (porque la noticia tiene poco
material), generamos un AVISO para que el usuario agregue mas URLs o contexto.
Tambien partimos escenas largas para que un video largo tenga MAS fotos.
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

# Cada cuantos SEGUNDOS queremos que cambie la foto. Bajalo para MAS fotos
# (mas dinamico) o subelo para menos. ~15 s es un buen ritmo viral.
SECONDS_PER_IMAGE = 15

# Cuantas veces, como maximo, le pedimos a la IA que ALARGUE el guion si quedo
# corto. Cada intento es gratis y rapido (Groq), pero no insistimos infinito.
_MAX_EXPAND_TRIES = 3


def _tokens_for(duration: int) -> int:
    """Cuanto 'espacio' de respuesta darle a la IA segun la duracion del video.
    Videos largos necesitan mas tokens para no cortarse a la mitad."""
    return int(min(8000, max(2500, 1500 + duration * 14)))


def _scene_count_for(duration: int) -> int:
    """
    Cuantas fotos/escenas queremos segun la duracion (~1 foto cada
    SECONDS_PER_IMAGE segundos). Asi un video largo tiene MAS fotos y la gente
    no se aburre viendo la misma imagen mucho tiempo.

    Ej (con 15 s/foto): 45s->3, 60s->4, 120s->8, 180s->12, 300s->20.
    """
    return max(3, min(40, round(duration / SECONDS_PER_IMAGE)))


def _resolve_n_images(n_images, duration: int) -> int:
    """
    Decide cuantas fotos/escenas usar a partir de lo que eligio el usuario.

    - "auto" / vacio / None -> automatico segun la duracion, pero NUNCA menos de 8.
    - un numero -> se respeta, limitado entre 8 (minimo) y 40 (maximo).

    Asi el usuario puede decidir cuantas imagenes quiere en CUALQUIER modo
    (noticia, YouTube o historia), sin importar la duracion del video.
    """
    auto = max(8, _scene_count_for(duration))
    if n_images is None:
        return auto
    texto = str(n_images).strip().lower()
    if texto in ("", "auto", "automatico", "automático", "0"):
        return auto
    try:
        return max(8, min(40, int(float(texto))))
    except ValueError:
        return auto


def _tolerance_words(duration: int) -> int:
    """
    Margen permitido (en palabras) para considerar que el guion 'da el ancho'.
    El usuario pidio: +-5 s en videos por segundos, +-15 s en videos por minutos.
    """
    tol_seconds = 5 if duration <= 90 else 15
    return int(tol_seconds * _WORDS_PER_SECOND)


def _count_words(scenes: list["Scene"]) -> int:
    """Total de palabras narradas (suma de todas las escenas)."""
    return sum(len(s.text.split()) for s in scenes)


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
    # Aviso para el usuario cuando NO se pudo llegar a la duracion pedida
    # (por falta de material). Cadena vacia = todo bien, sin aviso.
    warning: str = ""

    @property
    def image_keywords(self) -> list[str]:
        """Compatibilidad: lista de keywords de stock por escena."""
        return [s.keyword for s in self.scenes if s.keyword]


def _build_prompt(article: Article, duration: int, style: str, cta: str, n_scenes: int) -> list[dict]:
    target_words = int(duration * _WORDS_PER_SECOND)
    min_words = max(1, target_words - _tolerance_words(duration))
    style_desc = _STYLE_DESC.get(style, _STYLE_DESC["breaking"])
    # Para videos largos le damos mas texto de la noticia a la IA (mas material).
    src_chars = min(16000, max(6000, target_words * 25))

    system = (
        "Eres un guionista experto en videos cortos virales (Reels, TikTok, "
        "YouTube Shorts) en ESPANOL latino. Escribes guiones con un gancho "
        "potente en los primeros 3 segundos, ritmo agil y un cierre con "
        "llamada a la accion. Respetas SIEMPRE la longitud pedida (es mejor "
        "pasarte un poco que quedarte corto). Respondes SIEMPRE en espanol y "
        "SOLO con JSON valido."
    )

    user = f"""
A partir de esta noticia, crea un guion para un video vertical corto, DIVIDIDO EN ESCENAS.

TITULO DE LA NOTICIA:
{article.title}

CONTENIDO DE LA NOTICIA:
{article.text[:src_chars]}

REQUISITOS:
- Idioma del guion (campo "text"): espanol latino, cercano y natural.
- Estilo: {style_desc}.
- LONGITUD (MUY IMPORTANTE): el guion debe durar unos {duration} segundos al
  narrarse, asi que escribe el guion COMPLETO con APROXIMADAMENTE {target_words}
  palabras EN TOTAL (sumando todas las escenas), y NUNCA menos de {min_words}
  palabras. NO resumas de mas: desarrolla con detalles, datos y contexto de la
  noticia. Es mejor pasarte un poco que quedarte corto.
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


def _build_story_prompt(story: str, duration: int, n_images: int, cta: str) -> list[dict]:
    """
    Construye el prompt para cuando el usuario ESCRIBE su propia historia
    (en vez de pegar una noticia). Pedimos un minimo de imagenes/escenas.
    """
    target_words = int(duration * _WORDS_PER_SECOND)
    min_words = max(1, target_words - _tolerance_words(duration))
    n_scenes = max(8, int(n_images or 8))   # MINIMO 8 escenas/imagenes

    system = (
        "Eres un guionista experto en videos cortos virales (Reels, TikTok, "
        "YouTube Shorts) en ESPANOL latino. Conviertes una historia escrita por "
        "el usuario en un guion narrado con ritmo, dividido en escenas, y por "
        "cada escena creas una descripcion visual detallada para generar su "
        "imagen. Respetas SIEMPRE la longitud pedida. Respondes SIEMPRE en "
        "espanol y SOLO con JSON valido."
    )

    user = f"""
A partir de esta HISTORIA escrita por el usuario, crea un guion para un video
vertical corto, DIVIDIDO EN ESCENAS, y un prompt de imagen por cada escena.

HISTORIA DEL USUARIO:
{story[:6000]}

REQUISITOS:
- Idioma del guion (campo "text"): espanol latino, cercano y natural.
- Respeta la historia del usuario: NO inventes hechos que la contradigan.
  Puedes pulir la redaccion para que suene atractiva y con buen ritmo.
- LONGITUD (MUY IMPORTANTE): el guion debe durar unos {duration} segundos al
  narrarse, asi que escribe APROXIMADAMENTE {target_words} palabras EN TOTAL
  (sumando todas las escenas), y NUNCA menos de {min_words}. Desarrolla con
  descripciones y detalles; es mejor pasarte un poco que quedarte corto.
- Divide el guion en EXACTAMENTE {n_scenes} escenas (este es el numero de imagenes).
- La PRIMERA escena debe ser un GANCHO que enganche en los primeros 3 segundos.
- La ULTIMA escena debe cerrar con esta llamada a la accion (puedes adaptarla): "{cta}".
- En "text" NO pongas emojis, ni hashtags, ni acotaciones. Solo lo que se narra.

MUY IMPORTANTE sobre las imagenes (concordancia):
- Para CADA escena, "image_prompt" debe describir EN INGLES, de forma visual y
  concreta, una imagen que represente EXACTAMENTE lo que se narra en esa escena,
  manteniendo coherencia de personajes y ambientacion a lo largo de la historia.
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


def _build_expand_prompt(
    source_title: str,
    source_text: str,
    src_chars: int,
    current_narration: str,
    current_words: int,
    target_words: int,
    n_scenes: int,
    style_desc: str,
    cta: str,
    source_kind: str = "noticia",
) -> list[dict]:
    """
    Prompt para ALARGAR un guion que quedo demasiado corto. Le devolvemos a la
    IA su propio guion + la fuente original y le pedimos que lo desarrolle mas
    hasta acercarse al numero de palabras objetivo.
    """
    system = (
        "Eres un guionista experto en videos cortos virales en ESPANOL latino. "
        "Tu tarea ahora es ALARGAR un guion que quedo demasiado corto, "
        "manteniendo el tema, el estilo y la calidad, sin relleno vacio. "
        "Respondes SIEMPRE en espanol y SOLO con JSON valido."
    )

    if source_kind == "historia":
        fuente_label = "HISTORIA DEL USUARIO (fuente)"
        instr_fuente = (
            "Amplia con mas descripciones, ambientacion, emociones y detalles "
            "coherentes, SIN contradecir la historia del usuario."
        )
    else:
        fuente_label = "NOTICIA (fuente de informacion)"
        instr_fuente = (
            "Usa MAS datos, contexto, antecedentes y explicaciones tomados de la "
            "noticia. NO inventes hechos falsos y NO repitas frases tal cual."
        )

    user = f"""
El siguiente guion quedo DEMASIADO CORTO: tiene unas {current_words} palabras,
pero necesitamos unas {target_words} palabras EN TOTAL para alcanzar la duracion
pedida. Reescribelo MAS LARGO hasta acercarte a {target_words} palabras.
{instr_fuente}

{fuente_label}:
{source_title}
{source_text[:src_chars]}

GUION ACTUAL (muy corto, hay que alargarlo):
{current_narration}

REQUISITOS:
- Idioma: espanol latino, natural. Estilo: {style_desc}.
- Objetivo: ~{target_words} palabras EN TOTAL (es MEJOR pasarte un poco que
  quedarte corto). NO entregues menos que el guion actual.
- Divide el guion en {n_scenes} escenas aproximadamente.
- La PRIMERA escena = gancho potente. La ULTIMA escena cierra con: "{cta}".
- En "text" NO pongas emojis, ni hashtags, ni acotaciones.
- Para CADA escena: "image_prompt" (en ingles, visual, fotorealista) y "keyword"
  (termino corto en ingles para foto de stock).

DEVUELVE EXCLUSIVAMENTE UN JSON con esta forma EXACTA (sin texto extra):
{{
  "scenes": [
    {{"text": "...", "image_prompt": "detailed English description", "keyword": "short english term"}}
  ],
  "titles": ["3 titulos virales"],
  "hashtags": ["8 a 12 hashtags sin #"]
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


def _call_groq(messages: list[dict], timeout: int = 60, max_tokens: int = 2500) -> dict:
    """Envia los mensajes a Groq y devuelve el JSON ya parseado (dict)."""
    if not settings.groq_api_key or settings.groq_api_key.startswith("PEGA_AQUI"):
        raise ValueError(
            "Falta la clave de Groq (GROQ_API_KEY) en tu archivo .env. "
            "Consiguela gratis en https://console.groq.com"
        )

    payload = {
        "model": settings.groq_model,
        "messages": messages,
        "temperature": 0.8,
        "max_tokens": max_tokens,
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
        return _extract_json(content)
    except Exception as exc:
        raise ValueError(f"La IA no devolvio un JSON valido. Detalle: {exc}") from exc


def _parse_script(parsed: dict) -> VideoScript:
    """Convierte el JSON de Groq en un VideoScript con escenas validadas."""
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


# ==========================================================================
#  Control de LONGITUD y NUMERO DE FOTOS
# ==========================================================================
def _trim_scenes_to_words(scenes: list[Scene], max_words: int) -> None:
    """
    Si el guion se paso MUCHO del objetivo, quita escenas para recortarlo de
    forma limpia (entre escenas, no a media frase). Conserva SIEMPRE la primera
    escena (el gancho) y la ultima (la llamada a la accion), eliminando escenas
    intermedias del final hacia el centro.
    """
    while _count_words(scenes) > max_words and len(scenes) > 2:
        # Quitamos la penultima escena: asi respetamos gancho (primera) y cierre (ultima).
        del scenes[-2]


def _enforce_scene_count(scenes: list[Scene], target: int) -> None:
    """
    Garantiza que haya al menos `target` escenas (= fotos), partiendo las
    escenas mas largas en dos. Cada mitad conserva el MISMO image_prompt y
    keyword, por lo que al buscar/generar la imagen se obtiene una DISTINTA
    pero del mismo tema (stock: no se repite por la memoria de URLs; IA: cambia
    por la semilla). Asi un video largo cambia de foto seguido y no aburre.
    """
    MIN_WORDS = 6  # no creamos escenas mas chicas que esto (para que tengan sentido)
    guard = 0
    while len(scenes) < target and guard < 500:
        guard += 1
        # Buscamos la escena con MAS palabras (la mejor candidata para partir).
        idx = max(range(len(scenes)), key=lambda i: len(scenes[i].text.split()))
        words = scenes[idx].text.split()
        if len(words) < MIN_WORDS * 2:
            break  # ya no queda ninguna escena lo bastante grande para partir
        mid = len(words) // 2
        first = " ".join(words[:mid]).strip()
        second = " ".join(words[mid:]).strip()
        base = scenes[idx]
        scenes[idx] = Scene(text=first, image_prompt=base.image_prompt, keyword=base.keyword)
        scenes.insert(idx + 1, Scene(text=second, image_prompt=base.image_prompt, keyword=base.keyword))


def _coverage_warning(
    achieved_words: int, target_words: int, tol_words: int, duration: int, suggestion: str
) -> str:
    """
    Devuelve un AVISO (para mostrar al usuario) si el guion no alcanzo la
    duracion pedida por falta de material. Cadena vacia si todo bien.
    """
    if achieved_words >= target_words - tol_words:
        return ""
    est = max(1, round(achieved_words / _WORDS_PER_SECOND))
    return (
        f"\u26a0\ufe0f Necesito mas informacion: con lo que hay, el guion alcanza "
        f"para ~{est} segundos, no para los {duration} que pediste. {suggestion}"
    )


def _fit_length_and_scenes(
    script: VideoScript,
    *,
    duration: int,
    n_scenes: int,
    style_desc: str,
    cta: str,
    source_title: str,
    source_text: str,
    src_chars: int,
    max_tokens: int,
    timeout: int,
    source_kind: str,
    suggestion: str,
) -> VideoScript:
    """
    Ajusta el guion a la duracion pedida:
      1) Si quedo CORTO -> le pide a la IA que lo ALARGUE (hasta _MAX_EXPAND_TRIES).
      2) Si se paso MUCHO -> recorta escenas (deja gancho y cierre).
      3) Garantiza el numero de fotos partiendo escenas largas.
      4) Calcula el aviso si no se pudo llegar a la duracion (falta material).
    """
    target_words = int(duration * _WORDS_PER_SECOND)
    tol_words = _tolerance_words(duration)

    # 1) EXPANDIR si quedo corto (la IA casi siempre se queda corta)
    tries = 0
    while _count_words(script.scenes) < target_words - tol_words and tries < _MAX_EXPAND_TRIES:
        tries += 1
        before = _count_words(script.scenes)
        messages = _build_expand_prompt(
            source_title, source_text, src_chars,
            script.narration, before, target_words, n_scenes,
            style_desc, cta, source_kind=source_kind,
        )
        try:
            longer = _parse_script(_call_groq(messages, timeout=timeout, max_tokens=max_tokens))
        except Exception as exc:  # noqa: BLE001
            print(f"[guion] no pude expandir (intento {tries}): {exc}")
            break
        after = _count_words(longer.scenes)
        if after > before:
            script = longer  # nos quedamos con la version mas larga
        if after <= before + 5:
            break  # ya no esta mejorando: no insistas

    # 2) RECORTAR si se paso mucho del objetivo (deja gancho y cierre)
    _trim_scenes_to_words(script.scenes, target_words + tol_words)

    # 3) GARANTIZAR el numero de fotos (parte escenas largas si hacen falta)
    _enforce_scene_count(script.scenes, n_scenes)

    # 4) Recalcular narracion y aviso final
    script.narration = " ".join(s.text for s in script.scenes if s.text.strip()).strip()
    script.warning = _coverage_warning(
        _count_words(script.scenes), target_words, tol_words, duration, suggestion
    )
    return script


def generate_script(
    article: Article,
    duration: int | None = None,
    style: str | None = None,
    cta: str | None = None,
    n_images=None,
    timeout: int = 60,
) -> VideoScript:
    """Llama a Groq y devuelve un VideoScript con escenas listo para usar (desde NOTICIA).

    n_images: cuantas fotos quiere el usuario ("auto" o un numero entre 8 y 40).
    """
    duration = duration or settings.video_duration
    style = style or settings.script_style
    cta = cta or settings.call_to_action

    style_desc = _STYLE_DESC.get(style, _STYLE_DESC["breaking"])
    n_scenes = _resolve_n_images(n_images, duration)
    target_words = int(duration * _WORDS_PER_SECOND)
    src_chars = min(16000, max(6000, target_words * 25))
    max_tokens = _tokens_for(duration)

    messages = _build_prompt(article, duration, style, cta, n_scenes)
    script = _parse_script(_call_groq(messages, timeout=timeout, max_tokens=max_tokens))

    script = _fit_length_and_scenes(
        script,
        duration=duration,
        n_scenes=n_scenes,
        style_desc=style_desc,
        cta=cta,
        source_title=article.title,
        source_text=article.text,
        src_chars=src_chars,
        max_tokens=max_tokens,
        timeout=timeout,
        source_kind="noticia",
        suggestion="Agrega otra URL de noticia (una por renglon) o mas contexto y vuelve a generar.",
    )
    print(
        f"[guion] {len(script.scenes)} escenas, ~{_count_words(script.scenes)} palabras "
        f"(objetivo {target_words} para {duration}s)"
        + (" [AVISO: material insuficiente]" if script.warning else "")
    )
    return script


def generate_script_from_story(
    story: str,
    duration: int | None = None,
    n_images=8,
    cta: str | None = None,
    timeout: int = 60,
) -> VideoScript:
    """
    Llama a Groq y devuelve un VideoScript a partir de una HISTORIA escrita
    por el usuario (Modo Historia). El usuario elige cuantas fotos quiere
    ("auto" o un numero entre 8 y 40).
    """
    story = (story or "").strip()
    if len(story) < 30:
        raise ValueError(
            "La historia es muy corta. Escribe al menos unas frases con los "
            "detalles que quieres que aparezcan en el video."
        )

    duration = duration or settings.video_duration
    cta = cta or settings.call_to_action

    # El usuario decide el numero de imagenes (minimo 8); "auto" lo calcula
    # segun la duracion. Es el mismo criterio que en el modo noticia.
    n_scenes = _resolve_n_images(n_images, duration)
    style_desc = "estilo narrativo atractivo y con buen ritmo"
    target_words = int(duration * _WORDS_PER_SECOND)
    max_tokens = _tokens_for(duration)

    messages = _build_story_prompt(story, duration, n_scenes, cta)
    script = _parse_script(_call_groq(messages, timeout=timeout, max_tokens=max_tokens))

    script = _fit_length_and_scenes(
        script,
        duration=duration,
        n_scenes=n_scenes,
        style_desc=style_desc,
        cta=cta,
        source_title="",
        source_text=story,
        src_chars=6000,
        max_tokens=max_tokens,
        timeout=timeout,
        source_kind="historia",
        suggestion="Agrega mas detalles a tu historia y vuelve a generar.",
    )
    print(
        f"[historia] {len(script.scenes)} escenas, ~{_count_words(script.scenes)} palabras "
        f"(objetivo {target_words} para {duration}s)"
        + (" [AVISO: material insuficiente]" if script.warning else "")
    )
    return script
