"""
Tkinter shell for Danger Detection: fire & smoke via threaded YOLO inference.
"""

from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import ttk
from typing import Optional

from PIL import Image, ImageTk

from danger_detection.app.alert_notify import push_alert_to_pwa
from danger_detection.app.detector import FireSmokeDetector, FramePacket
from danger_detection.app.utils import bgr_to_rgb, resize_to_fit


# Security / SOC-style palette (dark, high contrast, minimal noise)
_BG = "#0a0c0f"
_SURFACE = "#11161d"
_SURFACE_ELEV = "#161d27"
_BORDER = "#2d3744"
_TEXT = "#e8edf4"
_TEXT_MUTED = "#8b98a8"
_ACCENT = "#3fb950"
_ACCENT_DIM = "#238636"
_DANGER = "#f85149"
_DANGER_BG = "#2d1b1b"
_AMBER = "#d29922"

# Tk font tuples must use a single family name; multiple names in one tuple break
# (e.g. size is mis-read). DejaVu ships on most Linux distros; Tk falls back if missing.
_F_UI = "DejaVu Sans"
_F_MONO = "DejaVu Sans Mono"


def _maybe_print_pwa_tip() -> None:
    """Explain that the desktop app does not start the API; the PWA needs uvicorn."""
    if os.environ.get("DANGER_DETECTION_NO_PWA_TIP", "").strip():
        return
    print(
        "\nTip: The web app talks to the API on port 8000. This window only runs the camera.\n"
        "In another terminal (repo root, venv active):\n"
        "  uvicorn danger_detection.app.pwa_server:app --host 127.0.0.1 --port 8000\n"
        "Then open http://localhost:8000 — alerts from this app POST to that server.\n"
        "(Suppress this message: export DANGER_DETECTION_NO_PWA_TIP=1)\n",
        file=sys.stderr,
    )


class DangerDetectionApp:
    POLL_MS = 33

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Security Monitor — Hazard Detection")
        self.root.minsize(720, 520)
        self.root.configure(bg=_BG)

        self.detector = FireSmokeDetector(on_alert=push_alert_to_pwa)
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._poll_job: Optional[str] = None

        self._apply_styles()
        self._build_ui()
        _maybe_print_pwa_tip()

    def _apply_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "App.TFrame",
            background=_BG,
        )
        style.configure(
            "Card.TFrame",
            background=_SURFACE,
            relief="flat",
        )
        style.configure(
            "TLabelframe",
            background=_SURFACE,
            foreground=_TEXT_MUTED,
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "TLabelframe.Label",
            background=_SURFACE,
            foreground=_TEXT_MUTED,
            font=(_F_UI, 9),
        )
        style.configure(
            "Title.TLabel",
            background=_BG,
            foreground=_TEXT,
            font=(_F_UI, 20, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background=_BG,
            foreground=_TEXT_MUTED,
            font=(_F_UI, 11),
        )
        style.configure(
            "Badge.TLabel",
            background=_SURFACE_ELEV,
            foreground=_TEXT_MUTED,
            font=(_F_UI, 9, "bold"),
            padding=(10, 4),
        )
        style.configure(
            "BadgeLive.TLabel",
            background="#0d2818",
            foreground=_ACCENT,
            font=(_F_UI, 9, "bold"),
            padding=(10, 4),
        )
        style.configure(
            "BadgeErr.TLabel",
            background="#2d2208",
            foreground=_AMBER,
            font=(_F_UI, 9, "bold"),
            padding=(10, 4),
        )
        style.configure(
            "Status.TLabel",
            background=_SURFACE,
            foreground=_TEXT,
            font=(_F_MONO, 11),
            wraplength=900,
            justify=tk.LEFT,
        )
        style.configure(
            "StatusHdr.TLabel",
            background=_SURFACE,
            foreground=_TEXT_MUTED,
            font=(_F_UI, 9, "bold"),
        )
        style.configure(
            "TSeparator",
            background=_BORDER,
        )
        style.configure(
            "Start.TButton",
            background=_ACCENT_DIM,
            foreground="#ffffff",
            font=(_F_UI, 10, "bold"),
            padding=(16, 10),
            borderwidth=0,
            focuscolor="none",
        )
        style.map(
            "Start.TButton",
            background=[("active", _ACCENT), ("disabled", "#2d333b")],
            foreground=[("disabled", "#6e7681")],
        )
        style.configure(
            "Stop.TButton",
            background=_SURFACE_ELEV,
            foreground=_DANGER,
            font=(_F_UI, 10, "bold"),
            padding=(16, 10),
            borderwidth=1,
            focuscolor="none",
        )
        style.map(
            "Stop.TButton",
            background=[("active", _DANGER_BG), ("disabled", _SURFACE_ELEV)],
            foreground=[("disabled", "#6e7681")],
        )

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, style="App.TFrame", padding=(16, 14))
        main.pack(fill=tk.BOTH, expand=True)

        # —— Header ——
        head = ttk.Frame(main, style="App.TFrame")
        head.pack(fill=tk.X, pady=(0, 12))

        head_left = ttk.Frame(head, style="App.TFrame")
        head_left.pack(side=tk.LEFT, fill=tk.Y)

        ttk.Label(
            head_left,
            text="SECURITY MONITOR",
            style="Title.TLabel",
        ).pack(anchor=tk.W)
        ttk.Label(
            head_left,
            text="Fire, smoke & motion — live hazard detection",
            style="Subtitle.TLabel",
        ).pack(anchor=tk.W, pady=(2, 0))

        self.badge_label = ttk.Label(
            head,
            text=" STANDBY ",
            style="Badge.TLabel",
        )
        self.badge_label.pack(side=tk.RIGHT, anchor=tk.NE, padx=(12, 0))

        ttk.Separator(main, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 12))

        # —— Controls ——
        ctrl = ttk.Frame(main, style="App.TFrame")
        ctrl.pack(fill=tk.X, pady=(0, 12))

        self.btn_start = ttk.Button(
            ctrl,
            text="Start monitoring",
            command=self._on_start,
            style="Start.TButton",
        )
        self.btn_start.pack(side=tk.LEFT, padx=(0, 10))

        self.btn_stop = ttk.Button(
            ctrl,
            text="Stop",
            command=self._on_stop,
            state=tk.DISABLED,
            style="Stop.TButton",
        )
        self.btn_stop.pack(side=tk.LEFT)

        # —— Status card ——
        status_card = ttk.Frame(main, style="Card.TFrame", padding=12)
        status_card.pack(fill=tk.X, pady=(0, 12))

        ttk.Label(
            status_card,
            text="SYSTEM STATUS",
            style="StatusHdr.TLabel",
        ).pack(anchor=tk.W)

        self.status_var = tk.StringVar(value="Stopped — ready to start monitoring.")
        ttk.Label(
            status_card,
            textvariable=self.status_var,
            style="Status.TLabel",
        ).pack(anchor=tk.W, fill=tk.X, pady=(6, 0))

        # —— Video (framed like a monitor bezel) ——
        bezel = tk.Frame(main, bg=_BORDER, padx=2, pady=2)
        bezel.pack(fill=tk.BOTH, expand=True)

        inner = tk.Frame(bezel, bg="#000000")
        inner.pack(fill=tk.BOTH, expand=True)

        self.video_label = tk.Label(
            inner,
            bg="#000000",
            fg=_TEXT_MUTED,
            text="Camera preview",
            font=(_F_UI, 12),
        )
        self.video_label.pack(fill=tk.BOTH, expand=True)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _set_badge(self, mode: str) -> None:
        if mode == "live":
            self.badge_label.configure(text=" LIVE ", style="BadgeLive.TLabel")
        elif mode == "error":
            self.badge_label.configure(text=" ERROR ", style="BadgeErr.TLabel")
        else:
            self.badge_label.configure(text=" STANDBY ", style="Badge.TLabel")

    def _on_start(self) -> None:
        self.status_var.set("Starting…")
        self._set_badge("live")
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        try:
            self.detector.start()
        except FileNotFoundError as e:
            self.status_var.set(f"Error: {e}")
            self._set_badge("error")
            self.btn_start.config(state=tk.NORMAL)
            self.btn_stop.config(state=tk.DISABLED)
            return
        except Exception as e:
            self.status_var.set(f"Error: {e}")
            self._set_badge("error")
            self.btn_start.config(state=tk.NORMAL)
            self.btn_stop.config(state=tk.DISABLED)
            return
        self.status_var.set("Monitoring active — waiting for camera frames…")
        self._schedule_poll()

    def _on_stop(self) -> None:
        if self._poll_job is not None:
            self.root.after_cancel(self._poll_job)
            self._poll_job = None
        self.detector.stop()
        self.status_var.set("Stopped — ready to start monitoring.")
        self._set_badge("standby")
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self.video_label.configure(image="")
        self.video_label.configure(text="Camera preview")

    def _schedule_poll(self) -> None:
        self._poll_job = self.root.after(self.POLL_MS, self._poll_loop)

    def _poll_loop(self) -> None:
        err = self.detector.get_error()
        if err:
            self.status_var.set(f"Error: {err}")
            self._set_badge("error")
            self.detector.stop()
            self.btn_start.config(state=tk.NORMAL)
            self.btn_stop.config(state=tk.DISABLED)
            self._poll_job = None
            return

        packet = self.detector.poll_frame()
        if packet is not None:
            self._show_frame(packet)

        if self.detector.is_running():
            self._schedule_poll()
        else:
            self.status_var.set("Stopped — ready to start monitoring.")
            self._set_badge("standby")
            self.btn_start.config(state=tk.NORMAL)
            self.btn_stop.config(state=tk.DISABLED)
            self._poll_job = None

    def _show_frame(self, packet: FramePacket) -> None:
        w = self.video_label.winfo_width() or 640
        h = self.video_label.winfo_height() or 480
        resized, _ = resize_to_fit(packet.frame_bgr, w, h)
        rgb = bgr_to_rgb(resized)
        img = Image.fromarray(rgb)
        self._photo = ImageTk.PhotoImage(image=img)
        self.video_label.configure(image=self._photo, text="")
        detail = packet.summary
        self.status_var.set(f"Monitoring — {detail}")
        self._set_badge("live")

    def _on_close(self) -> None:
        if self._poll_job is not None:
            self.root.after_cancel(self._poll_job)
        self.detector.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    DangerDetectionApp().run()


if __name__ == "__main__":
    main()
