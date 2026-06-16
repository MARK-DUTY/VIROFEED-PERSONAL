"""
Paso opcional: AVATAR hablando (lip-sync).

Este modulo es el "interruptor" del avatar. Por defecto esta APAGADO
(AVATAR_ENABLED=false) y el programa genera videos faceless gratis e
ilimitados.

Cuando lo enciendes (AVATAR_ENABLED=true), usa un servicio en la nube
(D-ID) para animar UNA foto tuya con la voz generada. Tu PC no tiene tarjeta
grafica NVIDIA, por eso esta parte se hace en la nube y no en tu equipo.

NOTA: el plan gratis de estos servicios tiene un limite de videos al mes.
"""
from __future__ import annotations

import base64
import time
from pathlib import Path

import requests

from .config import settings

DID_API = "https://api.d-id.com"


def avatar_is_enabled() -> bool:
    return settings.avatar_enabled


def _did_headers() -> dict:
    key = settings.did_api_key.strip()
    # D-ID acepta la clave tal cual en formato Basic.
    if ":" in key:  # formato usuario:clave -> codificar a base64
        key = base64.b64encode(key.encode()).decode()
    return {
        "Authorization": f"Basic {key}",
        "Content-Type": "application/json",
        "accept": "application/json",
    }


def _upload_audio_did(audio_path: Path) -> str:
    """Sube el audio a D-ID y devuelve la URL que ellos generan."""
    url = f"{DID_API}/audios"
    headers = {"Authorization": _did_headers()["Authorization"], "accept": "application/json"}
    with open(audio_path, "rb") as f:
        files = {"audio": (Path(audio_path).name, f, "audio/mpeg")}
        resp = requests.post(url, headers=headers, files=files, timeout=120)
    if resp.status_code >= 400:
        raise RuntimeError(f"D-ID rechazo el audio ({resp.status_code}): {resp.text[:300]}")
    return resp.json()["url"]


def _upload_image_did(image_path: Path) -> str:
    url = f"{DID_API}/images"
    headers = {"Authorization": _did_headers()["Authorization"], "accept": "application/json"}
    with open(image_path, "rb") as f:
        files = {"image": (Path(image_path).name, f, "image/jpeg")}
        resp = requests.post(url, headers=headers, files=files, timeout=120)
    if resp.status_code >= 400:
        raise RuntimeError(f"D-ID rechazo la imagen ({resp.status_code}): {resp.text[:300]}")
    return resp.json()["url"]


def generate_avatar_video(
    audio_path: Path,
    face_image: Path,
    out_path: Path,
    timeout: int = 300,
) -> Path:
    """
    Crea un video del avatar (foto animada) hablando con la voz dada.

    audio_path : la voz generada (mp3)
    face_image : foto de la cara (assets/avatar.jpg)
    out_path   : donde guardar el .mp4 del avatar

    Devuelve la ruta del video del avatar.
    """
    if not settings.did_api_key:
        raise ValueError(
            "El avatar esta activado pero falta DID_API_KEY en tu .env. "
            "Crea una cuenta gratis en https://www.d-id.com y pega tu clave, "
            "o apaga el avatar con AVATAR_ENABLED=false."
        )
    face_image = Path(face_image)
    if not face_image.exists():
        raise ValueError(
            f"No encontre la foto del avatar en {face_image}. "
            "Coloca una foto tuya (cara visible) en assets/avatar.jpg"
        )

    # 1) Subir foto y audio a D-ID
    image_url = _upload_image_did(face_image)
    audio_url = _upload_audio_did(Path(audio_path))

    # 2) Crear el "talk"
    payload = {
        "source_url": image_url,
        "script": {"type": "audio", "audio_url": audio_url},
        "config": {"stitch": True},
    }
    resp = requests.post(f"{DID_API}/talks", headers=_did_headers(), json=payload, timeout=60)
    if resp.status_code >= 400:
        raise RuntimeError(f"D-ID no pudo crear el avatar ({resp.status_code}): {resp.text[:300]}")
    talk_id = resp.json()["id"]

    # 3) Esperar a que termine (polling)
    result_url = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{DID_API}/talks/{talk_id}", headers=_did_headers(), timeout=30)
        data = r.json()
        status = data.get("status")
        if status == "done":
            result_url = data.get("result_url")
            break
        if status in ("error", "rejected"):
            raise RuntimeError(f"D-ID fallo al generar el avatar: {data}")
        time.sleep(4)

    if not result_url:
        raise RuntimeError("D-ID tardo demasiado en generar el avatar (timeout).")

    # 4) Descargar el video del avatar
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    vid = requests.get(result_url, timeout=120)
    vid.raise_for_status()
    out_path.write_bytes(vid.content)
    return out_path
