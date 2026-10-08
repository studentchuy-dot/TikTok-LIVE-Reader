"""Windows user-scoped DPAPI storage for third-party API credentials."""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import tempfile
from typing import Any

from .config import config_path


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _dpapi() -> Any:
    if os.name != "nt":
        raise RuntimeError("El guardado seguro de claves requiere Windows.")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def _transform(data: bytes, protect: bool) -> bytes:
    crypt32, kernel32 = _dpapi()
    source_buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(
        len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte))
    )
    destination = _DataBlob()
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    function.argtypes = (
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR if protect else ctypes.POINTER(wintypes.LPWSTR),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    )
    function.restype = wintypes.BOOL
    success = function(
        ctypes.byref(source),
        "TikTok LIVE Reader" if protect else None,
        None,
        None,
        None,
        1,
        ctypes.byref(destination),
    )
    if not success:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        kernel32.LocalFree(destination.pbData)


def _key_path() -> Path:
    return config_path().parent / "elevenlabs.key"


def store_api_key(api_key: str) -> Path:
    if not api_key.strip():
        raise ValueError("La API key está vacía.")
    encrypted = _transform(api_key.strip().encode("utf-8"), protect=True)
    target = _key_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, prefix=".key-", delete=False
        ) as temp_file:
            temp_file.write(base64.b64encode(encrypted))
            temp_name = temp_file.name
        os.replace(temp_name, target)
    except OSError as exc:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)
        raise OSError(f"No se pudo guardar la API key cifrada: {exc}") from exc
    return target


def load_api_key() -> str:
    target = _key_path()
    try:
        encrypted = base64.b64decode(target.read_bytes(), validate=True)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "No hay una API key configurada. Entra a Ajustes > ElevenLabs."
        ) from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError("No se pudo leer la API key cifrada.") from exc
    try:
        return _transform(encrypted, protect=False).decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeError(
            "Windows no pudo descifrar la API key para este usuario."
        ) from exc


def delete_api_key() -> None:
    _key_path().unlink(missing_ok=True)
