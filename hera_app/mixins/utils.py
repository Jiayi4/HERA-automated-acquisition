import threading
import tkinter as tk


class UtilsMixin:
    def _safe_after(self, delay_ms, callback):
        if self.is_closing or not self.winfo_exists():
            return None
        try:
            return self.after(delay_ms, callback)
        except tk.TclError:
            return None

    def _log_async(self, message):
        if threading.current_thread() is threading.main_thread():
            self.log(message)
        else:
            self._safe_after(0, lambda: self.log(message))

    def _set_var_async(self, var, value):
        def setter():
            if self.is_closing:
                return
            var.set(value)
            self._draw_live_view_placeholder()
            self.render_current_hyper_band()
        self._safe_after(0, setter)
