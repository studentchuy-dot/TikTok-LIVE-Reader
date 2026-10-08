"""Speech backends for Windows SAPI, local Piper, and ElevenLabs."""

from __future__ import annotations

import base64
from array import array
from collections import OrderedDict
from io import BytesIO
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Any
import wave

_PROFILE_SPEEDS = {
    "natural": 1.0,
    "ágil": 1.1,
    "agil": 1.1,
    "pausada": 0.9,
    "energética": 1.05,
    "energetica": 1.05,
}
_LIST_VOICES_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = @($synth.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object {
    [PSCustomObject]@{
        name = $_.VoiceInfo.Name
        culture = $_.VoiceInfo.Culture.Name
        gender = $_.VoiceInfo.Gender.ToString()
    }
})
if ($voices.Count -eq 0) {
    '[]'
} else {
    ConvertTo-Json -InputObject $voices -Compress
}
$synth.Dispose()
"""

_SPEECH_WORKER_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SetOutputToDefaultAudioDevice()
while ($null -ne ($line = [Console]::In.ReadLine())) {
    if ($line -eq '__QUIT__') { break }
    try {
        $item = ConvertFrom-Json -InputObject $line
        if ($item.voice) { $synth.SelectVoice([string]$item.voice) }
        $synth.Volume = [Math]::Max(0, [Math]::Min(100, [int]$item.volume))
        $synth.Rate = [Math]::Max(-10, [Math]::Min(10, [int]$item.rate))
        $synth.Speak([string]$item.text)
        [Console]::Out.WriteLine('__OK__')
    } catch {
        [Console]::Out.WriteLine('__ERROR__' + $_.Exception.Message)
    }
    [Console]::Out.Flush()
}
$synth.Dispose()
"""


def _powershell_executable() -> str:
    executable = shutil.which("powershell.exe") or shutil.which("powershell")
    if not executable:
        raise RuntimeError(
            "No se encontró Windows PowerShell. Esta versión requiere Windows."
        )
    return executable


def _encoded_command(script: str) -> str:
    return base64.b64encode(script.encode("utf-16le")).decode("ascii")


def list_voices() -> list[dict[str, str]]:
    """List voices exposed by Windows SAPI, without downloading voice models."""
    try:
        result = subprocess.run(
            [
                _powershell_executable(),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                _encoded_command(_LIST_VOICES_SCRIPT),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=20,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Windows tardó demasiado en consultar las voces.") from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Windows no pudo consultar las voces instaladas. {detail}")
    try:
        decoded: Any = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Windows devolvió una lista de voces ilegible: {result.stdout.strip()}"
        ) from exc
    if isinstance(decoded, dict):
        decoded = [decoded]
    if not isinstance(decoded, list):
        raise RuntimeError("Windows devolvió un formato de voces no reconocido.")
    return [
        {
            "name": str(voice["name"]),
            "culture": str(voice["culture"]),
            "gender": str(voice["gender"]),
        }
        for voice in decoded
        if isinstance(voice, dict)
        and {"name", "culture", "gender"}.issubset(voice)
    ]


class SpeechWorker:
    """Keep a selected local or cloud speech backend for sequential speech."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._process: subprocess.Popen[str] | None = None
        self._piper_voices: OrderedDict[str, Any] = OrderedDict()
        self._api_key = ""
        self._free_characters = 0
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._config.get("tts_provider") in {"piper", "elevenlabs"}:
            return
        if self._process and self._process.poll() is None:
            return
        self._process = subprocess.Popen(
            [
                _powershell_executable(),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                _encoded_command(_SPEECH_WORKER_SCRIPT),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if self._process.poll() is not None:
            detail = self._process.stderr.read() if self._process.stderr else ""
            raise RuntimeError(f"No se pudo iniciar el sintetizador de Windows. {detail}")

    def speak(self, text: str, voice: str, volume: int, rate: int) -> None:
        if self._stop_event.is_set():
            return
        provider = self._config.get("tts_provider", "sapi")
        if provider == "piper":
            self._speak_piper(text, voice, volume, rate)
            return
        if provider == "elevenlabs":
            self._speak_elevenlabs(text, voice, volume)
            return
        self._speak_sapi(text, voice, volume, rate)

    def _speak_sapi(self, text: str, voice: str, volume: int, rate: int) -> None:
        self.start()
        process = self._process
        if process is None:
            raise RuntimeError("El sintetizador de voz se detuvo.")
        if process.stdin is None or process.poll() is not None:
            detail = process.stderr.read() if process.stderr else ""
            raise RuntimeError(f"El sintetizador de voz se detuvo. {detail}")
        payload = json.dumps(
            {"text": text, "voice": voice, "volume": volume, "rate": rate},
            ensure_ascii=True,
        )
        try:
            process.stdin.write(payload + os.linesep)
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise RuntimeError(f"No se pudo enviar texto al sintetizador: {exc}") from exc
        if process.stdout is None:
            raise RuntimeError("No se pudo leer la respuesta del sintetizador.")
        try:
            response = process.stdout.readline().strip()
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"No se pudo leer la respuesta del sintetizador: {exc}") from exc
        if response == "__OK__":
            return
        if response.startswith("__ERROR__"):
            detail = response.removeprefix("__ERROR__")
        else:
            detail = (
                process.stderr.read().strip()
                if process.stderr and process.poll() is not None
                else ""
            )
        raise RuntimeError(
            f"Windows no pudo pronunciar el comentario. {detail or response}"
        )

    def _speak_piper(self, text: str, voice_id: str, volume: int, _rate: int) -> None:
        from .piper_voices import voice_path

        piper_voice = self._piper_voices.get(voice_id)
        if piper_voice is None:
            try:
                from piper import PiperVoice
            except ImportError as exc:
                raise RuntimeError(
                    "Falta el motor local Piper. Reinstala con setup.bat."
                ) from exc
            try:
                piper_voice = PiperVoice.load(str(voice_path(voice_id)))
            except (OSError, ValueError) as exc:
                raise RuntimeError(f"No se pudo cargar la voz Piper {voice_id}: {exc}") from exc
            self._piper_voices[voice_id] = piper_voice
            if len(self._piper_voices) > 2:
                self._piper_voices.popitem(last=False)
        else:
            self._piper_voices.move_to_end(voice_id)

        from piper.config import SynthesisConfig

        voice_profile = self._config.get("voice_profiles", {}).get(voice_id)
        fallback_speed = max(0.8, min(1.2, 1.0 + _rate * 0.05))
        profile = voice_profile or self._config.get("profile", "natural")
        speed = _PROFILE_SPEEDS.get(profile, fallback_speed)
        length_scale = max(0.65, min(1.5, 1.0 / speed))
        synth_config = SynthesisConfig(
            length_scale=length_scale,
            volume=1.0,
        )
        wav_buffer = BytesIO()
        try:
            with wave.open(wav_buffer, "wb") as wav_file:
                piper_voice.synthesize_wav(text, wav_file, syn_config=synth_config)
        except (OSError, ValueError, RuntimeError, wave.Error) as exc:
            raise RuntimeError(f"Piper no pudo generar la voz: {exc}") from exc
        _play_wave(wav_buffer.getvalue(), volume, self._stop_event)

    def _speak_elevenlabs(self, text: str, voice_id: str, volume: int) -> None:
        from .elevenlabs import synthesize, verify_free_account
        from .secrets_store import load_api_key

        if not self._api_key:
            self._api_key = load_api_key()
            account = verify_free_account(self._api_key)
            self._free_characters = account["remaining_characters"]
        if len(text) > self._free_characters:
            raise RuntimeError(
                "No quedan suficientes caracteres de cuota gratuita para este texto."
            )
        profile = self._config.get("voice_profiles", {}).get(
            voice_id, self._config.get("profile", "natural")
        )
        speed = _PROFILE_SPEEDS.get(profile, 1.0)
        pcm_audio = synthesize(self._api_key, voice_id, text, speed)
        self._free_characters -= len(text)
        wav_buffer = BytesIO()
        with wave.open(wav_buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(pcm_audio)
        _play_wave(wav_buffer.getvalue(), volume, self._stop_event)

    def stop(self) -> None:
        self._stop_event.set()
        process = self._process
        self._process = None
        if not process:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if process.stdin:
            process.stdin.close()
        # The speech thread may still be unwinding from a blocked pipe read.
        # Keep the handles open until that thread releases its local reference.


def _play_wave(
    data: bytes, volume: int, stop_event: threading.Event | None = None
) -> None:
    try:
        import winsound
    except ImportError as exc:
        raise RuntimeError("La reproducción local requiere Windows.") from exc
    try:
        with wave.open(BytesIO(data), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            frame_count = source.getnframes()
            frames = source.readframes(source.getnframes())
        if sample_width != 2 or channels not in {1, 2}:
            raise ValueError("El audio debe ser PCM de 16 bits mono o estéreo.")
        samples = array("h")
        samples.frombytes(frames)
        if sys.byteorder != "little":
            samples.byteswap()
        gain = max(0, min(100, volume)) / 100
        for index, sample in enumerate(samples):
            samples[index] = max(-32768, min(32767, round(sample * gain)))
        if sys.byteorder != "little":
            samples.byteswap()
        adjusted = BytesIO()
        with wave.open(adjusted, "wb") as destination:
            destination.setnchannels(channels)
            destination.setsampwidth(sample_width)
            destination.setframerate(sample_rate)
            destination.writeframes(samples.tobytes())
        playback_stop = stop_event or threading.Event()
        if playback_stop.is_set():
            return
        temporary_name = ""
        playing = False
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output:
                temporary_name = output.name
                output.write(adjusted.getvalue())
            winsound.PlaySound(
                temporary_name, winsound.SND_FILENAME | winsound.SND_ASYNC
            )
            playing = True
            playback_stop.wait(frame_count / sample_rate + 0.05)
        finally:
            try:
                if playing:
                    winsound.PlaySound(None, 0)
            finally:
                if temporary_name:
                    try:
                        os.unlink(temporary_name)
                    except FileNotFoundError:
                        pass
    except (OSError, wave.Error, ValueError) as exc:
        raise RuntimeError(f"No se pudo reproducir el audio generado: {exc}") from exc
