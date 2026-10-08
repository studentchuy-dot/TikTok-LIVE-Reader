"""Small, accessible Windows window for chat, connection, and voice settings."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from .config import save_config
from .connector import connect_and_read, normalize_username
from .speech import list_voices

PROFILE_LABELS = {
    "natural": "Natural",
    "ágil": "Ágil",
    "pausada": "Pausada",
    "energética": "Energética",
}
PROFILE_RATES = {
    "Natural": ("natural", 0),
    "Ágil": ("ágil", 2),
    "Pausada": ("pausada", -2),
    "Energética": ("energética", 1),
}
MODE_LABELS = {
    "per_user": "Una voz por persona",
    "rotate": "Alternar por comentario",
}


class DesktopApp:
    """Keep every common action visible in a single resizable window."""

    def __init__(self, root: tk.Tk, config: dict[str, Any]) -> None:
        self.root = root
        self.config = config
        self.events: queue.Queue[tuple[Any, ...]] = queue.Queue()
        self.stop_event: threading.Event | None = None
        self.connection_thread: threading.Thread | None = None
        self._save_job: str | None = None
        self._closing = False
        self._connection_error = False
        self._voice_names: list[str] = []

        self.root.title("TikTok LIVE Reader — CJVM (HoJ)")
        self.root.geometry("860x560")
        self.root.minsize(760, 500)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self._load_voices()
        self._sync_controls()
        self.root.after(100, self._process_events)

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            header, text="TikTok LIVE Reader", font=("Segoe UI", 17, "bold")
        ).pack(side="left")
        ttk.Label(
            header, text="Made by CJVM (HoJ)", font=("Segoe UI", 9)
        ).pack(side="right", anchor="s", padx=(8, 2), pady=4)

        if not self.config["username"] or not self.config["voice_names"]:
            ttk.Label(
                outer,
                text=(
                    "Primeros pasos: escribe tu usuario, marca una o varias voces y pulsa "
                    "Conectar. Los ajustes se guardan solos."
                ),
                wraplength=860,
                justify="left",
            ).grid(row=1, column=0, sticky="ew", pady=(5, 8))

        connection = ttk.LabelFrame(outer, text="Tu transmisión", padding=8)
        connection.grid(row=2, column=0, sticky="ew", pady=(0, 9))
        connection.columnconfigure(1, weight=1)
        ttk.Label(connection, text="Usuario TikTok").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.username = tk.StringVar(value=self.config["username"])
        self.username_entry = ttk.Entry(connection, textvariable=self.username)
        self.username_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.username_entry.bind("<FocusOut>", self._save_username)
        self.username_entry.bind("<Return>", lambda _event: self.start_connection())
        self.connect_button = ttk.Button(
            connection, text="Conectar y leer", command=self.start_connection
        )
        self.connect_button.grid(row=0, column=2, padx=(0, 5))
        self.stop_button = ttk.Button(
            connection, text="Detener", command=self.stop_connection, state="disabled"
        )
        self.stop_button.grid(row=0, column=3)

        content = ttk.Panedwindow(outer, orient="horizontal")
        content.grid(row=3, column=0, sticky="nsew")
        chat = ttk.LabelFrame(content, text="Comentarios del LIVE", padding=8)
        controls = ttk.LabelFrame(content, text="Controles", padding=10)
        content.add(chat, weight=4)
        content.add(controls, weight=2)

        chat.columnconfigure(0, weight=1)
        chat.rowconfigure(1, weight=1)
        chat_header = ttk.Frame(chat)
        chat_header.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        self.status = ttk.Label(chat_header, text="Listo. Introduce un usuario para empezar.")
        self.status.pack(side="left", fill="x", expand=True)
        ttk.Button(chat_header, text="Limpiar", command=self.clear_chat).pack(side="right")
        transcript_frame = ttk.Frame(chat)
        transcript_frame.grid(row=1, column=0, sticky="nsew")
        transcript_frame.columnconfigure(0, weight=1)
        transcript_frame.rowconfigure(0, weight=1)
        self.transcript = tk.Text(
            transcript_frame,
            state="disabled",
            wrap="word",
            height=12,
            padx=8,
            pady=8,
            font=("Segoe UI", 10),
        )
        self.transcript.tag_configure("nickname", foreground="#2457a6")
        scrollbar = ttk.Scrollbar(
            transcript_frame, orient="vertical", command=self.transcript.yview
        )
        self.transcript.configure(yscrollcommand=scrollbar.set)
        self.transcript.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        controls.columnconfigure(0, weight=1)
        controls.rowconfigure(1, weight=1)
        ttk.Label(controls, text="Voces (marca una o varias)").grid(
            row=0, column=0, sticky="w"
        )
        voice_frame = ttk.Frame(controls)
        voice_frame.grid(row=1, column=0, sticky="nsew", pady=(4, 2))
        voice_frame.columnconfigure(0, weight=1)
        voice_frame.rowconfigure(0, weight=1)
        self.voice_list = tk.Listbox(
            voice_frame,
            height=5,
            selectmode=tk.EXTENDED,
            exportselection=False,
            activestyle="dotbox",
            font=("Segoe UI", 9),
        )
        voice_scrollbar = ttk.Scrollbar(
            voice_frame, orient="vertical", command=self.voice_list.yview
        )
        self.voice_list.configure(yscrollcommand=voice_scrollbar.set)
        self.voice_list.grid(row=0, column=0, sticky="nsew")
        voice_scrollbar.grid(row=0, column=1, sticky="ns")
        self.voice_list.bind("<<ListboxSelect>>", self._voice_changed)
        ttk.Label(
            controls, text="Para varias voces: mantén Ctrl mientras seleccionas."
        ).grid(row=2, column=0, sticky="w", pady=(2, 8))

        volume_row = ttk.Frame(controls)
        volume_row.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        volume_row.columnconfigure(0, weight=1)
        ttk.Label(volume_row, text="Volumen").grid(row=0, column=0, sticky="w")
        self.volume_label = ttk.Label(volume_row, text="75%")
        self.volume_label.grid(row=0, column=1, sticky="e")
        self.volume = tk.IntVar(value=self.config["volume"])
        ttk.Scale(
            controls,
            from_=0,
            to=100,
            variable=self.volume,
            command=self._volume_changed,
        ).grid(row=4, column=0, sticky="ew", pady=(0, 7))

        ttk.Label(controls, text="Estilo de voz").grid(
            row=5, column=0, sticky="w"
        )
        self.profile = tk.StringVar(
            value=PROFILE_LABELS.get(self.config["profile"], "Natural")
        )
        ttk.Combobox(
            controls,
            textvariable=self.profile,
            values=list(PROFILE_RATES),
            state="readonly",
        ).grid(row=6, column=0, sticky="ew", pady=(2, 7))
        self.profile.trace_add("write", self._profile_changed)

        ttk.Label(controls, text="Reparto de voces").grid(
            row=7, column=0, sticky="w"
        )
        self.voice_mode = tk.StringVar()
        ttk.Combobox(
            controls,
            textvariable=self.voice_mode,
            values=list(MODE_LABELS.values()),
            state="readonly",
        ).grid(row=8, column=0, sticky="ew", pady=(2, 7))
        self.voice_mode.trace_add("write", self._voice_mode_changed)

        self.read_names = tk.BooleanVar(value=self.config["speak_usernames"])
        ttk.Checkbutton(
            controls,
            text="Leer el nombre del comentarista",
            variable=self.read_names,
            command=self._read_names_changed,
        ).grid(row=9, column=0, sticky="w", pady=(0, 7))

        buttons = ttk.Frame(controls)
        buttons.grid(row=10, column=0, sticky="ew")
        for column in range(2):
            buttons.columnconfigure(column, weight=1)
        self.test_button = ttk.Button(
            buttons, text="Probar voz", command=self.test_voice
        )
        self.test_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(
            buttons, text="Ayuda OBS", command=self.show_audio_help
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.footer = ttk.Label(
            outer,
            text="Los cambios se guardan automáticamente · No necesitas una contraseña de TikTok.",
            anchor="w",
        )
        self.footer.grid(row=4, column=0, sticky="ew", pady=(8, 0))

    def _load_voices(self) -> None:
        try:
            voices = list_voices()
        except (OSError, RuntimeError, ValueError) as exc:
            self._set_status("error", f"No pude cargar las voces de Windows: {exc}")
            return
        self._voice_names = [voice["name"] for voice in voices]
        for voice in voices:
            self.voice_list.insert(
                "end", f"{voice['name']}  ·  {voice['culture']}"
            )
        selected = set(self.config["voice_names"])
        if not selected and voices:
            spanish = next(
                (voice["name"] for voice in voices if voice["culture"].lower().startswith("es")),
                voices[0]["name"],
            )
            selected = {spanish}
        for index, name in enumerate(self._voice_names):
            if name in selected:
                self.voice_list.selection_set(index)
        if not voices:
            self._set_status(
                "error",
                "Windows no tiene una voz compatible. Instala una en Configuración > Accesibilidad > Voz.",
            )
        elif selected - set(self._voice_names):
            self._set_status(
                "warning",
                "Una voz guardada ya no está instalada. Elige una voz disponible.",
            )
        elif self.config["voice_names"] != self._selected_voice_names():
            self.config["voice_names"] = self._selected_voice_names()
            self._save_settings()
        if not self.config["username"] or not self.config["voice_names"]:
            return
        if self.status.cget("foreground") not in {"#b42318", "#b54708"}:
            self._set_status("ready", "Listo. Pulsa «Conectar y leer» cuando estés en LIVE.")

    def _selected_voice_names(self) -> list[str]:
        return [
            self._voice_names[index]
            for index in self.voice_list.curselection()
            if index < len(self._voice_names)
        ]

    def _set_status(self, level: str, message: str) -> None:
        colors = {
            "ready": "#176b3a",
            "connected": "#176b3a",
            "connecting": "#2457a6",
            "retry": "#8a5a00",
            "warning": "#8a5a00",
            "error": "#b42318",
            "info": "#46505a",
        }
        self.status.configure(text=message, foreground=colors.get(level, "#46505a"))

    def _append_comment(self, nickname: str, text: str) -> None:
        self.transcript.configure(state="normal")
        self.transcript.insert("end", f"{nickname or 'Usuario'}: ", "nickname")
        self.transcript.insert("end", text + "\n")
        line_count = int(self.transcript.index("end-1c").split(".")[0])
        if line_count > 500:
            self.transcript.delete("1.0", f"{line_count - 500}.0")
        self.transcript.see("end")
        self.transcript.configure(state="disabled")

    def _process_events(self) -> None:
        if self._closing:
            return
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event[0] == "status":
                self._set_status(str(event[1]), str(event[2]))
                if event[1] == "error":
                    self._connection_error = True
            elif event[0] == "comment":
                self._append_comment(str(event[1]), str(event[2]))
            elif event[0] == "finished":
                self.stop_event = None
                self.connect_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                self.test_button.configure(state="normal")
                if not self._connection_error:
                    self._set_status("ready", "Desconectado. Puedes iniciar otro LIVE.")
            elif event[0] == "test_finished":
                self.test_button.configure(state="normal")
        self.root.after(100, self._process_events)

    def _save_settings(self) -> None:
        self._save_job = None
        try:
            save_config(self.config)
        except (OSError, ValueError) as exc:
            self._set_status("error", f"No se pudieron guardar los ajustes: {exc}")
            return
        if not self._closing:
            self.footer.configure(text="Ajustes guardados automáticamente.")

    def _schedule_save(self) -> None:
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(350, self._save_settings)

    def _save_username(self, _event: object | None = None) -> None:
        try:
            self.config["username"] = normalize_username(self.username.get())
        except ValueError:
            if self.username.get().strip():
                self._set_status("warning", "Revisa el nombre de usuario de TikTok.")
            return
        self.username.set(self.config["username"])
        self._schedule_save()

    def _voice_changed(self, _event: object | None = None) -> None:
        self.config["voice_names"] = self._selected_voice_names()
        self._schedule_save()

    def _volume_changed(self, value: str) -> None:
        self.config["volume"] = max(0, min(100, round(float(value))))
        self.volume_label.configure(text=f"{self.config['volume']}%")
        self._schedule_save()

    def _profile_changed(self, *_args: object) -> None:
        profile = PROFILE_RATES.get(self.profile.get())
        if profile:
            self.config["profile"], self.config["rate"] = profile
            self._schedule_save()

    def _voice_mode_changed(self, *_args: object) -> None:
        selected = self.voice_mode.get()
        self.config["voice_mode"] = next(
            (key for key, label in MODE_LABELS.items() if label == selected),
            self.config["voice_mode"],
        )
        self._schedule_save()

    def _read_names_changed(self) -> None:
        self.config["speak_usernames"] = self.read_names.get()
        self._schedule_save()

    def _sync_controls(self) -> None:
        self.volume_label.configure(text=f"{self.config['volume']}%")
        self.voice_mode.set(MODE_LABELS[self.config["voice_mode"]])

    def start_connection(self) -> None:
        if self.stop_event is not None:
            return
        try:
            username = normalize_username(self.username.get())
        except ValueError as exc:
            messagebox.showinfo("Escribe tu usuario", str(exc), parent=self.root)
            self.username_entry.focus_set()
            return
        voices = self._selected_voice_names()
        if not voices:
            messagebox.showinfo(
                "Elige una voz",
                "Marca al menos una voz en el panel Controles.",
                parent=self.root,
            )
            return
        self.config["username"] = username
        self.config["voice_names"] = voices
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
            self._save_job = None
        try:
            save_config(self.config)
        except (OSError, ValueError) as exc:
            messagebox.showerror(
                "No se pudo guardar", f"Corrige el problema antes de conectar:\n{exc}", parent=self.root
            )
            return

        self.username.set(username)
        self.stop_event = threading.Event()
        event = self.stop_event
        self._connection_error = False
        self.connect_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.test_button.configure(state="disabled")
        self._set_status("connecting", f"Conectando con @{username}…")
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")

        def connect() -> None:
            try:
                connect_and_read(
                    username,
                    self.config,
                    stop_event=event,
                    on_status=lambda level, text: self.events.put(
                        ("status", level, text)
                    ),
                    comment_callback=lambda nickname, text: self.events.put(
                        ("comment", nickname, text)
                    ),
                )
            except Exception as exc:
                self.events.put(("status", "error", f"No se pudo iniciar: {exc}"))
            finally:
                self.events.put(("finished",))

        self.connection_thread = threading.Thread(
            target=connect, name="tiktok-connection", daemon=True
        )
        self.connection_thread.start()

    def stop_connection(self) -> None:
        if self.stop_event is None:
            return
        self.stop_event.set()
        self._set_status("warning", "Cerrando la conexión…")
        self.stop_button.configure(state="disabled")

    def test_voice(self) -> None:
        voices = self._selected_voice_names()
        if not voices:
            messagebox.showinfo(
                "Elige una voz",
                "Marca al menos una voz antes de probarla.",
                parent=self.root,
            )
            return
        self.config["voice_names"] = voices
        self.test_button.configure(state="disabled")
        self._set_status("info", "Reproduciendo una prueba corta de voz…")

        def test() -> None:
            try:
                from .connector import run_test_comment

                run_test_comment(self.config)
                self.events.put(("status", "ready", "La prueba de voz terminó."))
            except Exception as exc:
                self.events.put(("status", "error", f"Error de voz: {exc}"))
            finally:
                self.events.put(("test_finished",))

        threading.Thread(target=test, name="voice-test", daemon=True).start()

    def clear_chat(self) -> None:
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")

    def show_audio_help(self) -> None:
        messagebox.showinfo(
            "Audio para OBS y LIVE Studio",
            "La voz sale por el dispositivo de audio predeterminado de Windows.\n\n"
            "OBS: añade «Captura de salida de audio» y elige ese dispositivo. "
            "En LIVE Studio, activa la captura del audio del escritorio.\n\n"
            "Para separar solo la voz, puedes configurar por tu cuenta un cable "
            "de audio virtual como dispositivo predeterminado y añadirlo como "
            "entrada en el programa de transmisión.\n\n"
            "Ajusta el volumen aquí y en el mezclador. No captures la misma voz "
            "dos veces: puede producir eco.",
            parent=self.root,
        )

    def close(self) -> None:
        self._closing = True
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
            self._save_job = None
        try:
            save_config(self.config)
        except (OSError, ValueError) as exc:
            messagebox.showerror(
                "No se pudieron guardar los ajustes",
                str(exc),
                parent=self.root,
            )
        if self.stop_event is not None:
            self.stop_event.set()
        self.root.destroy()


def run_desktop(config: dict[str, Any]) -> None:
    root = tk.Tk()
    DesktopApp(root, config)
    root.mainloop()
