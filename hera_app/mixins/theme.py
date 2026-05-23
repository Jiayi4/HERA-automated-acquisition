import tkinter as tk
from tkinter import ttk


class ThemeMixin:
    def _configure_theme(self):
        palettes = {
            "dark": {
                "bg": "#14181d",
                "panel": "#1d232a",
                "panel_alt": "#232a32",
                "field": "#0f1318",
                "border": "#3a434d",
                "text": "#e7edf5",
                "muted": "#9aa6b2",
                "accent": "#ff8b3d",
                "accent_soft": "#ffb37a",
                "success": "#7ad97a",
                "danger": "#ff6a6a",
                "canvas": "#101418",
                "canvas_grid": "#1b2229",
                "title": "#f3f6fb",
                "button_text": "#e7edf5",
                "accent_text": "#111111",
            },
            "light": {
                "bg": "#eef2f6",
                "panel": "#ffffff",
                "panel_alt": "#e5ebf2",
                "field": "#f7f9fc",
                "border": "#c8d2df",
                "text": "#16202a",
                "muted": "#5c6b79",
                "accent": "#d96f22",
                "accent_soft": "#a9571d",
                "success": "#247a3d",
                "danger": "#ba3030",
                "canvas": "#f4f7fa",
                "canvas_grid": "#dde5ee",
                "title": "#101820",
                "button_text": "#16202a",
                "accent_text": "#ffffff",
            },
        }
        self.theme = palettes.get(self.theme_mode, palettes["dark"])
        self.configure(bg=self.theme["bg"])
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("Dark.Treeview", background=self.theme["panel"], fieldbackground=self.theme["panel"], foreground=self.theme["text"], rowheight=28, bordercolor=self.theme["border"], lightcolor=self.theme["border"], darkcolor=self.theme["border"])
        style.configure("Dark.Treeview.Heading", background=self.theme["panel_alt"], foreground=self.theme["text"], relief="flat")
        style.map("Dark.Treeview", background=[("selected", self.theme["accent"])], foreground=[("selected", "#111111")])
        style.configure("Dark.TSeparator", background=self.theme["border"])
        style.configure("Left.TNotebook", background=self.theme["bg"], borderwidth=0)
        style.configure("Left.TNotebook.Tab", background=self.theme["panel_alt"], foreground=self.theme["text"], padding=[12, 5], font=("Segoe UI", 10))
        style.map("Left.TNotebook.Tab", background=[("selected", self.theme["accent"]), ("active", self.theme["panel"])], foreground=[("selected", self.theme["accent_text"])])

        self.option_add("*Font", "{Segoe UI} 10")
        self.option_add("*Background", self.theme["panel"])
        self.option_add("*Foreground", self.theme["text"])
        self.option_add("*Label.Background", self.theme["panel"])
        self.option_add("*Label.Foreground", self.theme["text"])
        self.option_add("*LabelFrame.Background", self.theme["panel"])
        self.option_add("*LabelFrame.Foreground", self.theme["text"])
        self.option_add("*Button.Background", self.theme["panel_alt"])
        self.option_add("*Button.Foreground", self.theme["text"])
        self.option_add("*Entry.Background", self.theme["field"])
        self.option_add("*Entry.Foreground", self.theme["text"])
        self.option_add("*Text.Background", self.theme["field"])
        self.option_add("*Text.Foreground", self.theme["text"])
        if hasattr(self, "theme_button_var"):
            self.theme_button_var.set("Dark Mode" if self.theme_mode == "light" else "Light Mode")
        self._apply_theme_recursive(self)

    def _apply_theme_recursive(self, widget):
        cls = widget.winfo_class()
        try:
            if cls in {"Frame", "Labelframe", "LabelFrame", "Toplevel"}:
                widget.configure(bg=self.theme["panel"], highlightbackground=self.theme["border"], highlightcolor=self.theme["border"])
            elif cls == "Panedwindow":
                widget.configure(bg=self.theme["bg"], sashrelief="flat")
            elif cls == "Canvas":
                widget.configure(bg=self.theme["canvas"], highlightbackground=self.theme["border"], highlightcolor=self.theme["border"])
            elif cls == "Label":
                widget.configure(bg=self.theme["panel"], fg=self.theme["text"])
            elif cls == "Button":
                widget.configure(bg=self.theme["panel_alt"], fg=self.theme["button_text"], activebackground=self.theme["accent"], activeforeground=self.theme["accent_text"], relief="flat", bd=0, padx=10, pady=6, cursor="hand2")
            elif cls == "Entry":
                widget.configure(bg=self.theme["field"], fg=self.theme["text"], insertbackground=self.theme["accent_soft"], relief="flat", bd=6)
            elif cls == "Text":
                widget.configure(bg=self.theme["field"], fg=self.theme["text"], insertbackground=self.theme["accent_soft"], relief="flat", bd=0)
            elif cls == "Checkbutton":
                widget.configure(bg=self.theme["panel"], fg=self.theme["text"], selectcolor=self.theme["field"], activebackground=self.theme["panel"], activeforeground=self.theme["text"])
            elif cls == "Scale":
                widget.configure(bg=self.theme["panel"], fg=self.theme["text"], troughcolor=self.theme["field"], activebackground=self.theme["accent"], highlightthickness=0)
            elif cls == "Menubutton":
                widget.configure(bg=self.theme["panel_alt"], fg=self.theme["button_text"], activebackground=self.theme["accent"], activeforeground=self.theme["accent_text"], relief="flat", bd=0, highlightthickness=0)
                try:
                    widget["menu"].configure(bg=self.theme["panel_alt"], fg=self.theme["text"], activebackground=self.theme["accent"], activeforeground=self.theme["accent_text"])
                except Exception:
                    pass
        except Exception:
            pass

        for child in widget.winfo_children():
            self._apply_theme_recursive(child)

    def toggle_theme_mode(self):
        self.theme_mode = "light" if self.theme_mode == "dark" else "dark"
        self._configure_theme()
        self._draw_live_view_placeholder()
        self.render_current_hyper_band()
