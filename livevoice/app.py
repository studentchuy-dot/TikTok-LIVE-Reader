"""First-run wizard and compact interactive console menu."""

from __future__ import annotations

import getpass
from typing import Any

from .config import save_config
from .connector import connect_and_read, normalize_username, run_test_comment
from .elevenlabs import list_free_voices, verify_free_account
from .piper_voices import (
    catalog as piper_catalog,
    download_voice as download_piper_voice,
    installed_voices as list_installed_piper_voices,
    remove_voice as remove_piper_voice,
    voices_directory as piper_voices_directory,
)
from .secrets_store import (
    delete_api_key,
    load_api_key,
    store_api_key,
)
from .speech import list_voices

PROFILES = {
    "1": ("natural", 0, "Natural: ritmo normal, cómodo para conversar"),
    "2": ("ágil", 2, "Ágil: ritmo un poco más rápido para chats activos"),
    "3": ("pausada", -2, "Pausada: ritmo más lento para comentarios largos"),
    "4": ("energética", 1, "Energética: ritmo vivo para entretenimiento"),
}


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [Enter = {default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def _ask_integer(prompt: str, current: int, minimum: int, maximum: int) -> int:
    while True:
        answer = _ask(prompt, str(current))
        if answer.isdigit() and minimum <= int(answer) <= maximum:
            return int(answer)
        print(f"Escribe un número entre {minimum} y {maximum}.")


def _choose_voices(voices: list[dict[str, str]], current: list[str]) -> list[str]:
    if not voices:
        raise RuntimeError(
            "Windows no muestra voces SAPI instaladas. Abre Configuración > "
            "Hora e idioma > Voz para agregar una voz compatible."
        )
    print("\nVoces disponibles en Windows (no se descargan modelos adicionales):")
    for index, voice in enumerate(voices, 1):
        print(
            f"  {index}. {voice['name']} — {voice['culture']} — {voice['gender']}"
        )
    selected_default = ",".join(
        str(index + 1)
        for index, voice in enumerate(voices)
        if voice["name"] in current
    )
    while True:
        raw = _ask(
            "Elige una o varias voces separadas por coma (ej. 1,2)",
            selected_default or "1",
        )
        try:
            indexes = [int(value.strip()) for value in raw.split(",")]
        except ValueError:
            indexes = []
        if indexes and all(1 <= index <= len(voices) for index in indexes):
            selected = list(dict.fromkeys(voices[index - 1]["name"] for index in indexes))
            return selected
        print("La selección no es válida.")


def _persist(config: dict[str, Any]) -> None:
    path = save_config(config)
    print(f"Ajustes guardados en: {path}")


def _choose_indexes(prompt: str, count: int, default: str = "") -> list[int]:
    while True:
        raw = _ask(prompt, default)
        if not raw:
            return []
        try:
            indexes = [int(value.strip()) for value in raw.split(",")]
        except ValueError:
            indexes = []
        if indexes and all(1 <= index <= count for index in indexes):
            return list(dict.fromkeys(indexes))
        print("La selección no es válida.")


def _set_voice_profiles(config: dict[str, Any]) -> None:
    profiles = config.setdefault("voice_profiles", {})
    for voice in config["voice_names"]:
        current = profiles.get(voice, config["profile"])
        print(f"\nPerfil para {voice}:")
        for key, (name, _, description) in PROFILES.items():
            print(f"  {key}. {description}")
        default_key = next(
            (
                key
                for key, (name, _, _) in PROFILES.items()
                if name == current
            ),
            "1",
        )
        choice = _ask("Elige perfil", default_key)
        if choice in PROFILES:
            profiles[voice] = PROFILES[choice][0]
        else:
            print("Perfil no reconocido; se conserva el anterior.")


def _configure_sapi(config: dict[str, Any]) -> None:
    config["voice_names"] = _choose_voices(
        list_voices(), config.get("voice_names", [])
    )
    config["tts_provider"] = "sapi"
    _set_voice_profiles(config)


def _configure_piper(config: dict[str, Any]) -> None:
    catalog = piper_catalog()
    installed_ids = {
        voice["id"] for voice in list_installed_piper_voices()
    }
    print(
        "\nVOCES LOCALES PIPER (sin enviar comentarios a internet)"
        "\nEscribe los números que quieras separados por coma (ej. 1,3)."
        "\nPulsa Enter en la selección de descarga para saltar ese paso."
    )
    for index, voice in enumerate(catalog, 1):
        status = "instalada" if voice["id"] in installed_ids else "descargar"
        print(
            f"  {index}. {voice['name']} | {voice['language']} | "
            f"{voice['quality']} | aprox. {voice['size']} | {status}"
        )
        print(f"     Licencia y ficha: https://huggingface.co/rhasspy/piper-voices/tree/v1.0.0/{voice['folder']}")

    choices = _choose_indexes(
        "Voces que quieres descargar (ej. 1,3; Enter = no descargar ahora)",
        len(catalog),
    )
    for index in choices:
        voice = catalog[index - 1]
        if voice["id"] in installed_ids:
            print(f"{voice['name']} ya está descargada.")
            continue
        confirmation = _ask(
            f"Descargar {voice['name']} ({voice['size']}) y revisar su licencia después (s/n)",
            "n",
        ).lower()
        if confirmation not in {"s", "si", "sí", "y", "yes"}:
            continue
        model_path = download_piper_voice(voice["id"])
        installed_ids.add(voice["id"])
        print(f"Voz descargada: {model_path}")
        card_path = model_path.parent / "MODEL_CARD"
        if card_path.is_file():
            print(f"Ficha/licencia del modelo: {card_path}")

    installed = list_installed_piper_voices()
    if not installed:
        raise RuntimeError(
            "No hay voces Piper instaladas. Descarga al menos una para continuar."
        )
    print("\nVoces instaladas y nivel:")
    for index, voice in enumerate(installed, 1):
        print(
            f"  {index}. {voice['name']} | {voice['language']} | {voice['quality']}"
        )
    selected = _choose_indexes(
        "Voces activas para comentarios (ej. 1,2; Enter = conservar la selección)",
        len(installed),
        ",".join(
            str(index + 1)
            for index, voice in enumerate(installed)
            if voice["id"] in config.get("voice_names", [])
        ),
    )
    if not selected:
        raise RuntimeError(
            "Activa al menos una voz Piper para continuar. "
            "Escribe su número (ej. 1) o cambia a otro motor."
        )
    config["voice_names"] = list(
        dict.fromkeys(installed[index - 1]["id"] for index in selected)
    )
    config["tts_provider"] = "piper"
    _set_voice_profiles(config)


def _configure_elevenlabs(config: dict[str, Any]) -> None:
    print(
        "\nELEVENLABS (NUBE)"
        "\n1. Crea una cuenta gratuita en https://elevenlabs.io/app/sign-up"
        "\n2. Abre https://elevenlabs.io/app/settings/api-keys y crea una API key."
        "\n3. Habilita permisos de cuenta, voces y texto-a-voz; pega la key aquí."
        "\n   Se comprueba el nivel Free y que no haya excedentes facturables."
        "\nLos comentarios se envían a ElevenLabs; consumen tu cupo y el plan Free"
        "\nno incluye licencia comercial. No uses esta opción si necesitas esa licencia."
    )
    entered_key = getpass.getpass("API key (entrada oculta; Enter = usar la guardada): ").strip()
    if entered_key:
        api_key = entered_key
    else:
        api_key = load_api_key()

    account = verify_free_account(api_key)
    print(
        "Cuenta gratuita comprobada: "
        f"{account['character_count']:,}/{account['character_limit']:,} "
        f"caracteres usados; quedan aproximadamente "
        f"{account['remaining_characters']:,}."
    )
    voices = list_free_voices(api_key)
    if not voices:
        raise RuntimeError(
            "La API no devolvió voces disponibles para el nivel Free."
        )
    print("\nVoces que la API marca disponibles para Free:")
    for index, voice in enumerate(voices, 1):
        print(
            f"  {index}. {voice['name']} | {voice['language']} | {voice['category']}"
        )
    selected = _choose_indexes(
        "Voces activas (números separados por coma)",
        len(voices),
        ",".join(
            str(index + 1)
            for index, voice in enumerate(voices)
            if voice["id"] in config.get("voice_names", [])
        ),
    )
    if not selected:
        raise RuntimeError("Selecciona al menos una voz de ElevenLabs.")
    if entered_key:
        key_path = store_api_key(api_key)
        print(f"API key validada y cifrada por Windows: {key_path}")
    config["voice_names"] = list(
        dict.fromkeys(voices[index - 1]["id"] for index in selected)
    )
    config["tts_provider"] = "elevenlabs"
    _set_voice_profiles(config)


def _configure_provider(config: dict[str, Any]) -> None:
    print(
        "\nMOTOR DE VOZ"
        "\n  1. Voces de Windows (instaladas en este equipo)"
        "\n  2. Piper (descargar voces y hablar sin internet)"
        "\n  3. ElevenLabs (nube, requiere API key y consume el cupo Free)"
    )
    current = {"sapi": "1", "piper": "2", "elevenlabs": "3"}.get(
        config.get("tts_provider", "sapi"), "1"
    )
    while True:
        choice = _ask("Elige el motor", current)
        try:
            if choice == "1":
                _configure_sapi(config)
                break
            if choice == "2":
                _configure_piper(config)
                break
            if choice == "3":
                _configure_elevenlabs(config)
                break
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"[ERROR DE VOZ] {exc}")
            if _ask("Volver a elegir motor (s/n)", "s").lower() not in {
                "s",
                "si",
                "sí",
                "y",
                "yes",
            }:
                raise
        else:
            print("Selecciona 1, 2 o 3.")


def _manage_voices(config: dict[str, Any]) -> None:
    if config.get("tts_provider") != "piper":
        print(
            "\nGESTIONAR VOCES"
            "\n  1. Elegir voces del motor actual"
            "\n  2. Instalar y usar voces Piper descargables"
            "\n  3. Volver"
        )
        choice = _ask("Opción", "3")
        if choice == "2":
            _configure_piper(config)
            _persist(config)
            return
        if choice == "3":
            return
        if choice != "1":
            print("Opción no reconocida.")
            return

    if config.get("tts_provider") == "piper":
        print(
            "\nGESTIONAR VOCES PIPER"
            "\n  1. Descargar más voces y elegir cuáles usar"
            "\n  2. Elegir voces Piper ya descargadas"
            "\n  3. Desinstalar una voz Piper"
            "\n  4. Volver"
        )
        choice = _ask("Opción", "4")
        if choice == "1":
            _configure_piper(config)
        elif choice == "2":
            installed = list_installed_piper_voices()
            if not installed:
                print("Todavía no hay voces descargadas.")
                return
            for index, voice in enumerate(installed, 1):
                print(
                    f"  {index}. {voice['name']} | {voice['language']} | {voice['quality']}"
                )
            selected = _choose_indexes(
                "Voces activas",
                len(installed),
                ",".join(
                    str(index + 1)
                    for index, voice in enumerate(installed)
                    if voice["id"] in config["voice_names"]
                ),
            )
            if selected:
                config["voice_names"] = list(
                    dict.fromkeys(installed[index - 1]["id"] for index in selected)
                )
                _set_voice_profiles(config)
                _persist(config)
        elif choice == "3":
            installed = list_installed_piper_voices()
            if not installed:
                print("No hay voces Piper descargadas.")
                return
            for index, voice in enumerate(installed, 1):
                print(f"  {index}. {voice['name']} ({voice['size']})")
            selected = _choose_indexes("Voz que quieres desinstalar", len(installed))
            if selected:
                voice = installed[selected[0] - 1]
                if (
                    voice["id"] in config["voice_names"]
                    and len(config["voice_names"]) == 1
                ):
                    raise RuntimeError(
                        "No puedes quitar la última voz activa. Activa otra o cambia de motor."
                    )
                remove_piper_voice(voice["id"])
                config["voice_names"] = [
                    name for name in config["voice_names"] if name != voice["id"]
                ]
                config.get("voice_profiles", {}).pop(voice["id"], None)
                print(f"Voz eliminada de {piper_voices_directory()}.")
                _persist(config)
        elif choice != "4":
            print("Opción no reconocida.")
        return

    if config.get("tts_provider") == "elevenlabs":
        print(
            "\n  1. Volver a validar key y elegir voces/perfiles"
            "\n  2. Borrar API key cifrada"
            "\n  3. Volver"
        )
        choice = _ask("Opción", "3")
        if choice == "1":
            _configure_elevenlabs(config)
            _persist(config)
        elif choice == "2":
            delete_api_key()
            config["tts_provider"] = "sapi"
            config["voice_names"] = []
            print("API key cifrada eliminada; selecciona otra voz en Ajustes.")
            _persist(config)
        elif choice != "3":
            print("Opción no reconocida.")
        return

    _configure_sapi(config)
    _persist(config)


def first_run(config: dict[str, Any]) -> None:
    print("\nAsistente de primera configuración — TikTok LIVE Reader")
    print(
        "Los ajustes se guardan localmente. No se solicita contraseña de TikTok."
    "\nPulsa Enter para aceptar el valor recomendado que aparezca entre corchetes."
    "\nEl usuario de TikTok y al menos una voz sí son necesarios para conectar."
    )
    while True:
        username = _ask("Nombre de usuario de TikTok (con o sin @)")
        try:
            config["username"] = normalize_username(username)
            break
        except ValueError as exc:
            print(exc)

    config["volume"] = _ask_integer("Volumen de voz (0–100)", 75, 0, 100)
    _choose_profile(config)
    _configure_provider(config)
    config["voice_mode"] = _choose_voice_mode(config)
    _persist(config)


def _choose_profile(config: dict[str, Any]) -> None:
    print("\nPerfil de lectura:")
    for key, (_, _, description) in PROFILES.items():
        print(f"  {key}. {description}")
    default_key = next(
        (
            key
            for key, (name, _, _) in PROFILES.items()
            if name == config["profile"]
        ),
        "1",
    )
    choice = _ask("Elige un perfil", default_key)
    if choice not in PROFILES:
        print("Perfil no reconocido; se conserva el perfil actual.")
        return
    config["profile"], config["rate"], _ = PROFILES[choice]
    if config["voice_names"] and _ask(
        "¿Aplicar el nuevo perfil a todas las voces activas? (s/n)", "n"
    ).lower() in {"s", "si", "sí", "y", "yes"}:
        config["voice_profiles"] = {
            voice: config["profile"] for voice in config["voice_names"]
        }


def _choose_voice_mode(config: dict[str, Any]) -> str:
    print("\nCómo repartir las voces:")
    print("  1. Una voz distinta estable por cada usuario del chat")
    print("  2. Rotar las voces en cada comentario")
    default = "2" if config["voice_mode"] == "rotate" else "1"
    choice = _ask("Elige el modo", default)
    if choice == "2":
        return "rotate"
    if choice != "1":
        print("Opción no reconocida; se conserva el modo actual.")
    return config["voice_mode"]


def _settings(config: dict[str, Any]) -> None:
    while True:
        print("\nAJUSTES")
        print("  1. Cambiar usuario")
        print("  2. Gestionar voces (incluye instalar voces Piper)")
        print("  3. Modo de asignación de voces")
        print("  4. Volumen de lectura")
        print("  5. Perfil / velocidad")
        print("  6. Leer nombre de quien comenta")
        print("  7. Longitud máxima del comentario")
        print("  8. Capacidad de la cola de voz (1–100)")
        print("  9. Cambiar motor TTS y voces")
        print("  10. Guardar y volver")
        choice = _ask("Opción", "10")
        if choice == "1":
            try:
                config["username"] = normalize_username(
                    _ask("Nuevo usuario", config["username"])
                )
                _persist(config)
            except ValueError as exc:
                print(exc)
        elif choice == "2":
            try:
                _manage_voices(config)
                _persist(config)
            except (OSError, RuntimeError, ValueError) as exc:
                print(f"[ERROR DE VOZ] {exc}")
        elif choice == "3":
            config["voice_mode"] = _choose_voice_mode(config)
            _persist(config)
        elif choice == "4":
            config["volume"] = _ask_integer("Volumen (0–100)", config["volume"], 0, 100)
            _persist(config)
        elif choice == "5":
            _choose_profile(config)
            _persist(config)
        elif choice == "6":
            current = "s" if config["speak_usernames"] else "n"
            config["speak_usernames"] = _ask("Leer nombre de usuario (s/n)", current).lower() in {
                "s",
                "si",
                "sí",
                "y",
                "yes",
            }
            _persist(config)
        elif choice == "7":
            config["max_comment_length"] = _ask_integer(
                "Límite de caracteres", config["max_comment_length"], 20, 1000
            )
            _persist(config)
        elif choice == "8":
            config["queue_size"] = _ask_integer(
                "Comentarios máximos en cola",
                config["queue_size"],
                1,
                100,
            )
            _persist(config)
        elif choice == "9":
            try:
                _configure_provider(config)
                _persist(config)
            except (OSError, RuntimeError, ValueError) as exc:
                print(f"[ERROR DE VOZ] {exc}")
        elif choice == "10":
            _persist(config)
            return
        else:
            print("Opción no reconocida.")


def _show_audio_guide() -> None:
    print(
        """
AUDIO PARA OBS Y TIKTOK LIVE STUDIO
• La voz sale por el dispositivo de reproducción predeterminado de Windows.
• OBS: agrega “Captura de salida de audio” para incluirla en el directo.
  Para aislarla, prueba “Captura de audio de aplicación” con PowerShell.
• TikTok LIVE Studio: activa la captura de sonido del escritorio/dispositivo
  donde se reproduce la voz. Los nombres de los controles dependen de la versión.
• Ajusta el volumen aquí y también en el mezclador de OBS/Live Studio.
• Si quieres aislar la voz del resto del escritorio, puedes configurar un
  cable de audio virtual compatible como salida predeterminada de Windows y
  añadir ese cable como fuente de entrada en el programa de transmisión.
  Ese controlador es opcional, de terceros y no se instala ni descarga aquí.
• Para escucharla localmente y emitirla a la vez, activa el monitoreo de esa
  fuente en OBS. Evita capturarla dos veces para no crear eco.
"""
    )


def _show_quick_guide() -> None:
    print(
        """
AYUDA RÁPIDA

Instalar voces descargables:
1. En el menú principal, escribe 3 y pulsa Enter para abrir Ajustes.
2. Escribe 2 y pulsa Enter para Gestionar voces.
3. Escribe 2 para instalar/usar voces Piper (o, si Piper ya es el motor,
   escribe 1 para descargar más).
4. Elige una o varias voces por número: por ejemplo, 1,3. Confirma la descarga
   con s. Los archivos se guardan en data\\voices y no se vuelven a descargar
   si ya están instalados.
5. Elige qué voces activar. Pulsa Enter para conservar las que ya estaban
   activas. Para cambiar a Piper también puedes abrir Ajustes > opción 9.

Para omitir pasos:
• En una pregunta con [Enter = ...], pulsa Enter para conservar ese valor.
• En la selección de descargas Piper, Enter omite la descarga por ahora.
• El usuario de TikTok y una voz activa son obligatorios para conectar. Si
  omites la descarga y aún no tienes voces Piper, vuelve a elegir el motor.
• Si prefieres no usar Piper, elige voces de Windows o el motor que ya tengas.

Mientras está conectado:
• Haz clic en la ventana de esta consola y pulsa R para repetir el último
  comentario que se leyó en voz alta.
• Pulsa S para saltar el siguiente comentario pendiente. No interrumpe el que
  ya se está reproduciendo.
• Pulsa Ctrl+C para detener y volver al menú.
• Las teclas solo se leen desde esta consola; no son atajos globales. Si otra
  ventana está activa, sus teclas no controlan este programa.
"""
    )


def run(config: dict[str, Any]) -> None:
    if not config["username"] or not config["voice_names"]:
        first_run(config)
    print("\nTikTok LIVE Reader — Made by CJVM (HoJ)")
    while True:
        print(
            "\nTikTok LIVE TTS"
            "\n──────────────────────────────"
            f"\n  Usuario: @{config['username'] or 'sin configurar'}"
            f"\n  Motor: {config['tts_provider']}"
            f"\n  Voces: {', '.join(config['voice_names']) or 'sin configurar'}"
            f"\n  Volumen: {config['volume']}%  ·  Cola: {config['queue_size']}"
            "\n\n  1 / conectar  — Conectar y leer comentarios"
            "\n  2 / probar    — Probar voz"
            "\n  3 / ajustes   — Preferencias"
            "\n  4 / audio     — Ayuda para OBS / TikTok LIVE Studio"
            "\n  5 / ayuda     — Voces, pasos opcionales y teclas"
            "\n  6 / salir     — Cerrar"
            "\n"
        )
        choice = _ask(">>>", "1").lower()
        if choice in {"1", "conectar"}:
            if not config["username"]:
                print("Configura primero tu nombre de usuario.")
                continue
            try:
                connect_and_read(config["username"], config)
            except KeyboardInterrupt:
                print("\nConexión detenida.")
            except (RuntimeError, ValueError) as exc:
                print(f"\n[ERROR] {exc}")
        elif choice in {"2", "probar"}:
            try:
                if config["tts_provider"] == "elevenlabs":
                    consent = _ask(
                        "La prueba enviará texto a ElevenLabs y consumirá cuota. "
                        "¿Continuar? (s/n)",
                        "n",
                    ).lower()
                    if consent not in {"s", "si", "sí", "y", "yes"}:
                        continue
                run_test_comment(config)
            except (RuntimeError, OSError) as exc:
                print(f"[ERROR DE VOZ] {exc}")
        elif choice in {"3", "ajustes"}:
            try:
                _settings(config)
            except (RuntimeError, OSError) as exc:
                print(f"[ERROR DE AJUSTES] {exc}")
        elif choice in {"4", "audio"}:
            _show_audio_guide()
        elif choice in {"5", "ayuda", "help"}:
            _show_quick_guide()
        elif choice in {"6", "salir"}:
            print("Hasta luego — Made by CJVM (HoJ).")
            return
        else:
            print("Opción no reconocida.")
