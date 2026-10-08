"""Lazy TikTok LIVE chat connection with bounded speech queue and retries."""

from __future__ import annotations

import asyncio
from collections import deque
import itertools
import queue
import re
import threading
import time
import unicodedata
from collections.abc import Callable
from typing import Any

from .config import DEFAULT_QUEUE_SIZE
from .speech import SpeechWorker

MAX_QUEUED_COMMENTS = DEFAULT_QUEUE_SIZE
MAX_SEEN_COMMENT_IDS = 2048
_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._]{1,24}$")
_STATUS_LABELS = {
    "connecting": "CONECTANDO",
    "connected": "CONECTADO",
    "error": "ERROR",
    "warning": "AVISO",
    "retry": "REINTENTO",
}


def normalize_username(username: str) -> str:
    normalized = username.strip().lstrip("@")
    if not _USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Usuario no válido. Usa de 1 a 24 letras, números, puntos o guiones bajos."
        )
    return normalized


def _spoken_nickname(nickname: str) -> str:
    normalized = unicodedata.normalize("NFKC", nickname)
    readable: list[str] = []
    previous_was_letter = False
    for character in normalized:
        category = unicodedata.category(character)
        if category.startswith("L") and unicodedata.name(
            character, ""
        ).startswith("LATIN "):
            readable.append(character)
            previous_was_letter = True
        elif category.startswith("M") and previous_was_letter:
            readable.append(character)
        elif character.isascii() and character.isdigit():
            readable.append(character)
            previous_was_letter = False
        elif character in " ._-'":
            if readable and readable[-1] != " ":
                readable.append(" ")
            previous_was_letter = False
        else:
            previous_was_letter = False
    return "".join(readable).strip()[:40]


def _voice_for_speaker(
    nickname: str, voice_names: list[str], voice_mode: str, cycle: Any
) -> str:
    if not voice_names:
        raise ValueError("Selecciona al menos una voz instalada en Ajustes.")
    if voice_mode == "rotate":
        return next(cycle)
    index = sum((position + 1) * ord(char) for position, char in enumerate(nickname))
    return voice_names[index % len(voice_names)]


def speak_comment(
    nickname: str,
    comment: str,
    config: dict[str, Any],
    worker: SpeechWorker,
    cycle: Any,
) -> None:
    text = comment.strip()
    if not text:
        return
    text = text[: config["max_comment_length"]]
    voice = _voice_for_speaker(
        nickname, config["voice_names"], config["voice_mode"], cycle
    )
    voice_profile = config.get("voice_profiles", {}).get(voice)
    rate = config["rate"]
    if voice_profile:
        rate = {
            "natural": 0,
            "ágil": 2,
            "agil": 2,
            "pausada": -2,
            "energética": 1,
            "energetica": 1,
        }[voice_profile]
    spoken_name = _spoken_nickname(nickname)
    spoken_text = (
        f"{spoken_name}: {text}"
        if config["speak_usernames"] and spoken_name
        else text
    )
    worker.speak(spoken_text, voice, config["volume"], rate)


def _load_tiktok_client() -> tuple[Any, Any, Any]:
    """Import the connector only after the user asks to connect."""
    try:
        from TikTokLive import TikTokLiveClient
        from TikTokLive.events import CommentEvent, ConnectEvent
    except ImportError as exc:
        raise RuntimeError(
            "Falta el conector de TikTok. Ejecuta primero setup.bat para instalar "
            "la única dependencia de conexión."
        ) from exc
    return TikTokLiveClient, CommentEvent, ConnectEvent


def _event_text(event: Any) -> tuple[str, str]:
    comment = str(getattr(event, "comment", "")).strip()
    user = getattr(event, "user", None)
    nickname = str(
        getattr(user, "nickname", None) or getattr(user, "unique_id", None) or ""
    ).strip()
    return nickname, comment


def _event_id(event: Any) -> str | None:
    common = getattr(event, "common", None)
    message_id = getattr(common, "msg_id", None)
    if message_id in (None, 0, ""):
        return None
    return str(message_id)


def _handle_console_key(
    key: str,
    comments: queue.Queue[tuple[str, str] | None],
    last_comment: tuple[str, str] | None,
    report: Callable[[str, str], None],
) -> None:
    key = key.casefold()
    if key == "r":
        if last_comment is None:
            report("info", "Todavía no hay comentarios para repetir.")
            return
        try:
            comments.put_nowait(last_comment)
        except queue.Full:
            report("warning", "La cola está llena; no se pudo repetir el comentario.")
        else:
            report("info", "Último comentario añadido de nuevo a la cola.")
    elif key == "s":
        try:
            comments.get_nowait()
        except queue.Empty:
            report("info", "No hay comentarios pendientes para saltar.")
        else:
            report("info", "Se omitió el siguiente comentario pendiente.")
    elif key == "?":
        report("info", "Teclas: R repetir último comentario leído | S saltar el siguiente pendiente.")


def connect_and_read(
    username: str,
    config: dict[str, Any],
    *,
    stop_event: threading.Event | None = None,
    on_status: Callable[[str, str], None] | None = None,
    comment_callback: Callable[[str, str], None] | None = None,
) -> None:
    normalized = normalize_username(username)
    client_type, comment_event, connect_event = _load_tiktok_client()
    stop_event = stop_event or threading.Event()
    comments: queue.Queue[tuple[str, str] | None] = queue.Queue(
        maxsize=config.get("queue_size", MAX_QUEUED_COMMENTS)
    )
    worker = SpeechWorker(config)
    stop_speech = threading.Event()
    cycle = itertools.cycle(config["voice_names"])
    last_spoken_comment: tuple[str, str] | None = None
    last_spoken_lock = threading.Lock()

    def report(level: str, message: str) -> None:
        print(f"[{_STATUS_LABELS.get(level, level.upper())}] {message}")
        if on_status:
            on_status(level, message)

    def speech_loop() -> None:
        nonlocal last_spoken_comment
        while not stop_speech.is_set():
            try:
                item = comments.get(timeout=0.25)
            except queue.Empty:
                continue
            if item is None:
                return
            with last_spoken_lock:
                last_spoken_comment = item
            try:
                speak_comment(item[0], item[1], config, worker, cycle)
            except RuntimeError as exc:
                if stop_event.is_set():
                    return
                report("error", f"Error de voz: {exc}")
                stop_speech.set()
                stop_event.set()
                return

    speech_thread = threading.Thread(
        target=speech_loop, name="speech-worker", daemon=True
    )
    speech_thread.start()
    last_comment: tuple[str, str] | None = None
    last_comment_at = 0.0
    seen_comment_ids: set[str] = set()
    seen_comment_order: deque[str] = deque()

    keyboard_thread: threading.Thread | None = None
    try:
        def console_controls() -> None:
            try:
                import msvcrt
            except ImportError as exc:
                report("warning", f"Los controles de teclado no están disponibles: {exc}")
                return

            while not stop_event.is_set():
                if not msvcrt.kbhit():
                    stop_event.wait(0.1)
                    continue
                key = msvcrt.getwch()
                if key in {"\x00", "\xe0"}:
                    msvcrt.getwch()
                    continue
                with last_spoken_lock:
                    current_comment = last_spoken_comment
                _handle_console_key(
                    key.casefold(), comments, current_comment, report
                )

        print(
            "[TECLAS] R = repetir el último comentario leído | "
            "S = saltar el siguiente pendiente | Ctrl+C = detener."
        )
        print(
            "[TECLAS] Haz clic primero en esta ventana de consola. "
            "No se capturan teclas de otras ventanas."
        )
        keyboard_thread = threading.Thread(
            target=console_controls, name="console-controls", daemon=True
        )
        keyboard_thread.start()
        retry_delay = 2
        while not stop_event.is_set():
            client = client_type(unique_id=f"@{normalized}")
            connected = threading.Event()
            connected_at = 0.0
            client_finished = threading.Event()

            def interrupt_client() -> None:
                while not client_finished.is_set():
                    if not stop_event.wait(0.1):
                        continue
                    loop = getattr(client, "_asyncio_loop", None)
                    deadline = time.monotonic() + 10
                    while (
                        not client_finished.is_set()
                        and loop is not None
                        and not loop.is_running()
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.05)
                    if loop is not None and loop.is_running():
                        try:
                            asyncio.run_coroutine_threadsafe(
                                client.disconnect(), loop
                            ).result(timeout=5)
                        except TimeoutError:
                            report("warning", "TikTok tardó en cerrar la conexión.")
                        except Exception as exc:
                            if not client_finished.is_set():
                                report(
                                    "warning",
                                    f"No se pudo cerrar la conexión limpiamente: {exc}",
                                )
                    return

            interrupt_thread = threading.Thread(
                target=interrupt_client,
                name="connection-stop",
                daemon=True,
            )
            interrupt_thread.start()

            async def on_connect(event: Any) -> None:
                nonlocal connected_at
                connected_at = time.monotonic()
                connected.set()
                report("connected", f"Conectado a @{normalized}. Leyendo comentarios.")

            async def handle_comment(event: Any) -> None:
                nonlocal last_comment, last_comment_at
                if stop_speech.is_set():
                    return
                nickname, text = _event_text(event)
                if not text:
                    return
                message_id = _event_id(event)
                if message_id is not None:
                    if message_id in seen_comment_ids:
                        return
                    seen_comment_ids.add(message_id)
                    seen_comment_order.append(message_id)
                    if len(seen_comment_order) > MAX_SEEN_COMMENT_IDS:
                        seen_comment_ids.remove(seen_comment_order.popleft())
                fingerprint = (nickname, text)
                now = time.monotonic()
                if (
                    message_id is None
                    and fingerprint == last_comment
                    and now - last_comment_at < 1.5
                ):
                    return
                last_comment, last_comment_at = fingerprint, now
                if comment_callback:
                    comment_callback(nickname, text)
                else:
                    print(f"[{nickname or 'usuario'}] {text}")
                try:
                    comments.put_nowait((nickname, text))
                except queue.Full:
                    report("warning", "La voz va retrasada; se omitió un comentario.")

            client.add_listener(connect_event, on_connect)
            client.add_listener(comment_event, handle_comment)
            report("connecting", f"Conectando con @{normalized}…")
            try:
                client.run(
                    fetch_live_check=True,
                    fetch_room_info=False,
                    fetch_gift_info=False,
                )
                if stop_event.is_set():
                    break
                if stop_speech.is_set():
                    raise RuntimeError("El sintetizador dejó de funcionar.")
                if connected.is_set():
                    report("warning", "La conexión terminó; intentando reconectar.")
                    if time.monotonic() - connected_at >= 60:
                        retry_delay = 2
                else:
                    report("warning", "La conexión terminó antes de conectar.")
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                if stop_event.is_set():
                    break
                if stop_speech.is_set():
                    raise RuntimeError(
                        "El sintetizador dejó de funcionar; revisa el dispositivo "
                        "de salida de audio de Windows."
                    ) from exc
                report(
                    "error",
                    f"Problema de conexión ({type(exc).__name__}): {exc}",
                )
            finally:
                client_finished.set()
                interrupt_thread.join(timeout=1)
            if stop_event.is_set():
                break
            report("retry", f"Nuevo intento en {retry_delay} s.")
            if stop_event.wait(retry_delay):
                break
            retry_delay = min(retry_delay * 2, 60)
    finally:
        stop_speech.set()
        stop_event.set()
        worker.stop()
        try:
            comments.put_nowait(None)
        except queue.Full:
            pass
        speech_thread.join(timeout=2)
        if keyboard_thread is not None:
            keyboard_thread.join(timeout=1)


def run_test_comment(config: dict[str, Any]) -> None:
    worker = SpeechWorker(config)
    try:
        if not config["voice_names"]:
            raise RuntimeError("Selecciona al menos una voz en Ajustes.")
        for voice in config["voice_names"]:
            worker.speak(
                "Prueba de voz. Made by CJVM, HoJ.",
                voice,
                config["volume"],
                config["rate"],
            )
    finally:
        worker.stop()
