import tkinter as tk
from tkinter import ttk


class ThemeMixin:
    def _configure_theme(self):
        palettes = {
            "dark": {
                "bg": "#111316",
                "panel": "#171a1f",
                "panel_section": "#1b2026",
                "panel_subsection": "#20262d",
                "panel_alt": "#2a3038",
                "button_bg": "#252b33",
                "button_active": "#303843",
                "field": "#0d0f12",
                "border": "#303842",
                "border_strong": "#47515e",
                "view_border": "#303842",
                "text": "#eef2f7",
                "muted": "#94a3b8",
                "accent": "#3f7fe2",
                "accent_active": "#5a93ee",
                "accent_soft": "#8eb6f5",
                "accent_orange": "#df8138",
                "accent_orange_active": "#ee9452",
                "success": "#65d28b",
                "danger": "#ef6b6b",
                "canvas": "#080c12",
                "canvas_grid": "#1b2430",
                "title": "#f8fafc",
                "button_text": "#eef2f7",
                "accent_text": "#ffffff",
                "orange_text": "#111827",
                "section_text": "#c5d0dd",
            },
            "light": {
                "bg": "#f4f7fb",
                "panel": "#ffffff",
                "panel_section": "#f7f9fc",
                "panel_subsection": "#eef3f8",
                "panel_alt": "#e7edf5",
                "button_bg": "#edf2f7",
                "button_active": "#dfe8f2",
                "field": "#ffffff",
                "border": "#cfd8e5",
                "border_strong": "#aebdcd",
                "view_border": "#bdd2ee",
                "text": "#182230",
                "muted": "#667085",
                "accent": "#326fd3",
                "accent_active": "#275fbf",
                "accent_soft": "#5689df",
                "accent_orange": "#c9732f",
                "accent_orange_active": "#b76626",
                "success": "#25834f",
                "danger": "#b93838",
                "canvas": "#f8fafc",
                "canvas_grid": "#dde5ee",
                "title": "#111827",
                "button_text": "#182230",
                "accent_text": "#ffffff",
                "orange_text": "#ffffff",
                "section_text": "#415064",
            },
        }
        self.theme = palettes.get(self.theme_mode, palettes["dark"])
        self.configure(bg=self.theme["bg"])
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "Dark.Treeview",
            background=self.theme["panel"],
            fieldbackground=self.theme["panel"],
            foreground=self.theme["text"],
            rowheight=23,
            bordercolor=self.theme["border"],
            lightcolor=self.theme["border"],
            darkcolor=self.theme["border"],
            relief="flat",
        )
        style.configure(
            "Dark.Treeview.Heading",
            background=self.theme["panel_alt"],
            foreground=self.theme["section_text"],
            relief="flat",
            padding=[4, 3],
        )
        style.map(
            "Dark.Treeview",
            background=[("selected", self.theme["accent"])],
            foreground=[("selected", self.theme["accent_text"])],
        )
        style.configure("Dark.TSeparator", background=self.theme["border"])
        view_border = self.theme.get("view_border", self.theme["border"])
        style.configure(
            "TNotebook",
            background=self.theme["bg"],
            borderwidth=0,
            tabmargins=[0, 0, 0, 0],
            relief="flat",
            lightcolor=view_border,
            darkcolor=view_border,
            bordercolor=view_border,
        )
        style.configure(
            "TNotebook.Tab",
            background=self.theme["panel_alt"],
            foreground=self.theme["muted"],
            padding=[9, 4],
            font=("Segoe UI", 9),
            borderwidth=1,
            relief="flat",
            lightcolor=view_border,
            darkcolor=view_border,
            bordercolor=view_border,
            focuscolor=view_border,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.theme["panel"]), ("active", self.theme["panel_section"])],
            foreground=[("selected", self.theme["text"]), ("active", self.theme["text"])],
        )
        style.configure(
            "Left.TNotebook",
            background=self.theme["bg"],
            borderwidth=0,
            tabmargins=[0, 0, 0, 0],
            relief="flat",
            lightcolor=self.theme["bg"],
            darkcolor=self.theme["bg"],
            bordercolor=self.theme["bg"],
        )
        style.configure(
            "Left.TNotebook.Tab",
            background=self.theme["panel_alt"],
            foreground=self.theme["muted"],
            padding=[9, 4],
            font=("Segoe UI", 9),
            borderwidth=1,
            relief="flat",
            lightcolor=self.theme["border"],
            darkcolor=self.theme["border"],
            bordercolor=self.theme["border"],
            focuscolor=self.theme["border"],
        )
        style.map(
            "Left.TNotebook.Tab",
            background=[("selected", self.theme["accent"]), ("active", self.theme["panel_section"])],
            foreground=[("selected", self.theme["accent_text"]), ("active", self.theme["text"])],
        )
        for progress_style in ("TProgressbar", "Horizontal.TProgressbar"):
            style.configure(
                progress_style,
                background=self.theme["accent"],
                troughcolor=self.theme["field"],
                bordercolor=self.theme["border"],
                lightcolor=self.theme["accent"],
                darkcolor=self.theme["accent"],
            )
        for scrollbar_style in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
            style.configure(
                scrollbar_style,
                background=self.theme["button_bg"],
                troughcolor=self.theme["bg"],
                bordercolor=self.theme["bg"],
                arrowcolor=self.theme["muted"],
                lightcolor=self.theme["button_bg"],
                darkcolor=self.theme["button_bg"],
                relief="flat",
            )
            style.map(
                scrollbar_style,
                background=[("active", self.theme["button_active"])],
                arrowcolor=[("active", self.theme["text"])],
            )

        self.option_add("*Font", "{Segoe UI} 9")
        self.option_add("*Background", self.theme["panel"])
        self.option_add("*Foreground", self.theme["text"])
        self.option_add("*Label.Background", self.theme["panel"])
        self.option_add("*Label.Foreground", self.theme["text"])
        self.option_add("*LabelFrame.Background", self.theme["panel"])
        self.option_add("*LabelFrame.Foreground", self.theme["section_text"])
        self.option_add("*LabelFrame.BorderWidth", 1)
        self.option_add("*LabelFrame.HighlightThickness", 1)
        self.option_add("*LabelFrame.HighlightBackground", self.theme["border"])
        self.option_add("*Button.Background", self.theme["button_bg"])
        self.option_add("*Button.Foreground", self.theme["text"])
        self.option_add("*Button.Relief", "flat")
        self.option_add("*Button.BorderWidth", 1)
        self.option_add("*Button.HighlightThickness", 1)
        self.option_add("*Button.HighlightBackground", self.theme["border"])
        self.option_add("*Button.HighlightColor", self.theme["accent"])
        self.option_add("*Button.DisabledForeground", self.theme["muted"])
        self.option_add("*Entry.Background", self.theme["field"])
        self.option_add("*Entry.Foreground", self.theme["text"])
        self.option_add("*Text.Background", self.theme["field"])
        self.option_add("*Text.Foreground", self.theme["text"])
        if hasattr(self, "theme_button_var"):
            self.theme_button_var.set("Dark Mode" if self.theme_mode == "light" else "Light Mode")
        self._apply_theme_recursive(self)

    def _safe_widget_bg(self, widget, fallback=None):
        try:
            return widget.cget("bg")
        except Exception:
            return fallback or self.theme["panel"]

    def _label_frame_bg(self, widget):
        parent = getattr(widget, "master", None)
        if parent is None:
            return self.theme["panel_section"]
        parent_bg = self._safe_widget_bg(parent, self.theme["panel"])
        parent_cls = parent.winfo_class()
        if parent_cls in {"Labelframe", "LabelFrame"} or parent_bg in {
            self.theme["panel_section"],
            self.theme["panel_subsection"],
        }:
            return self.theme["panel_subsection"]
        return self.theme["panel_section"]

    def _container_bg_for_widget(self, widget):
        cls = widget.winfo_class()
        if cls in {"Labelframe", "LabelFrame"}:
            return self._label_frame_bg(widget)
        parent = getattr(widget, "master", None)
        if parent is None:
            return self.theme["bg"]
        parent_cls = parent.winfo_class()
        if parent is self or parent_cls in {"Tk", "Toplevel", "Panedwindow"}:
            return self.theme["bg"]
        parent_bg = self._safe_widget_bg(parent, self.theme["panel"])
        if parent_cls in {"Labelframe", "LabelFrame"}:
            return self.theme["panel_subsection"] if cls == "Frame" else parent_bg
        if parent_bg == self.theme["panel_subsection"]:
            return self.theme["panel_subsection"]
        if parent_bg == self.theme["panel_section"]:
            return self.theme["panel_subsection"]
        if parent_bg == self.theme["bg"]:
            return self.theme["bg"]
        return self.theme["panel"]

    def _button_role(self, widget):
        try:
            text = widget.cget("text")
        except Exception:
            return "neutral"
        if text == "Run Timelapse":
            return "orange"
        if text in {"Start Single Acquisition", "Run One Loop", "Export", "Set"}:
            return "blue"
        return "neutral"

    def _label_role_color(self, widget):
        try:
            current_fg = str(widget.cget("fg")).lower()
        except Exception:
            return self.theme["text"]
        muted_colors = {
            "#9aa6b2",
            "#5c6b79",
            "#94a3b8",
            "#667085",
            "#728091",
            self.theme.get("muted", "").lower(),
        }
        success_colors = {
            "#7ad97a",
            "#247a3d",
            "#65d28b",
            "#25834f",
            self.theme.get("success", "").lower(),
        }
        accent_colors = {
            "#ffb37a",
            "#a9571d",
            "#8bb8ff",
            "#3f7fe8",
            self.theme.get("accent_soft", "").lower(),
        }
        title_colors = {
            "#f3f6fb",
            "#101820",
            "#f8fafc",
            "#111827",
            self.theme.get("title", "").lower(),
        }
        if current_fg in muted_colors:
            return self.theme["muted"]
        if current_fg in success_colors:
            return self.theme["success"]
        if current_fg in accent_colors:
            return self.theme["accent_soft"]
        if current_fg in title_colors:
            return self.theme["title"]
        return self.theme["text"]

    def _button_colors(self, widget):
        role = self._button_role(widget)
        if role == "orange":
            return (
                self.theme["accent_orange"],
                self.theme["orange_text"],
                self.theme["accent_orange_active"],
                self.theme["orange_text"],
            )
        if role == "blue":
            return (
                self.theme["accent"],
                self.theme["accent_text"],
                self.theme["accent_active"],
                self.theme["accent_text"],
            )
        return (
            self.theme["button_bg"],
            self.theme["button_text"],
            self.theme["button_active"],
            self.theme["button_text"],
        )

    def _apply_theme_recursive(self, widget):
        cls = widget.winfo_class()
        try:
            if cls in {"Frame", "Toplevel"}:
                bg = self._container_bg_for_widget(widget)
                widget.configure(bg=bg, highlightbackground=self.theme["border"], highlightcolor=self.theme["border"])
            elif cls in {"Labelframe", "LabelFrame"}:
                bg = self._label_frame_bg(widget)
                widget.configure(
                    bg=bg,
                    fg=self.theme["section_text"],
                    relief="flat",
                    bd=1,
                    highlightthickness=1,
                    highlightbackground=self.theme["border"],
                    highlightcolor=self.theme["border"],
                )
            elif cls == "Panedwindow":
                widget.configure(bg=self.theme["bg"], sashrelief="flat")
            elif cls == "Canvas":
                view_border = self.theme.get("view_border", self.theme["border"])
                widget.configure(bg=self.theme["canvas"], highlightbackground=view_border, highlightcolor=view_border)
            elif cls == "Label":
                widget.configure(bg=self._container_bg_for_widget(widget), fg=self._label_role_color(widget))
            elif cls == "Button":
                bg, fg, active_bg, active_fg = self._button_colors(widget)
                control_bar_button = bool(getattr(widget, "_hera_control_bar_button", False))
                widget.configure(
                    bg=bg,
                    fg=fg,
                    activebackground=active_bg,
                    activeforeground=active_fg,
                    relief="flat",
                    bd=1,
                    highlightthickness=1,
                    highlightbackground=self.theme["border"],
                    highlightcolor=self.theme["accent"],
                    padx=4 if control_bar_button else 6,
                    pady=1 if control_bar_button else 2,
                    cursor="hand2",
                    disabledforeground=self.theme["muted"],
                )
            elif cls == "Entry":
                widget.configure(bg=self.theme["field"], fg=self.theme["text"], insertbackground=self.theme["accent_soft"], relief="flat", bd=1, highlightthickness=1, highlightbackground=self.theme["border"], highlightcolor=self.theme["accent"])
            elif cls == "Text":
                widget.configure(bg=self.theme["field"], fg=self.theme["text"], insertbackground=self.theme["accent_soft"], relief="flat", bd=1, highlightthickness=1, highlightbackground=self.theme["border"])
            elif cls == "Checkbutton":
                bg = self._container_bg_for_widget(widget)
                widget.configure(bg=bg, fg=self.theme["text"], selectcolor=self.theme["field"], activebackground=bg, activeforeground=self.theme["text"], highlightthickness=0)
            elif cls == "Scale":
                widget.configure(bg=self._container_bg_for_widget(widget), fg=self.theme["text"], troughcolor=self.theme["field"], activebackground=self.theme["accent"], highlightthickness=0)
            elif cls == "Menubutton":
                widget.configure(
                    bg=self.theme["button_bg"],
                    fg=self.theme["button_text"],
                    activebackground=self.theme["button_active"],
                    activeforeground=self.theme["button_text"],
                    relief="flat",
                    bd=1,
                    highlightthickness=1,
                    highlightbackground=self.theme["border"],
                    highlightcolor=self.theme["accent"],
                )
                try:
                    widget["menu"].configure(bg=self.theme["panel_alt"], fg=self.theme["text"], activebackground=self.theme["button_active"], activeforeground=self.theme["button_text"])
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
