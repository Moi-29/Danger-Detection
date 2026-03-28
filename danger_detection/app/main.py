"""
Tkinter shell for Danger Detection: fire & smoke via threaded YOLO inference.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

from PIL import Image, ImageTk

from danger_detection.app.alert_notify import push_alert_to_pwa
from danger_detection.app.detector import FireSmokeDetector, FramePacket
from danger_detection.app.utils import bgr_to_rgb, resize_to_fit


class DangerDetectionApp:
    POLL_MS = 33

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Danger Detection — Fire & Smoke")
        self.root.minsize(640, 480)

        self.detector = FireSmokeDetector(on_alert=push_alert_to_pwa)
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._poll_job: Optional[str] = None

        self._build_ui()

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        btn_row = ttk.Frame(main)
        btn_row.pack(fill=tk.X, pady=(0, 8))

        self.btn_start = ttk.Button(
            btn_row, text="Start Detection", command=self._on_start
        )
        self.btn_start.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_stop = ttk.Button(
            btn_row, text="Stop Detection", command=self._on_stop, state=tk.DISABLED
        )
        self.btn_stop.pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="Stopped")
        status = ttk.Label(main, textvariable=self.status_var, font=("TkDefaultFont", 11))
        status.pack(anchor=tk.W, pady=(0, 4))

        self.video_label = ttk.Label(main)
        self.video_label.pack(fill=tk.BOTH, expand=True)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_start(self) -> None:
        self.status_var.set("Starting…")
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        try:
            self.detector.start()
        except FileNotFoundError as e:
            self.status_var.set(f"Error: {e}")
            self.btn_start.config(state=tk.NORMAL)
            self.btn_stop.config(state=tk.DISABLED)
            return
        except Exception as e:
            self.status_var.set(f"Error: {e}")
            self.btn_start.config(state=tk.NORMAL)
            self.btn_stop.config(state=tk.DISABLED)
            return
        self.status_var.set("Detecting…")
        self._schedule_poll()

    def _on_stop(self) -> None:
        if self._poll_job is not None:
            self.root.after_cancel(self._poll_job)
            self._poll_job = None
        self.detector.stop()
        self.status_var.set("Stopped")
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self.video_label.configure(image="")

    def _schedule_poll(self) -> None:
        self._poll_job = self.root.after(self.POLL_MS, self._poll_loop)

    def _poll_loop(self) -> None:
        err = self.detector.get_error()
        if err:
            self.status_var.set(f"Error: {err}")
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
            self.status_var.set("Stopped")
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
        self.video_label.configure(image=self._photo)
        detail = packet.summary
        self.status_var.set(f"Detecting… — {detail}")

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
