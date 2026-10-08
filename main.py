"""Console entry point for TikTok LIVE Reader."""

from __future__ import annotations

import sys

from livevoice.config import load_config


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(errors="replace")

    if sys.platform != "win32":
        return

    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    get_console_window = kernel32.GetConsoleWindow
    get_console_window.restype = ctypes.c_void_p
    window = get_console_window()
    if window:
        show_window = user32.ShowWindow
        show_window.argtypes = (ctypes.c_void_p, ctypes.c_int)
        show_window.restype = ctypes.c_bool
        show_window(window, 9)
        show_window(window, 3)


def main() -> int:
    _configure_console()
    if sys.platform != "win32":
        print("Esta versión usa voces SAPI de Windows y solo funciona en Windows.")
        return 1
    try:
        config = load_config()
        from livevoice.app import run

        run(config)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[ERROR] No se pudo iniciar TikTok LIVE Reader: {exc}")
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nCierre solicitado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
