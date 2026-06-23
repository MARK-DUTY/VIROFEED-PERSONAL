"""
ViroFeed AI Personal - Servidor web local (interfaz)

Flujo en DOS PASOS (como el editor de ViroFeed):
  1) PREPARAR: genera guion + voz + imagenes y te las muestra para revisar.
  2) REVISAR : cambias/regeneras las imagenes que salieron mal.
  3) GENERAR : arma el video final con las imagenes aprobadas.

Para arrancar:   python app.py
Luego abre:      http://localhost:5000
"""
from __future__ import annotations

import re
import threading
import traceback
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename


# --------------------------------------------------------------------------
#  AUTO-REPARACION: si falta algun archivo nuevo del programa (porque el
#  actualizar.bat viejo no lo trajo), lo descargamos solos desde GitHub ANTES
#  de importar el resto. Asi el programa nunca se queda sin abrir por un
#  archivo faltante.
# --------------------------------------------------------------------------
_RAW_BASE = "https://raw.githubusercontent.com/MARK-DUTY/VIROFEED-PERSONAL/main"
_REQUIRED_FILES = ["pipeline/music.py", "pipeline/youtube.py"]


def _self_repair() -> None:
    import urllib.request
    here = Path(__file__).resolve().parent
    for rel in _REQUIRED_FILES:
        dest = here / rel
        if dest.exists():
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            print(f"[auto-reparacion] falta {rel}, descargandolo desde GitHub...")
            urllib.request.urlretrieve(f"{_RAW_BASE}/{rel}", str(dest))
            print(f"[auto-reparacion] listo: {rel}")
        except Exception as exc:  # noqa: BLE001
            print(f"[auto-reparacion] no pude descargar {rel}: {exc}")


_self_repair()

from pipeline.config import settings
from pipeline.runner import (
    assemble_prepared,
    delete_scene,
    draft_story,
    prepare_from_draft,
    prepare_video,
    prepare_youtube,
    regenerate_scene_image,
    set_scene_image,
    update_scene_prompt,
    update_scene_text,
)
from pipeline.voice import list_spanish_voices

app = Flask(__name__)


def _parse_urls(data: dict) -> list[str]:
    """
    Saca la lista de URLs del cuerpo de la peticion. Acepta:
      - "urls": ["...", "..."]  (lista)
      - "url" : "uno\\notro"     (texto con un enlace por renglon)
    Devuelve la lista limpia (sin renglones vacios).
    """
    raw = data.get("urls")
    if isinstance(raw, list):
        items = raw
    else:
        items = re.split(r"[\r\n]+", str(data.get("url") or ""))
    return [u.strip() for u in items if u and u.strip()]

# Estado de los trabajos (en memoria). clave = job_id
#   cada job: {status, phase, message, percent, error, prepared, options, review, result}
JOBS: dict[str, dict] = {}


# --------------------------------------------------------------------------
#  Pagina principal
# --------------------------------------------------------------------------
@app.route("/")
def index():
    missing = settings.missing_keys()
    voices = list_spanish_voices()
    voice_names = [v.get("ShortName") for v in voices] if voices else []
    return render_template(
        "index.html",
        missing_keys=missing,
        avatar_enabled=settings.avatar_enabled,
        voice_names=voice_names,
        defaults={
            "voice": settings.tts_voice,
            "rate": settings.tts_rate,
            "duration": settings.video_duration,
            "style": settings.script_style,
            "cta": settings.call_to_action,
            "image_source": settings.image_source,
        },
    )


# --------------------------------------------------------------------------
#  Utilidad: armar la lista de escenas para la interfaz
# --------------------------------------------------------------------------
def _review_payload(job_id: str) -> dict:
    job = JOBS[job_id]
    prepared = job["prepared"]
    scenes = []
    for i, (scene, img) in enumerate(zip(prepared.scenes, prepared.images)):
        scenes.append({
            "index": i,
            "text": scene.text,
            "image_prompt": scene.image_prompt,
            "keyword": scene.keyword,
            "image_file": Path(img.path).name,
            "source": img.source,
        })
    return {
        "job_id": job_id,
        "title": prepared.title,
        "narration": prepared.narration,
        "titles": prepared.titles,
        "hashtags": prepared.hashtags,
        "duration": round(prepared.real_duration, 1),
        "use_avatar": bool(job["options"].get("use_avatar", False)),
        "voice": prepared.voice,
        "scenes": scenes,
    }


def _draft_payload(job_id: str) -> dict:
    """Lista de escenas del BORRADOR (texto + prompt, sin imagenes todavia)."""
    job = JOBS[job_id]
    prepared = job["prepared"]
    scenes = []
    for i, scene in enumerate(prepared.scenes):
        scenes.append({
            "index": i,
            "text": scene.text,
            "image_prompt": scene.image_prompt,
        })
    return {
        "job_id": job_id,
        "title": prepared.title,
        "titles": prepared.titles,
        "hashtags": prepared.hashtags,
        "scenes": scenes,
    }


# --------------------------------------------------------------------------
#  PASO 1: preparar (guion + voz + imagenes)
# --------------------------------------------------------------------------
@app.route("/api/prepare", methods=["POST"])
def api_prepare():
    data = request.get_json(force=True) or {}
    urls = _parse_urls(data)
    if not urls:
        return jsonify({"error": "Pega la URL de una noticia primero."}), 400

    fresh = settings.reload()
    missing = fresh.missing_keys()
    if "GROQ_API_KEY" in missing:
        return jsonify({"error": "Faltan claves en tu archivo .env: " + ", ".join(missing)}), 400

    job_id = uuid.uuid4().hex[:12]
    options = {
        "duration": int(data.get("duration") or fresh.video_duration),
        "style": data.get("style") or fresh.script_style,
        "voice": data.get("voice") or fresh.tts_voice,
        "rate": data.get("rate") if data.get("rate") is not None else fresh.tts_rate,
        "cta": data.get("cta") or fresh.call_to_action,
        "image_source": data.get("image_source") or fresh.image_source,
        "subtitle_color": data.get("subtitle_color") or "amarillo",
        "subtitle_position": data.get("subtitle_position") or "center",
        "use_avatar": bool(data.get("use_avatar", fresh.avatar_enabled)),
        "music_mode": data.get("music_mode") or "auto",
        "music_volume": float(data.get("music_volume") or 0.15),
        "aspect": data.get("aspect") or "9:16",
    }
    JOBS[job_id] = {
        "status": "running", "phase": "preparing", "message": "Iniciando...",
        "percent": 0, "error": None, "prepared": None, "options": options,
        "review": None, "result": None,
    }

    threading.Thread(target=_run_prepare, args=(job_id, urls, options), daemon=True).start()
    return jsonify({"job_id": job_id})


def _run_prepare(job_id: str, url, options: dict) -> None:
    def progress(msg: str, pct: int) -> None:
        JOBS[job_id]["message"] = msg
        JOBS[job_id]["percent"] = pct

    try:
        prepared = prepare_video(
            url,
            duration=options["duration"],
            style=options["style"],
            voice=options["voice"],
            rate=options["rate"],
            cta=options["cta"],
            image_source=options["image_source"],
            progress=progress,
        )
        JOBS[job_id]["prepared"] = prepared
        JOBS[job_id]["phase"] = "review"
        JOBS[job_id]["status"] = "ready"
        JOBS[job_id]["percent"] = 100
        JOBS[job_id]["message"] = "Listo para revisar"
        JOBS[job_id]["review"] = _review_payload(job_id)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = str(exc)


# --------------------------------------------------------------------------
#  PASO 1 (YOUTUBE): preparar desde un link de video de YouTube
# --------------------------------------------------------------------------
@app.route("/api/prepare_youtube", methods=["POST"])
def api_prepare_youtube():
    data = request.get_json(force=True) or {}
    urls = _parse_urls(data)
    if not urls:
        return jsonify({"error": "Pega el enlace de un video de YouTube primero."}), 400

    fresh = settings.reload()
    missing = fresh.missing_keys()
    if "GROQ_API_KEY" in missing:
        return jsonify({"error": "Faltan claves en tu archivo .env: " + ", ".join(missing)}), 400

    job_id = uuid.uuid4().hex[:12]
    options = {
        "duration": int(data.get("duration") or fresh.video_duration),
        "style": data.get("style") or fresh.script_style,
        "voice": data.get("voice") or fresh.tts_voice,
        "rate": data.get("rate") if data.get("rate") is not None else fresh.tts_rate,
        "cta": data.get("cta") or fresh.call_to_action,
        "image_source": data.get("image_source") or fresh.image_source,
        "subtitle_color": data.get("subtitle_color") or "amarillo",
        "subtitle_position": data.get("subtitle_position") or "center",
        "use_avatar": bool(data.get("use_avatar", fresh.avatar_enabled)),
        "music_mode": data.get("music_mode") or "auto",
        "music_volume": float(data.get("music_volume") or 0.15),
        "aspect": data.get("aspect") or "9:16",
    }
    JOBS[job_id] = {
        "status": "running", "phase": "preparing", "message": "Iniciando...",
        "percent": 0, "error": None, "prepared": None, "options": options,
        "review": None, "result": None,
    }

    threading.Thread(target=_run_prepare_youtube, args=(job_id, urls, options), daemon=True).start()
    return jsonify({"job_id": job_id})


def _run_prepare_youtube(job_id: str, url, options: dict) -> None:
    def progress(msg: str, pct: int) -> None:
        JOBS[job_id]["message"] = msg
        JOBS[job_id]["percent"] = pct

    try:
        prepared = prepare_youtube(
            url,
            duration=options["duration"],
            style=options["style"],
            voice=options["voice"],
            rate=options["rate"],
            cta=options["cta"],
            image_source=options["image_source"],
            progress=progress,
        )
        JOBS[job_id]["prepared"] = prepared
        JOBS[job_id]["phase"] = "review"
        JOBS[job_id]["status"] = "ready"
        JOBS[job_id]["percent"] = 100
        JOBS[job_id]["message"] = "Listo para revisar"
        JOBS[job_id]["review"] = _review_payload(job_id)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = str(exc)


# --------------------------------------------------------------------------
#  MODO HISTORIA - PASO A: crear el borrador (guion + prompts, sin imagenes)
# --------------------------------------------------------------------------
@app.route("/api/draft_story", methods=["POST"])
def api_draft_story():
    data = request.get_json(force=True) or {}
    story = (data.get("story") or "").strip()
    if not story:
        return jsonify({"error": "Escribe tu historia primero."}), 400

    fresh = settings.reload()
    if "GROQ_API_KEY" in fresh.missing_keys():
        return jsonify({"error": "Falta la clave GROQ_API_KEY en tu archivo .env"}), 400

    job_id = uuid.uuid4().hex[:12]
    options = {
        "duration": int(data.get("duration") or fresh.video_duration),
        "n_images": max(8, int(data.get("n_images") or 8)),
        "style": fresh.script_style,
        "voice": data.get("voice") or fresh.tts_voice,
        "rate": data.get("rate") if data.get("rate") is not None else fresh.tts_rate,
        "cta": data.get("cta") or fresh.call_to_action,
        "image_source": data.get("image_source") or fresh.image_source,
        "subtitle_color": data.get("subtitle_color") or "amarillo",
        "subtitle_position": data.get("subtitle_position") or "center",
        "use_avatar": bool(data.get("use_avatar", fresh.avatar_enabled)),
        "music_mode": data.get("music_mode") or "auto",
        "music_volume": float(data.get("music_volume") or 0.15),
        "aspect": data.get("aspect") or "9:16",
    }
    JOBS[job_id] = {
        "status": "running", "phase": "drafting", "message": "Iniciando...",
        "percent": 0, "error": None, "prepared": None, "options": options,
        "draft": None, "review": None, "result": None,
    }

    threading.Thread(target=_run_draft, args=(job_id, story, options), daemon=True).start()
    return jsonify({"job_id": job_id})


def _run_draft(job_id: str, story: str, options: dict) -> None:
    def progress(msg: str, pct: int) -> None:
        JOBS[job_id]["message"] = msg
        JOBS[job_id]["percent"] = pct

    try:
        prepared = draft_story(
            story,
            duration=options["duration"],
            n_images=options["n_images"],
            voice=options["voice"],
            rate=options["rate"],
            cta=options["cta"],
            image_source=options["image_source"],
            progress=progress,
        )
        JOBS[job_id]["prepared"] = prepared
        JOBS[job_id]["phase"] = "draft"
        JOBS[job_id]["status"] = "draft_ready"
        JOBS[job_id]["percent"] = 100
        JOBS[job_id]["message"] = "Borrador listo para revisar"
        JOBS[job_id]["draft"] = _draft_payload(job_id)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = str(exc)


# --------------------------------------------------------------------------
#  Editar el prompt de imagen de una escena (en el borrador)
# --------------------------------------------------------------------------
@app.route("/api/update_prompt", methods=["POST"])
def api_update_prompt():
    data = request.get_json(force=True) or {}
    job_id = data.get("job_id")
    job = JOBS.get(job_id)
    if not job or not job.get("prepared"):
        return jsonify({"error": "Trabajo no encontrado o expirado."}), 404
    try:
        index = int(data.get("index"))
        prompt = data.get("prompt") or ""
        update_scene_prompt(job["prepared"], index, prompt)
        # Si el usuario edito el dialogo en el borrador tambien, lo guardamos
        if data.get("text") is not None:
            update_scene_text(job["prepared"], index, data.get("text") or "")
        job["draft"] = _draft_payload(job_id)
        return jsonify({"ok": True})
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 400


# --------------------------------------------------------------------------
#  MODO HISTORIA - PASO B: generar voz + imagenes desde el borrador aprobado
# --------------------------------------------------------------------------
@app.route("/api/generate_from_draft", methods=["POST"])
def api_generate_from_draft():
    data = request.get_json(force=True) or {}
    job_id = data.get("job_id")
    job = JOBS.get(job_id)
    if not job or not job.get("prepared"):
        return jsonify({"error": "Trabajo no encontrado o expirado."}), 404

    job["phase"] = "preparing"
    job["status"] = "running"
    job["percent"] = 0
    job["message"] = "Generando voz e imagenes..."
    threading.Thread(target=_run_generate_from_draft, args=(job_id,), daemon=True).start()
    return jsonify({"job_id": job_id})


def _run_generate_from_draft(job_id: str) -> None:
    job = JOBS[job_id]

    def progress(msg: str, pct: int) -> None:
        job["message"] = msg
        job["percent"] = pct

    try:
        prepare_from_draft(job["prepared"], progress=progress)
        job["phase"] = "review"
        job["status"] = "ready"
        job["percent"] = 100
        job["message"] = "Listo para revisar"
        job["review"] = _review_payload(job_id)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        job["status"] = "error"
        job["error"] = str(exc)


# --------------------------------------------------------------------------
#  Subir musica de fondo (opcional) para el video
# --------------------------------------------------------------------------
@app.route("/api/upload_music", methods=["POST"])
def api_upload_music():
    job_id = request.form.get("job_id")
    job = JOBS.get(job_id)
    if not job or not job.get("prepared"):
        return jsonify({"error": "Trabajo no encontrado o expirado."}), 404
    if "music" not in request.files:
        return jsonify({"error": "No se recibio ningun archivo de musica."}), 400
    try:
        prepared = job["prepared"]
        file = request.files["music"]
        ext = Path(secure_filename(file.filename or "musica.mp3")).suffix.lower() or ".mp3"
        if ext not in (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"):
            return jsonify({"error": "Formato no valido. Usa MP3, WAV, M4A, AAC, OGG o FLAC."}), 400
        dest = prepared.job_dir / f"musica{ext}"
        file.save(str(dest))
        prepared.music_path = dest
        return jsonify({"ok": True, "music_file": dest.name})
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 400


# --------------------------------------------------------------------------
#  Quitar la musica de fondo
# --------------------------------------------------------------------------
@app.route("/api/remove_music", methods=["POST"])
def api_remove_music():
    data = request.get_json(force=True) or {}
    job = JOBS.get(data.get("job_id"))
    if not job or not job.get("prepared"):
        return jsonify({"error": "Trabajo no encontrado o expirado."}), 404
    job["prepared"].music_path = None
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
#  Regenerar la imagen de una escena
# --------------------------------------------------------------------------
@app.route("/api/regenerate_image", methods=["POST"])
def api_regenerate_image():
    data = request.get_json(force=True) or {}
    job_id = data.get("job_id")
    job = JOBS.get(job_id)
    if not job or not job.get("prepared"):
        return jsonify({"error": "Trabajo no encontrado o expirado."}), 404

    try:
        index = int(data.get("index"))
        mode = (data.get("mode") or "hybrid").lower()
        new_prompt = data.get("prompt")
        attempt = int(data.get("attempt") or 0)
        result = regenerate_scene_image(
            job["prepared"], index, mode=mode, new_prompt=new_prompt, attempt=attempt
        )
        job["review"] = _review_payload(job_id)
        return jsonify({
            "index": index,
            "image_file": Path(result.path).name,
            "source": result.source,
        })
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 400


# --------------------------------------------------------------------------
#  Subir una imagen propia para una escena
# --------------------------------------------------------------------------
@app.route("/api/upload_image", methods=["POST"])
def api_upload_image():
    job_id = request.form.get("job_id")
    job = JOBS.get(job_id)
    if not job or not job.get("prepared"):
        return jsonify({"error": "Trabajo no encontrado o expirado."}), 404
    if "image" not in request.files:
        return jsonify({"error": "No se recibio ninguna imagen."}), 400

    try:
        index = int(request.form.get("index"))
        prepared = job["prepared"]
        file = request.files["image"]
        ext = Path(secure_filename(file.filename or "img.jpg")).suffix.lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            return jsonify({"error": "Formato no valido. Usa JPG, PNG o WEBP."}), 400
        dest = prepared.job_dir / "images" / f"img_{index:02d}_subida{ext}"
        file.save(str(dest))
        set_scene_image(prepared, index, dest, source="subida")
        job["review"] = _review_payload(job_id)
        return jsonify({"index": index, "image_file": dest.name, "source": "subida"})
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 400


# --------------------------------------------------------------------------
#  Editar el dialogo (texto narrado) de una escena
# --------------------------------------------------------------------------
@app.route("/api/update_scene", methods=["POST"])
def api_update_scene():
    data = request.get_json(force=True) or {}
    job_id = data.get("job_id")
    job = JOBS.get(job_id)
    if not job or not job.get("prepared"):
        return jsonify({"error": "Trabajo no encontrado o expirado."}), 404
    try:
        index = int(data.get("index"))
        text = data.get("text") or ""
        update_scene_text(job["prepared"], index, text)
        job["review"] = _review_payload(job_id)
        return jsonify({"ok": True, "review": job["review"]})
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 400


# --------------------------------------------------------------------------
#  Eliminar una escena completa (imagen + dialogo)
# --------------------------------------------------------------------------
@app.route("/api/delete_scene", methods=["POST"])
def api_delete_scene():
    data = request.get_json(force=True) or {}
    job_id = data.get("job_id")
    job = JOBS.get(job_id)
    if not job or not job.get("prepared"):
        return jsonify({"error": "Trabajo no encontrado o expirado."}), 404
    try:
        index = int(data.get("index"))
        delete_scene(job["prepared"], index)
        job["review"] = _review_payload(job_id)
        return jsonify({"ok": True, "review": job["review"]})
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 400


# --------------------------------------------------------------------------
#  PASO 2: ensamblar el video final
# --------------------------------------------------------------------------
@app.route("/api/assemble", methods=["POST"])
def api_assemble():
    data = request.get_json(force=True) or {}
    job_id = data.get("job_id")
    job = JOBS.get(job_id)
    if not job or not job.get("prepared"):
        return jsonify({"error": "Trabajo no encontrado o expirado."}), 404

    # Modo y volumen de musica (ajustables en la pantalla de revision)
    if data.get("music_mode"):
        job["options"]["music_mode"] = data.get("music_mode")
    if data.get("music_volume") is not None:
        try:
            job["options"]["music_volume"] = float(data.get("music_volume"))
        except (TypeError, ValueError):
            pass

    # Voz y avatar (ahora tambien se pueden cambiar en la pantalla de revision)
    # voice == "" significa "mantener la voz actual" (no regenerar).
    job["options"]["override_voice"] = (data.get("voice") or "").strip()
    if "use_avatar" in data:
        job["options"]["use_avatar"] = bool(data.get("use_avatar"))

    job["phase"] = "assembling"
    job["status"] = "running"
    job["percent"] = 0
    job["message"] = "Preparando ensamblaje..."
    threading.Thread(target=_run_assemble, args=(job_id,), daemon=True).start()
    return jsonify({"job_id": job_id})


def _run_assemble(job_id: str) -> None:
    job = JOBS[job_id]
    options = job["options"]

    def progress(msg: str, pct: int) -> None:
        job["message"] = msg
        job["percent"] = pct

    try:
        result = assemble_prepared(
            job["prepared"],
            subtitle_color=options["subtitle_color"],
            subtitle_position=options["subtitle_position"],
            use_avatar=options["use_avatar"],
            voice=options.get("override_voice") or None,
            music_mode=options.get("music_mode", "auto"),
            music_volume=float(options.get("music_volume", 0.15)),
            aspect=options.get("aspect", "9:16"),
            progress=progress,
        )
        job["status"] = "done"
        job["phase"] = "done"
        job["percent"] = 100
        job["message"] = "Listo!"
        job["result"] = {
            "video_file": result.video_path.name,
            "title": result.title,
            "narration": result.narration,
            "titles": result.titles,
            "hashtags": result.hashtags,
            "duration": round(result.duration, 1),
            "used_avatar": result.used_avatar,
        }
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        job["status"] = "error"
        job["error"] = str(exc)


# --------------------------------------------------------------------------
#  Estado de un trabajo
# --------------------------------------------------------------------------
@app.route("/api/status/<job_id>")
def api_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Trabajo no encontrado"}), 404
    return jsonify({
        "status": job["status"],
        "phase": job["phase"],
        "message": job["message"],
        "percent": job["percent"],
        "error": job["error"],
        "draft": job.get("draft"),
        "review": job["review"],
        "result": job["result"],
    })


# --------------------------------------------------------------------------
#  Servir imagenes de previsualizacion (durante la revision)
# --------------------------------------------------------------------------
@app.route("/preview/<job_id>/<path:filename>")
def serve_preview(job_id: str, filename: str):
    job = JOBS.get(job_id)
    if not job or not job.get("prepared"):
        return "No encontrado", 404
    images_dir = job["prepared"].job_dir / "images"
    resp = send_from_directory(images_dir, filename)
    resp.headers["Cache-Control"] = "no-store"
    return resp


# --------------------------------------------------------------------------
#  Servir y descargar los videos finales
# --------------------------------------------------------------------------
@app.route("/video/<path:filename>")
def serve_video(filename: str):
    return send_from_directory(settings.output_dir, filename)


@app.route("/download/<path:filename>")
def download_video(filename: str):
    return send_from_directory(settings.output_dir, filename, as_attachment=True)


def _open_browser():
    try:
        import webbrowser
        webbrowser.open("http://localhost:5000")
    except Exception:
        pass


if __name__ == "__main__":
    print("=" * 60)
    print("  ViroFeed AI Personal")
    print("  VERSION DEL CODIGO: 18 (lector de YouTube resistente a bloqueos)")
    print("  Abriendo en tu navegador: http://localhost:5000")
    print("  (Para cerrar el programa, cierra esta ventana)")
    print("=" * 60)
    threading.Timer(1.5, _open_browser).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
