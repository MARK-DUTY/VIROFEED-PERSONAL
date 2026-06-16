"""
Carga y valida la configuracion desde el archivo .env

Este modulo centraliza TODA la configuracion del programa para que el resto
del codigo simplemente importe `settings` y use sus valores.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Carpeta raiz del proyecto (donde vive este programa)
ROOT_DIR = Path(__file__).resolve().parent.parent

# Cargar variables del archivo .env (si existe)
load_dotenv(ROOT_DIR / ".env")


def _get_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    return value in ("1", "true", "yes", "si", "sí", "on")


@dataclass
class Settings:
    """Todos los ajustes del programa en un solo lugar."""

    # --- Claves de APIs ---
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", "").strip())
    groq_model: str = field(default_factory=lambda: os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip())
    pexels_api_key: str = field(default_factory=lambda: os.getenv("PEXELS_API_KEY", "").strip())
    pixabay_api_key: str = field(default_factory=lambda: os.getenv("PIXABAY_API_KEY", "").strip())

    # --- Voz ---
    tts_voice: str = field(default_factory=lambda: os.getenv("TTS_VOICE", "es-MX-JorgeNeural").strip())
    tts_rate: str = field(default_factory=lambda: os.getenv("TTS_RATE", "+8%").strip())

    # --- Avatar ---
    avatar_enabled: bool = field(default_factory=lambda: _get_bool("AVATAR_ENABLED", False))
    avatar_provider: str = field(default_factory=lambda: os.getenv("AVATAR_PROVIDER", "did").strip())
    did_api_key: str = field(default_factory=lambda: os.getenv("DID_API_KEY", "").strip())

    # --- Video ---
    video_duration: int = field(default_factory=lambda: int(os.getenv("VIDEO_DURATION", "45") or 45))
    script_style: str = field(default_factory=lambda: os.getenv("SCRIPT_STYLE", "breaking").strip())
    call_to_action: str = field(default_factory=lambda: os.getenv("CALL_TO_ACTION", "Sigueme para mas noticias").strip())

    # --- Carpetas de trabajo ---
    root_dir: Path = ROOT_DIR
    output_dir: Path = ROOT_DIR / "output"
    work_dir: Path = ROOT_DIR / "work"
    assets_dir: Path = ROOT_DIR / "assets"

    def __post_init__(self) -> None:
        # Crear carpetas necesarias si no existen
        for d in (self.output_dir, self.work_dir, self.assets_dir):
            d.mkdir(parents=True, exist_ok=True)

    # --- Validaciones utiles ---
    def missing_keys(self) -> list[str]:
        """Devuelve la lista de claves obligatorias que faltan."""
        missing = []
        if not self.groq_api_key or self.groq_api_key.startswith("PEGA_AQUI"):
            missing.append("GROQ_API_KEY")
        if not self.pexels_api_key or self.pexels_api_key.startswith("PEGA_AQUI"):
            missing.append("PEXELS_API_KEY")
        if self.avatar_enabled and not self.did_api_key:
            missing.append("DID_API_KEY (porque AVATAR_ENABLED=true)")
        return missing

    def reload(self) -> "Settings":
        """Vuelve a leer el archivo .env (util si el usuario lo edita)."""
        load_dotenv(ROOT_DIR / ".env", override=True)
        return Settings()


# Instancia global que usa todo el programa
settings = Settings()
