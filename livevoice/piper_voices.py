"""Optional, user-installed offline Piper voice models."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from .config import config_path

_REPOSITORY = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"
_CATALOG: dict[str, dict[str, str]] = {
    "es_ES-carlfm-x_low": {
        "name": "Carl FM (España)",
        "language": "Español de España",
        "quality": "Básica / rápida",
        "folder": "es/es_ES/carlfm/x_low",
        "size": "28 MB",
    },
    "es_ES-davefx-medium": {
        "name": "Dave FX (España)",
        "language": "Español de España",
        "quality": "Media",
        "folder": "es/es_ES/davefx/medium",
        "size": "63 MB",
    },
    "es_MX-ald-medium": {
        "name": "Ald (México)",
        "language": "Español de México",
        "quality": "Media",
        "folder": "es/es_MX/ald/medium",
        "size": "63 MB",
    },
    "es_MX-claude-high": {
        "name": "Claude (México)",
        "language": "Español de México",
        "quality": "Alta",
        "folder": "es/es_MX/claude/high",
        "size": "63 MB",
    },
    "en_US-lessac-medium": {
        "name": "Lessac (Estados Unidos)",
        "language": "Inglés de Estados Unidos",
        "quality": "Media",
        "folder": "en/en_US/lessac/medium",
        "size": "63 MB",
    },
}


def catalog() -> list[dict[str, str]]:
    return [{"id": model_id, **details} for model_id, details in _CATALOG.items()]


def voices_directory() -> Path:
    return config_path().parent / "voices"


def installed_voices() -> list[dict[str, str]]:
    voices = []
    for item in catalog():
        model_path = voices_directory() / item["id"] / f"{item['id']}.onnx"
        metadata_path = Path(f"{model_path}.json")
        if model_path.is_file() and metadata_path.is_file():
            voices.append(item)
    return voices


def _download(url: str, destination: Path, max_bytes: int) -> None:
    request = Request(url, headers={"User-Agent": "TikTokLiveReader/1.0"})
    try:
        with urlopen(request, timeout=45) as response:
            advertised_size = response.headers.get("Content-Length")
            if advertised_size and int(advertised_size) > max_bytes:
                raise ValueError("El archivo de voz excede el tamaño permitido.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as output:
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("El archivo de voz excede el tamaño permitido.")
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
    except (OSError, URLError, TimeoutError) as exc:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"No se pudo descargar el archivo de voz: {exc}") from exc
    except ValueError:
        destination.unlink(missing_ok=True)
        raise


def download_voice(model_id: str) -> Path:
    """Install an allow-listed Piper model and its configuration/license card."""
    details = _CATALOG.get(model_id)
    if details is None:
        raise ValueError("La voz solicitada no está en el catálogo permitido.")

    voice_dir = voices_directory() / model_id
    model_path = voice_dir / f"{model_id}.onnx"
    metadata_path = Path(f"{model_path}.json")
    card_path = voice_dir / "MODEL_CARD"
    if model_path.is_file() and metadata_path.is_file() and card_path.is_file():
        return model_path

    voice_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []
    model_files = (
        (model_path, 100 * 1024 * 1024),
        (metadata_path, 1024 * 1024),
        (card_path, 64 * 1024),
    )
    try:
        for destination, limit in model_files:
            if destination.exists():
                continue
            file_name = destination.name
            url = f"{_REPOSITORY}/{details['folder']}/{file_name}"
            with tempfile.NamedTemporaryFile(
                dir=voice_dir, prefix=".download-", suffix=".tmp", delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
            try:
                _download(url, temporary_path, limit)
                if destination == metadata_path:
                    json.loads(temporary_path.read_text(encoding="utf-8"))
                temporary_path.replace(destination)
                downloaded.append(destination)
            finally:
                temporary_path.unlink(missing_ok=True)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
        for path in downloaded:
            path.unlink(missing_ok=True)
        raise
    return model_path


def remove_voice(model_id: str) -> None:
    if model_id not in _CATALOG:
        raise ValueError("La voz solicitada no está en el catálogo permitido.")
    voice_dir = voices_directory() / model_id
    for path in voice_dir.iterdir():
        if path.is_file():
            path.unlink()
    voice_dir.rmdir()


def voice_path(model_id: str) -> Path:
    if model_id not in _CATALOG:
        raise ValueError("La voz solicitada no está en el catálogo permitido.")
    path = voices_directory() / model_id / f"{model_id}.onnx"
    if not path.is_file() or not Path(f"{path}.json").is_file():
        raise RuntimeError(
            f"La voz {model_id} no está descargada. Instálala desde Ajustes > Voces."
        )
    return path


def voice_details(model_id: str) -> dict[str, Any]:
    """Return model metadata without accepting an arbitrary filesystem path."""
    voice_path(model_id)
    return _CATALOG[model_id]
