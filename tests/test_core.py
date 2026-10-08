from __future__ import annotations

import asyncio
import ctypes
import io
import json
import os
import queue
import sys
import tempfile
import threading
import time
import types
import unittest
import wave
from array import array
from asyncio import run as run_async
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

from livevoice.app import _configure_piper, run as run_app
from livevoice.config import default_config, load_config, save_config
from livevoice.connector import (
    _handle_console_key,
    _spoken_nickname,
    connect_and_read,
    normalize_username,
    speak_comment,
)
from livevoice.elevenlabs import list_free_voices, verify_free_account
from livevoice.piper_voices import (
    catalog as piper_catalog,
    download_voice,
    installed_voices as list_installed_piper_voices,
    voice_path,
)
from livevoice.secrets_store import (
    delete_api_key,
    load_api_key,
    store_api_key,
)
from livevoice.speech import SpeechWorker, _play_wave
from main import _configure_console


class ConfigTests(unittest.TestCase):
    def test_queue_defaults_to_ten_and_rejects_out_of_range(self) -> None:
        config = default_config()
        self.assertEqual(config["queue_size"], 10)
        config["queue_size"] = 101
        with self.assertRaisesRegex(ValueError, "cola"):
            save_config(config, Path(tempfile.gettempdir()) / "unused-config.json")

    def test_migrates_legacy_settings_and_adds_new_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            legacy = root / "old-config.json"
            local = root / "data" / "config.json"
            old_config = default_config()
            old_config["username"] = "creator"
            del old_config["queue_size"]
            legacy.write_text(json.dumps(old_config), encoding="utf-8")

            with (
                patch("livevoice.config.config_path", return_value=local),
                patch("livevoice.config._legacy_config_path", return_value=legacy),
            ):
                migrated = load_config()

            self.assertEqual(migrated["username"], "creator")
            self.assertEqual(migrated["queue_size"], 10)
            self.assertEqual(load_config(local), migrated)

    def test_defaults_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "settings.json"
            config = default_config()
            config["username"] = "creator"
            save_config(config, target)
            self.assertEqual(load_config(target), config)

    def test_rejects_invalid_volume(self) -> None:
        config = default_config()
        config["volume"] = 101
        with self.assertRaisesRegex(ValueError, "volumen"):
            save_config(config, Path(tempfile.gettempdir()) / "unused-config.json")

    def test_rejects_unknown_tts_provider(self) -> None:
        config = default_config()
        config["tts_provider"] = "unknown"
        with self.assertRaisesRegex(ValueError, "proveedor"):
            save_config(config, Path(tempfile.gettempdir()) / "unused-config.json")


class VoiceProviderTests(unittest.TestCase):
    def test_piper_catalog_is_allow_listed_and_voice_path_rejects_unknown(self) -> None:
        voices = piper_catalog()
        self.assertGreaterEqual(len(voices), 4)
        with self.assertRaisesRegex(ValueError, "catálogo"):
            voice_path("../../outside")

    def test_free_elevenlabs_account_must_not_have_overage(self) -> None:
        response = {
            "subscription": {
                "tier": "free",
                "status": "free",
                "character_limit": 10000,
                "character_count": 250,
                "max_credit_limit_extension": 0,
            }
        }
        with patch("livevoice.elevenlabs._request", return_value=(json.dumps(response).encode(), "")):
            account = verify_free_account("unit-test-key")
        self.assertEqual(account["remaining_characters"], 9750)

        response["subscription"]["max_credit_limit_extension"] = "unlimited"
        with patch("livevoice.elevenlabs._request", return_value=(json.dumps(response).encode(), "")):
            with self.assertRaisesRegex(RuntimeError, "excedentes"):
                verify_free_account("unit-test-key")

    def test_elevenlabs_only_lists_voices_marked_free(self) -> None:
        response = {
            "voices": [
                {
                    "voice_id": "free-id",
                    "name": "Free voice",
                    "available_for_tiers": ["free", "starter"],
                    "labels": {"language": "Spanish"},
                },
                {
                    "voice_id": "paid-id",
                    "name": "Paid voice",
                    "available_for_tiers": ["starter"],
                },
            ]
        }
        with patch("livevoice.elevenlabs._request", return_value=(json.dumps(response).encode(), "")):
            voices = list_free_voices("unit-test-key")
        self.assertEqual([voice["id"] for voice in voices], ["free-id"])

    def test_piper_download_is_allow_listed_and_atomic_files_are_installed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            data_dir = Path(folder) / "data"
            with patch(
                "livevoice.piper_voices.config_path",
                return_value=data_dir / "config.json",
            ):
                def fake_download(url: str, destination: Path, limit: int) -> None:
                    self.assertTrue(url.startswith("https://huggingface.co/"))
                    self.assertGreater(limit, 0)
                    if url.endswith(".onnx.json"):
                        destination.write_text('{"audio":{"sample_rate":22050}}', encoding="utf-8")
                    else:
                        destination.write_bytes(b"test-file")

                with patch("livevoice.piper_voices._download", side_effect=fake_download):
                    model_path = download_voice("es_ES-carlfm-x_low")

                self.assertTrue(model_path.is_file())
                self.assertTrue(Path(f"{model_path}.json").is_file())
                self.assertIn(
                    "es_ES-carlfm-x_low",
                    [voice["id"] for voice in list_installed_piper_voices()],
                )

    def test_console_keys_repeat_last_comment_and_skip_pending_comment(self) -> None:
        comments: queue.Queue[tuple[str, str] | None] = queue.Queue(maxsize=3)
        comments.put_nowait(("Ana", "primero"))
        statuses: list[tuple[str, str]] = []
        report = lambda level, message: statuses.append((level, message))

        _handle_console_key("R", comments, ("Luis", "último"), report)
        self.assertEqual(comments.get_nowait(), ("Ana", "primero"))
        self.assertEqual(comments.get_nowait(), ("Luis", "último"))

        comments.put_nowait(("Eva", "pendiente"))
        _handle_console_key("s", comments, ("Luis", "último"), report)
        self.assertTrue(comments.empty())
        self.assertEqual(
            [level for level, _ in statuses],
            ["info", "info"],
        )

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI is required")
    def test_api_key_is_encrypted_for_current_windows_user(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with patch(
                "livevoice.secrets_store.config_path",
                return_value=Path(folder) / "data" / "config.json",
            ):
                key_path = store_api_key("fake-test-key")
                self.assertNotIn(b"fake-test-key", key_path.read_bytes())
                self.assertEqual(load_api_key(), "fake-test-key")
                delete_api_key()
                self.assertFalse(key_path.exists())

    def test_piper_worker_maps_each_profile_to_local_synthesis_speed(self) -> None:
        class FakePiperVoice:
            syn_configs: list[Any] = []

            def synthesize_wav(
                self, _text: str, destination: Any, syn_config: Any
            ) -> None:
                type(self).syn_configs.append(syn_config)
                destination.setnchannels(1)
                destination.setsampwidth(2)
                destination.setframerate(22050)
                destination.writeframes(array("h", [100]).tobytes())

        fake_voice = FakePiperVoice()
        config = default_config()
        voice_id = "es_ES-carlfm-x_low"
        config.update(tts_provider="piper")
        worker = SpeechWorker(config)
        with (
            patch("piper.PiperVoice.load", return_value=fake_voice),
            patch(
                "livevoice.piper_voices.voice_path",
                return_value=Path("voice.onnx"),
            ),
            patch("livevoice.speech._play_wave") as play,
        ):
            for profile in ("pausada", "natural", "energética", "ágil"):
                config["voice_profiles"][voice_id] = profile
                worker.speak("hola", voice_id, 75, 0)
        expected_scales = [1 / 0.9, 1.0, 1 / 1.05, 1 / 1.1]
        self.assertEqual(len(FakePiperVoice.syn_configs), 4)
        for syn_config, expected_scale in zip(
            FakePiperVoice.syn_configs, expected_scales
        ):
            self.assertAlmostEqual(syn_config.length_scale, expected_scale)
            self.assertEqual(syn_config.volume, 1.0)
        self.assertEqual(play.call_count, 4)

    def test_installed_piper_model_synthesizes_each_profile(self) -> None:
        installed = list_installed_piper_voices()
        if not installed:
            self.skipTest("No hay una voz Piper descargada para la prueba de integración.")

        voice_id = installed[0]["id"]
        config = default_config()
        config.update(
            tts_provider="piper",
            voice_names=[voice_id],
            voice_profiles={voice_id: "natural"},
        )
        worker = SpeechWorker(config)
        captured: list[bytes] = []
        durations: list[float] = []
        with patch(
            "livevoice.speech._play_wave",
            side_effect=lambda data, _volume, _stop_event: captured.append(data),
        ):
            for profile in ("pausada", "natural", "energética", "ágil"):
                config["voice_profiles"][voice_id] = profile
                worker.speak("Hola, esta es una prueba de ritmo.", voice_id, 50, 0)
                with wave.open(io.BytesIO(captured[-1]), "rb") as wav:
                    self.assertEqual(wav.getnchannels(), 1)
                    self.assertEqual(wav.getsampwidth(), 2)
                    self.assertGreater(wav.getframerate(), 0)
                    durations.append(wav.getnframes() / wav.getframerate())
        worker.stop()
        self.assertEqual(len(durations), 4)
        self.assertTrue(all(0.1 < duration < 15 for duration in durations))

    def test_elevenlabs_uses_each_selected_profile_speed_without_network(self) -> None:
        config = default_config()
        config.update(
            tts_provider="elevenlabs",
            voice_names=["free-voice"],
            voice_profiles={
                "free-voice": profile
                for profile in ("pausada", "natural", "energética", "ágil")
            },
        )
        worker = SpeechWorker(config)
        speeds: list[float] = []

        def fake_synthesize(
            _api_key: str, _voice_id: str, _text: str, speed: float
        ) -> bytes:
            speeds.append(speed)
            return array("h", [100]).tobytes()

        with (
            patch("livevoice.secrets_store.load_api_key", return_value="fake-key"),
            patch(
                "livevoice.elevenlabs.verify_free_account",
                return_value={"remaining_characters": 1000},
            ),
            patch("livevoice.elevenlabs.synthesize", side_effect=fake_synthesize),
            patch("livevoice.speech._play_wave") as play,
        ):
            for profile in ("pausada", "natural", "energética", "ágil"):
                config["voice_profiles"]["free-voice"] = profile
                worker.speak("hola", "free-voice", 75, 0)

        self.assertEqual(speeds, [0.9, 1.0, 1.05, 1.1])
        self.assertEqual(play.call_count, 4)

    def test_local_audio_volume_is_applied_to_wave_samples(self) -> None:
        source = io.BytesIO()
        with wave.open(source, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(array("h", [1000, -2000]).tobytes())
        def capture_playback(path: str | None, _flags: int) -> None:
            if path is None:
                return
            with wave.open(path, "rb") as wav_file:
                samples = array("h", wav_file.readframes(2))
            self.assertEqual(samples.tolist(), [500, -1000])

        with patch("winsound.PlaySound", side_effect=capture_playback) as play:
            _play_wave(source.getvalue(), 50)
        import winsound

        self.assertEqual(
            play.call_args_list[0].args[1],
            winsound.SND_FILENAME | winsound.SND_ASYNC,
        )
        self.assertEqual(play.call_args_list[-1].args, (None, 0))

    def test_local_audio_playback_is_cancelled_and_temp_file_removed(self) -> None:
        source = io.BytesIO()
        with wave.open(source, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(array("h", [1000] * 22050).tobytes())

        playback_started = threading.Event()
        playback_files: list[str] = []

        def start_playback(path: str | None, _flags: int) -> None:
            if path is not None:
                playback_files.append(path)
                playback_started.set()

        stop_event = threading.Event()
        errors: list[BaseException] = []

        def play() -> None:
            try:
                _play_wave(source.getvalue(), 100, stop_event)
            except BaseException as exc:
                errors.append(exc)

        with patch("winsound.PlaySound", side_effect=start_playback):
            playback_thread = threading.Thread(target=play)
            playback_thread.start()
            self.assertTrue(playback_started.wait(timeout=2))
            time.sleep(0.05)
            stop_event.set()
            playback_thread.join(timeout=1)

        self.assertFalse(playback_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(playback_files), 1)
        self.assertFalse(Path(playback_files[0]).exists())

class ConnectorTests(unittest.TestCase):
    def test_username_validation(self) -> None:
        self.assertEqual(normalize_username("  @creator_01 "), "creator_01")
        with self.assertRaises(ValueError):
            normalize_username("https://tiktok.com/@creator")

    def test_speech_preserves_names_and_clips_comments(self) -> None:
        class FakeWorker:
            def __init__(self) -> None:
                self.last: tuple[str, str, int, int] | None = None

            def speak(self, text: str, voice: str, volume: int, rate: int) -> None:
                self.last = (text, voice, volume, rate)

        worker = FakeWorker()
        config = default_config()
        config.update(
            voice_names=["Sabina", "Raul"],
            voice_mode="per_user",
            max_comment_length=5,
            volume=55,
            rate=2,
        )
        speak_comment("Ana", "Hola, mundo", config, worker, iter(["Sabina"]))
        self.assertIsNotNone(worker.last)
        text, voice, volume, rate = worker.last
        self.assertEqual(text, "Ana: Hola,")
        self.assertIn(voice, config["voice_names"])
        self.assertEqual((volume, rate), (55, 2))

    def test_speech_profiles_use_expected_sapi_rates(self) -> None:
        class FakeWorker:
            def __init__(self) -> None:
                self.rates: list[int] = []

            def speak(self, _text: str, _voice: str, _volume: int, rate: int) -> None:
                self.rates.append(rate)

        worker = FakeWorker()
        config = default_config()
        config.update(voice_names=["Sabina"], voice_mode="per_user")
        config["voice_profiles"]["Sabina"] = "pausada"
        expected_rates = {
            "pausada": -2,
            "natural": 0,
            "energética": 1,
            "ágil": 2,
        }
        for profile, expected_rate in expected_rates.items():
            config["voice_profiles"]["Sabina"] = profile
            speak_comment("Ana", "Hola", config, worker, iter(config["voice_names"]))
            self.assertEqual(worker.rates[-1], expected_rate)

    def test_decorative_nickname_is_normalized_before_speech(self) -> None:
        class FakeWorker:
            def __init__(self) -> None:
                self.text = ""

            def speak(
                self, text: str, _voice: str, _volume: int, _rate: int
            ) -> None:
                self.text = text

        self.assertEqual(_spoken_nickname("×𝚈𝚊𝚑𝚒𝚛𝙹𝙼 亗"), "YahirJM")
        worker = FakeWorker()
        config = default_config()
        config.update(voice_names=["Sabina"], speak_usernames=True)
        speak_comment("×𝚈𝚊𝚑𝚒𝚛𝙹𝙼 亗", "Hola", config, worker, iter(["Sabina"]))
        self.assertEqual(worker.text, "YahirJM: Hola")

    def test_connection_retries_with_increasing_delays(self) -> None:
        class ControlledStop(threading.Event):
            delays: list[float] = []

            def wait(self, timeout: float | None = None) -> bool:
                if timeout is not None and timeout >= 2:
                    self.delays.append(timeout)
                    if len(self.delays) == 2:
                        self.set()
                    return super().wait(0)
                return super().wait(timeout)

        class FailingClient:
            attempts = 0

            def __init__(self, unique_id: str) -> None:
                self.unique_id = unique_id
                self.listeners: dict[object, object] = {}
                type(self).attempts += 1

            def add_listener(self, event_type: object, listener: object) -> None:
                self.listeners[event_type] = listener

            def run(self, **kwargs: object) -> None:
                connect_listener = self.listeners[events_module.ConnectEvent]
                comment_listener = self.listeners[events_module.CommentEvent]
                run_async(connect_listener(None))
                run_async(
                    comment_listener(
                        SimpleNamespace(
                            comment="Hola",
                            common=SimpleNamespace(msg_id=42),
                            user=SimpleNamespace(nickname="Ana"),
                        )
                    )
                )
                raise RuntimeError("temporary network failure")

        class FakeSpeechWorker:
            def __init__(self, config: dict[str, object] | None = None) -> None:
                pass

            def speak(
                self, text: str, voice: str, volume: int, rate: int
            ) -> None:
                pass

            def stop(self) -> None:
                pass

        tiktok_module = types.ModuleType("TikTokLive")
        tiktok_module.TikTokLiveClient = FailingClient
        events_module = types.ModuleType("TikTokLive.events")
        events_module.CommentEvent = type("CommentEvent", (), {})
        events_module.ConnectEvent = type("ConnectEvent", (), {})
        config = default_config()
        config["voice_names"] = ["Sabina"]
        output = io.StringIO()
        stop_event = ControlledStop()
        statuses: list[tuple[str, str]] = []
        displayed_comments: list[tuple[str, str]] = []

        with (
            patch.dict(
                sys.modules,
                {"TikTokLive": tiktok_module, "TikTokLive.events": events_module},
            ),
            patch("livevoice.connector.SpeechWorker", FakeSpeechWorker),
            redirect_stdout(output),
        ):
            connect_and_read(
                "creator",
                config,
                stop_event=stop_event,
                on_status=lambda level, text: statuses.append((level, text)),
                comment_callback=lambda nickname, text: displayed_comments.append(
                    (nickname, text)
                ),
            )

        self.assertEqual(FailingClient.attempts, 2)
        self.assertEqual(stop_event.delays, [2, 4])
        self.assertIn("temporary network failure", output.getvalue())
        self.assertIn(("connected", "Conectado a @creator. Leyendo comentarios."), statuses)
        self.assertEqual(displayed_comments, [("Ana", "Hola")])

    def test_stop_event_disconnects_active_client(self) -> None:
        connected = threading.Event()
        disconnected = threading.Event()

        class FakeClient:
            def __init__(self, unique_id: str) -> None:
                self.unique_id = unique_id
                self.listeners: dict[object, object] = {}
                self._asyncio_loop = asyncio.new_event_loop()
                self.loop_thread = threading.Thread(
                    target=self._serve_loop, daemon=True
                )
                self.loop_thread.start()

            def _serve_loop(self) -> None:
                asyncio.set_event_loop(self._asyncio_loop)
                self._asyncio_loop.run_forever()

            def add_listener(self, event_type: object, listener: object) -> None:
                self.listeners[event_type] = listener

            def run(self, **kwargs: object) -> None:
                listener = self.listeners[events_module.ConnectEvent]
                future = asyncio.run_coroutine_threadsafe(
                    listener(None), self._asyncio_loop
                )
                future.result(timeout=2)
                if not disconnected.wait(timeout=2):
                    raise TimeoutError("disconnect was not requested")
                self._asyncio_loop.call_soon_threadsafe(self._asyncio_loop.stop)
                self.loop_thread.join(timeout=2)
                self._asyncio_loop.close()

            async def disconnect(self) -> None:
                disconnected.set()

        class FakeSpeechWorker:
            def __init__(self, config: dict[str, object] | None = None) -> None:
                pass

            def speak(
                self, text: str, voice: str, volume: int, rate: int
            ) -> None:
                pass

            def stop(self) -> None:
                pass

        tiktok_module = types.ModuleType("TikTokLive")
        tiktok_module.TikTokLiveClient = FakeClient
        events_module = types.ModuleType("TikTokLive.events")
        events_module.CommentEvent = type("CommentEvent", (), {})
        events_module.ConnectEvent = type("ConnectEvent", (), {})
        stop_event = threading.Event()
        config = default_config()
        config["voice_names"] = ["Sabina"]

        def report_status(level: str, _message: str) -> None:
            if level == "connected":
                connected.set()

        with (
            patch.dict(
                sys.modules,
                {"TikTokLive": tiktok_module, "TikTokLive.events": events_module},
            ),
            patch("livevoice.connector.SpeechWorker", FakeSpeechWorker),
        ):
            connection = threading.Thread(
                target=connect_and_read,
                args=("creator", config),
                kwargs={"stop_event": stop_event, "on_status": report_status},
                daemon=True,
            )
            connection.start()
            self.assertTrue(connected.wait(timeout=2))
            stop_event.set()
            connection.join(timeout=3)

        self.assertFalse(connection.is_alive())
        self.assertTrue(disconnected.is_set())


class AppMenuTests(unittest.TestCase):
    def test_piper_setup_can_skip_download_and_keep_installed_voice(self) -> None:
        voice = {
            "id": "test-spanish",
            "name": "Spanish test voice",
            "language": "Español",
            "quality": "Media",
            "size": "1 MB",
            "folder": "es/test/medium",
        }
        config = default_config()
        config["voice_names"] = [voice["id"]]
        with (
            patch("livevoice.app.piper_catalog", return_value=[voice]),
            patch(
                "livevoice.app.list_installed_piper_voices",
                return_value=[voice],
            ),
            patch("livevoice.app.download_piper_voice") as download,
            patch("builtins.input", side_effect=["", "", ""]),
        ):
            _configure_piper(config)

        download.assert_not_called()
        self.assertEqual(config["tts_provider"], "piper")
        self.assertEqual(config["voice_names"], [voice["id"]])
        self.assertEqual(config["voice_profiles"][voice["id"]], "natural")

    def test_quick_help_is_available_from_main_menu(self) -> None:
        config = default_config()
        config.update(username="creator", voice_names=["Sabina"])
        output = io.StringIO()
        with patch("livevoice.app._ask", side_effect=["5", "6"]), redirect_stdout(output):
            run_app(config)

        self.assertIn("AYUDA RÁPIDA", output.getvalue())
        self.assertIn("pulsa R", output.getvalue())
        self.assertIn("Pulsa S", output.getvalue())

    def test_console_is_restored_then_maximized_on_windows(self) -> None:
        kernel32 = Mock()
        user32 = Mock()
        kernel32.GetConsoleWindow.return_value = 1234
        with (
            patch("main.sys.platform", "win32"),
            patch("ctypes.WinDLL", side_effect=[kernel32, user32]),
        ):
            _configure_console()

        self.assertEqual(
            [call.args for call in user32.ShowWindow.call_args_list],
            [(1234, 9), (1234, 3)],
        )
        self.assertEqual(kernel32.GetConsoleWindow.restype, ctypes.c_void_p)


if __name__ == "__main__":
    unittest.main()
