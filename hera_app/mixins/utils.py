import queue
import threading
import tkinter as tk


class UtilsMixin:
    def _is_ui_thread(self):
        return threading.get_ident() == getattr(self, "ui_thread_id", None)

    def _start_ui_call_queue_pump(self):
        if not self._is_ui_thread() or getattr(self, "is_closing", False):
            return
        if getattr(self, "ui_queue_poll_job", None):
            return
        self._drain_ui_call_queue()

    def _drain_ui_call_queue(self):
        if getattr(self, "is_closing", False):
            self.ui_queue_poll_job = None
            return

        ui_queue = getattr(self, "ui_call_queue", None)
        if ui_queue is not None:
            for _ in range(200):
                try:
                    delay_ms, callback = ui_queue.get_nowait()
                except queue.Empty:
                    break
                self._safe_after(delay_ms, callback)

        try:
            self.ui_queue_poll_job = self.after(
                getattr(self, "ui_queue_poll_interval_ms", 25),
                self._drain_ui_call_queue,
            )
        except (RuntimeError, tk.TclError):
            self.ui_queue_poll_job = None

    def _safe_after(self, delay_ms, callback):
        if getattr(self, "is_closing", False):
            return None
        if not self._is_ui_thread():
            ui_queue = getattr(self, "ui_call_queue", None)
            if ui_queue is not None:
                ui_queue.put((delay_ms, callback))
            return None

        def guarded_callback():
            if getattr(self, "is_closing", False):
                return
            try:
                exists = self.winfo_exists()
            except (RuntimeError, tk.TclError):
                return
            if not exists:
                return
            try:
                callback()
            except tk.TclError:
                return
            except RuntimeError as exc:
                if "main thread is not in main loop" in str(exc):
                    return
                raise

        try:
            if not self.winfo_exists():
                return None
            return self.after(delay_ms, guarded_callback)
        except (RuntimeError, tk.TclError):
            return None

    def _log_async(self, message, detail=None):
        if getattr(self, "is_closing", False):
            return
        if self._is_ui_thread():
            self.log(message, detail=detail)
        else:
            self._safe_after(0, lambda: self.log(message, detail=detail))

    def _set_var_async(self, var, value):
        def setter():
            if self.is_closing:
                return
            var.set(value)
        self._safe_after(0, setter)
