"""Persistent user settings."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

APP_NAME = "TikTokLiveReader"
DEFAULT_QUEUE_SIZE = 10


def config_path() -> Path:
    """Return the writable data path beside the source or packaged app."""
    if getattr(sys, "frozen", False):
        app_dir = Path(sys.executable).resolve().parent
    else:
        app_dir = Path(__file__).resolve().parent.parent
    return app_dir / "data" / "config.json"


def _legacy_config_path() -> Path:
    base = os.environ.get("APPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "CJVM" / APP_NAME / "config.json"


def default_config() -> dict[str, Any]:
    return {
        "version": 1,
        "username": "",
        "voice_names": [],
        "voice_mode": "per_user",
        "volume": 75,
        "rate": 0,
        "profile": "natural",
        "speak_usernames": True,
        "max_comment_length": 300,
        "queue_size": DEFAULT_QUEUE_SIZE,
        "tts_provider": "sapi",
        "voice_profiles": {},
    }


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load and validate saved settings, or return first-run defaults."""
    target = path or config_path()
    if not target.exists() and path is None:
        legacy_target = _legacy_config_path()
        if legacy_target.exists():
            config = _read_config(legacy_target)
            save_config(config, target)
            return config
    if not target.exists():
        return default_config()
    return _read_config(target)


def _read_config(target: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"No se pudo leer la configuración ({target}): {exc}") from exc
    if not isinstance(loaded, dict) or loaded.get("version") != 1:
        raise ValueError(f"El formato de configuración no es compatible: {target}")

    config = default_config()
    config.update(loaded)
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    if not isinstance(config["username"], str):
        raise ValueError("El nombre de usuario guardado no es válido.")
    if not isinstance(config["voice_names"], list) or any(
        not isinstance(name, str) for name in config["voice_names"]
    ):
        raise ValueError("La lista de voces guardada no es válida.")
    if config["voice_mode"] not in {"per_user", "rotate"}:
        raise ValueError("El modo de selección de voz guardado no es válido.")
    if isinstance(config["volume"], bool) or not isinstance(config["volume"], int):
        raise ValueError("El volumen guardado no es válido.")
    if not 0 <= config["volume"] <= 100:
        raise ValueError("El volumen debe estar entre 0 y 100.")
    if isinstance(config["rate"], bool) or not isinstance(config["rate"], int):
        raise ValueError("La velocidad guardada no es válida.")
    if not -10 <= config["rate"] <= 10:
        raise ValueError("La velocidad debe estar entre -10 y 10.")
    if not isinstance(config["speak_usernames"], bool):
        raise ValueError("La opción de leer nombres guardada no es válida.")
    if (
        isinstance(config["max_comment_length"], bool)
        or not isinstance(config["max_comment_length"], int)
        or not 20 <= config["max_comment_length"] <= 1000
    ):
        raise ValueError("El límite de longitud del comentario no es válido.")
    if (
        isinstance(config["queue_size"], bool)
        or not isinstance(config["queue_size"], int)
        or not 1 <= config["queue_size"] <= 100
    ):
        raise ValueError("La cola debe tener entre 1 y 100 comentarios.")
    if not isinstance(config["profile"], str) or config["profile"] not in {
        "natural",
        "ágil",
        "agil",
        "pausada",
        "energética",
        "energetica",
    }:
        raise ValueError("El perfil de voz guardado no es válido.")
    if not isinstance(config["tts_provider"], str) or config["tts_provider"] not in {
        "sapi",
        "piper",
        "elevenlabs",
    }:
        raise ValueError("El proveedor de voz guardado no es válido.")
    if not isinstance(config["voice_profiles"], dict) or any(
        not isinstance(name, str)
        or not isinstance(profile, str)
        or profile
        not in {
            "natural",
            "ágil",
            "agil",
            "pausada",
            "energética",
            "energetica",
        }
        for name, profile in config["voice_profiles"].items()
    ):
        raise ValueError("Los perfiles por voz guardados no son válidos.")


def save_config(config: dict[str, Any], path: Path | None = None) -> Path:
    """Atomically save validated settings without exposing a partial JSON file."""
    validate_config(config)
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            json.dump(config, temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
            temp_name = temp_file.name
        os.replace(temp_name, target)
    except OSError as exc:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
        raise OSError(f"No se pudo guardar la configuración ({target}): {exc}") from exc
    return target
