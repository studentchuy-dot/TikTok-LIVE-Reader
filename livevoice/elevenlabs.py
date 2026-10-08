"""Small standard-library client for the free-tier ElevenLabs speech API."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request
from urllib.request import HTTPRedirectHandler, build_opener

_API = "https://api.elevenlabs.io"
_MAX_RESPONSE_BYTES = 12 * 1024 * 1024
_VOICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class _TrustedApiRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        if not new_url.startswith(f"{_API}/"):
            raise RuntimeError("ElevenLabs solicitó una redirección no confiable.")
        return super().redirect_request(
            request, file_pointer, code, message, headers, new_url
        )


def _request(
    path: str, api_key: str, *, body: dict[str, Any] | None = None, timeout: int = 20
) -> tuple[bytes, str]:
    headers = {"xi-api-key": api_key, "Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    request = Request(f"{_API}{path}", data=data, headers=headers)
    try:
        with build_opener(_TrustedApiRedirects()).open(
            request, timeout=timeout
        ) as response:
            content_type = response.headers.get("Content-Type", "")
            payload = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(payload) > _MAX_RESPONSE_BYTES:
                raise RuntimeError("ElevenLabs devolvió una respuesta demasiado grande.")
            return payload, content_type
    except HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", errors="replace")
        if exc.code in {401, 403}:
            raise RuntimeError(
                "ElevenLabs rechazó la API key o no tiene permisos de usuario/TTS."
            ) from exc
        if exc.code == 429:
            raise RuntimeError(
                "ElevenLabs alcanzó el límite gratuito o de solicitudes. "
                "Revisa tu cuota antes de continuar."
            ) from exc
        raise RuntimeError(
            f"ElevenLabs respondió HTTP {exc.code}: {detail[:500]}"
        ) from exc
    except (TimeoutError, URLError, OSError) as exc:
        raise RuntimeError(f"No se pudo contactar a ElevenLabs: {exc}") from exc


def verify_free_account(api_key: str) -> dict[str, Any]:
    payload, _ = _request("/v1/user", api_key)
    try:
        user = json.loads(payload)
        subscription = user["subscription"]
        tier = subscription["tier"]
        status = subscription["status"]
        remaining = max(
            0,
            int(subscription["character_limit"])
            - int(subscription["character_count"]),
        )
        overage = subscription.get("max_credit_limit_extension")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("ElevenLabs devolvió información de cuenta incompleta.") from exc
    if tier != "free" or status != "free":
        raise RuntimeError(
            "Esta integración solo usa cuentas del nivel Free. "
            "Cambia al plan gratuito para activar esta opción."
        )
    if overage not in (0, "0"):
        raise RuntimeError(
            "No se pudo confirmar que los excedentes estén desactivados. "
            "Revisa los límites de facturación antes de usar ElevenLabs."
        )
    if remaining <= 0:
        raise RuntimeError("La cuota mensual gratuita de ElevenLabs está agotada.")
    return {
        "remaining_characters": remaining,
        "character_limit": int(subscription["character_limit"]),
        "character_count": int(subscription["character_count"]),
    }


def list_free_voices(api_key: str) -> list[dict[str, str]]:
    query = urlencode({"page_size": 100, "include_total_count": "false"})
    payload, _ = _request(f"/v2/voices?{query}", api_key)
    try:
        response = json.loads(payload)
        voices = response["voices"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("ElevenLabs devolvió una lista de voces ilegible.") from exc
    result = []
    for voice in voices:
        if not isinstance(voice, dict):
            continue
        available_tiers = voice.get("available_for_tiers")
        if not isinstance(available_tiers, list) or "free" not in available_tiers:
            continue
        voice_id = voice.get("voice_id")
        if not isinstance(voice_id, str) or not _VOICE_ID_PATTERN.fullmatch(voice_id):
            continue
        labels = voice.get("labels") or {}
        language = labels.get("language", "Idioma no especificado")
        accent = labels.get("accent")
        if accent:
            language = f"{language} ({accent})"
        result.append(
            {
                "id": voice_id,
                "name": str(voice.get("name") or voice_id),
                "language": str(language),
                "category": str(voice.get("category") or "voz"),
            }
        )
    return result


def synthesize(api_key: str, voice_id: str, text: str, speed: float) -> bytes:
    if not _VOICE_ID_PATTERN.fullmatch(voice_id):
        raise ValueError("El identificador de voz de ElevenLabs no es válido.")
    if not 0.7 <= speed <= 1.2:
        raise ValueError("La velocidad solicitada para ElevenLabs no es válida.")
    path = f"/v1/text-to-speech/{voice_id}?output_format=pcm_22050"
    request = Request(
        f"{_API}{path}",
        data=json.dumps(
            {
                "text": text,
                "model_id": "eleven_turbo_v2_5",
                "voice_settings": {"speed": speed},
            }
        ).encode("utf-8"),
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
    )
    try:
        with build_opener(_TrustedApiRedirects()).open(
            request, timeout=30
        ) as response:
            audio = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(audio) > _MAX_RESPONSE_BYTES:
                raise RuntimeError("ElevenLabs devolvió audio demasiado grande.")
            if not audio:
                raise RuntimeError("ElevenLabs devolvió audio vacío.")
            return audio
    except HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", errors="replace")
        if exc.code in {401, 403}:
            raise RuntimeError("ElevenLabs rechazó la API key o la voz elegida.") from exc
        if exc.code == 429:
            raise RuntimeError(
                "Se agotó la cuota gratuita o el límite de solicitudes de ElevenLabs."
            ) from exc
        raise RuntimeError(
            f"ElevenLabs respondió HTTP {exc.code}: {detail[:500]}"
        ) from exc
    except (TimeoutError, URLError, OSError) as exc:
        raise RuntimeError(f"No se pudo generar voz con ElevenLabs: {exc}") from exc
