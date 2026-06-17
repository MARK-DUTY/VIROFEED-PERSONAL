"""
ViroFeed AI Personal - Servidor web local (interfaz)

Este es el programa que ejecutas. Abre una pagina web en tu navegador donde
pegas la URL de una noticia y, con un clic, se genera el video.

Para arrancar:   python app.py
Luego abre:      http://localhost:5000
"""
from __future__ import annotations

import threading
import traceback
import uuid
import webbrowser
from pathlib import Path

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    send_from_directory,
)

from pipeline.config import settings
from pipeline.runner import create_video_from_url
from pipeline.voice import list_spanish_voices

app = Flask(__name__)

# Estado de los trabajos en curso (en memoria). clave = job_id
JOBS: dict[str, dict] = {}


# --------------------------------------------------------------------------
#  Paginas
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
#  API: iniciar un trabajo de generacion
# --------------------------------------------------------------------------
@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json(force=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Pega la URL de una noticia primero."}), 400

    # Recargar config por si el usuario edito el .env
    fresh = settings.reload()
    missing = fresh.missing_keys()
    if "GROQ_API_KEY" in missing or any("PEXELS" in m for m in missing):
        return jsonify({
            "error": "Faltan claves en tu archivo .env: " + ", ".join(missing)
        }), 400

    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"status": "running", "message": "Iniciando...", "percent": 0, "result": None, "error": None}

    options = {
        "duration": int(data.get("duration") or fresh.video_duration),
        "style": data.get("style") or fresh.script_style,
        "voice": data.get("voice") or fresh.tts_voice,
        "rate": data.get("rate") if data.get("rate") is not None else fresh.tts_rate,
        "cta": data.get("cta") or fresh.call_to_action,
        "subtitle_color": data.get("subtitle_color") or "amarillo",
        "subtitle_position": data.get("subtitle_position") or "center",
        "image_source": data.get("image_source") or fresh.image_source,
        "use_avatar": bool(data.get("use_avatar", fresh.avatar_enabled)),
    }

    thread = threading.Thread(target=_run_job, args=(job_id, url, options), daemon=True)
    thread.start()
    return jsonify({"job_id": job_id})


def _run_job(job_id: str, url: str, options: dict) -> None:
    def progress(msg: str, pct: int) -> None:
        JOBS[job_id]["message"] = msg
        JOBS[job_id]["percent"] = pct

    try:
        result = create_video_from_url(url, progress=progress, **options)
        JOBS[job_id]["status"] = "done"
        JOBS[job_id]["percent"] = 100
        JOBS[job_id]["message"] = "Listo!"
        JOBS[job_id]["result"] = {
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
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = str(exc)
        JOBS[job_id]["message"] = "Error"


# --------------------------------------------------------------------------
#  API: consultar el progreso de un trabajo
# --------------------------------------------------------------------------
@app.route("/api/status/<job_id>")
def api_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Trabajo no encontrado"}), 404
    return jsonify(job)


# --------------------------------------------------------------------------
#  Servir y descargar los videos generados
# --------------------------------------------------------------------------
@app.route("/video/<path:filename>")
def serve_video(filename: str):
    return send_from_directory(settings.output_dir, filename)


@app.route("/download/<path:filename>")
def download_video(filename: str):
    return send_from_directory(settings.output_dir, filename, as_attachment=True)


def _open_browser():
    try:
        webbrowser.open("http://localhost:5000")
    except Exception:
        pass


if __name__ == "__main__":
    print("=" * 60)
    print("  ViroFeed AI Personal")
    print("  VERSION DEL CODIGO: 2 (subtitulos con Plan B)")
    print("  Abriendo en tu navegador: http://localhost:5000")
    print("  (Para cerrar el programa, cierra esta ventana)")
    print("=" * 60)
    threading.Timer(1.5, _open_browser).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
