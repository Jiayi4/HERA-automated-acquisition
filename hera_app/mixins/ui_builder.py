import os
import tkinter as tk
from tkinter import filedialog, ttk


class UIBuilderMixin:
    def _build_ui(self):
        shell = tk.Frame(self, bg=self.theme["bg"])
        shell.pack(fill="both", expand=True, padx=14, pady=14)

        toolbar = tk.Frame(shell, bg=self.theme["bg"])
        toolbar.pack(fill="x", pady=(0, 8))
        title = tk.Label(toolbar, text="HERA + Tango Trigger", font=("Segoe UI Semibold", 16), bg=self.theme["bg"], fg=self.theme["title"])
        title.pack(side="left")
        subtitle = tk.Label(toolbar, text="Stage-guided hyperspectral acquisition", font=("Segoe UI", 10), bg=self.theme["bg"], fg=self.theme["muted"])
        subtitle.pack(side="left", padx=(12, 0), pady=(4, 0))
        tk.Button(toolbar, textvariable=self.theme_button_var, command=self.toggle_theme_mode).pack(side="right")

        body = tk.PanedWindow(shell, orient="horizontal", sashwidth=8, sashrelief="flat", bg=self.theme["bg"], bd=0)
        body.pack(fill="both", expand=True)

        left = self._make_scroll_column(body, width=300)
        body.add(left, minsize=240, width=300, stretch="never")

        center = tk.Frame(body, bg=self.theme["bg"], padx=10)
        center.grid_rowconfigure(1, weight=1)
        center.grid_columnconfigure(0, weight=1)
        body.add(center, minsize=560, stretch="always")

        right = self._make_scroll_column(body, width=285)
        body.add(right, minsize=230, width=285, stretch="never")

        self._build_left_controls(left.content)
        self._build_center_workspace(center)
        self._build_right_controls(right.content)

    def _make_scroll_column(self, parent, width):
        outer = tk.Frame(parent, bg=self.theme["bg"])
        scroll = ttk.Scrollbar(outer, orient="vertical")
        scroll.pack(side="right", fill="y")
        canvas = tk.Canvas(outer, bg=self.theme["bg"], highlightthickness=0, width=width, yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.config(command=canvas.yview)
        content = tk.Frame(canvas, bg=self.theme["bg"])
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(window_id, width=e.width))

        def bind_wheel(_event):
            canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        canvas.bind("<Enter>", bind_wheel)
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        outer.content = content
        return outer

    def _param_entry(self, parent, row, label_text, key, default, width=10):
        tk.Label(parent, text=label_text).grid(row=row, column=0, sticky="w", pady=2)
        if isinstance(default, int):
            self.param_vars[key] = tk.IntVar(value=default)
        else:
            self.param_vars[key] = tk.DoubleVar(value=default)
        tk.Entry(parent, textvariable=self.param_vars[key], width=width).grid(row=row, column=1, sticky="ew", padx=(6, 0), pady=2)

    def _param_menu(self, parent, row, label_text, key, default, options):
        tk.Label(parent, text=label_text).grid(row=row, column=0, sticky="w", pady=2)
        self.param_vars[key] = tk.StringVar(value=default)
        tk.OptionMenu(parent, self.param_vars[key], *list(options)).grid(row=row, column=1, sticky="ew", padx=(6, 0), pady=2)

    def _build_left_controls(self, parent):
        self.param_vars = {}
        self.stage_speed_var = tk.DoubleVar(value=20.0)
        self.stage_dwell_var = tk.DoubleVar(value=0.0)
        self.live_pixel_size_var = tk.DoubleVar(value=1.0)
        self.live_invert_x_var = tk.BooleanVar(value=False)
        self.live_invert_y_var = tk.BooleanVar(value=False)
        self.live_swap_xy_var = tk.BooleanVar(value=False)
        self.position_name_var = tk.StringVar()
        self.selected_name_var = tk.StringVar()
        self.selected_x_var = tk.StringVar()
        self.selected_y_var = tk.StringVar()
        self.selected_z_var = tk.StringVar()
        self.roi_tl_x_var = tk.IntVar(value=0)
        self.roi_tl_y_var = tk.IntVar(value=0)
        self.roi_tr_x_var = tk.IntVar(value=511)
        self.roi_tr_y_var = tk.IntVar(value=0)
        self.roi_br_x_var = tk.IntVar(value=511)
        self.roi_br_y_var = tk.IntVar(value=511)
        self.roi_bl_x_var = tk.IntVar(value=0)
        self.roi_bl_y_var = tk.IntVar(value=511)
        self.roi_area_var = tk.StringVar(value=str(512 * 512))

        nb = ttk.Notebook(parent, style="Left.TNotebook")
        nb.pack(fill="both", expand=True)
        camera_tab = tk.Frame(nb, padx=4, pady=4)
        stage_tab = tk.Frame(nb, padx=4, pady=4)
        nb.add(camera_tab, text="  Camera  ")
        nb.add(stage_tab, text="  Stage  ")

        status = tk.LabelFrame(camera_tab, text="Status", padx=8, pady=8)
        status.pack(fill="x", pady=(0, 10))
        for text, var in (
            ("License", self.license_var),
            ("Live", self.live_view_status_var),
            ("HDR", self.hdr_status_var),
            ("NIS Z", self.nis_z_status_var),
            ("Site", self.current_site_var),
            ("Cycle", self.current_cycle_var),
            ("Last export", self.last_export_var),
        ):
            row = tk.Frame(status)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"{text}:", fg=self.theme["muted"], width=10, anchor="w").pack(side="left")
            tk.Label(row, textvariable=var, anchor="w", wraplength=210, justify="left").pack(side="left", fill="x", expand=True)
        cursor_row = tk.Frame(status)
        cursor_row.pack(fill="x", pady=1)
        tk.Label(cursor_row, text="Cursor:", fg=self.theme["muted"], width=10, anchor="w").pack(side="left")
        tk.Label(
            cursor_row,
            textvariable=self.live_cursor_var,
            anchor="w",
            width=48,
            justify="left",
            font=("Consolas", 9),
        ).pack(side="left", fill="x", expand=True)
        state_row = tk.Frame(status)
        state_row.pack(fill="x", pady=(4, 0))
        self.app_state_var = tk.StringVar(value=self.app_state)
        tk.Label(state_row, text="State:", fg=self.theme["muted"], width=10, anchor="w").pack(side="left")
        self.app_state_label = tk.Label(state_row, textvariable=self.app_state_var, fg="#7ad97a", font=("Segoe UI Semibold", 10))
        self.app_state_label.pack(side="left", fill="x", expand=True)
        btns = tk.Frame(status)
        btns.pack(fill="x", pady=(8, 0))
        tk.Button(btns, text="Preflight", command=self.preflight_check).pack(side="left", padx=(0, 6))
        tk.Button(btns, text="Live Status", command=self.debug_live_status).pack(side="left", padx=(0, 6))
        tk.Button(btns, text="Restart Live", command=self.restart_live_view).pack(side="left")

        exposure = tk.LabelFrame(camera_tab, text="Exposure", padx=8, pady=8)
        exposure.pack(fill="x", pady=(0, 10))
        exposure.grid_columnconfigure(1, weight=1)
        self._param_entry(exposure, 0, "Gain [dB]:", "gain", 0.0)
        self._param_entry(exposure, 1, "Exposure [ms]:", "exposure", 1.0)
        tk.Checkbutton(exposure, text="HDR", variable=self.hdr_enabled_var).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        tk.Button(exposure, text="Apply", command=self.apply_parameters_async).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        roi = tk.LabelFrame(camera_tab, text="ROI", padx=8, pady=8)
        roi.pack(fill="x", pady=(0, 10))
        roi.grid_columnconfigure(1, weight=1)
        for _k, _v in [("roi_x", 0), ("roi_y", 0), ("roi_w", 512), ("roi_h", 512)]:
            self.param_vars[_k] = tk.IntVar(value=_v)
        corners = tk.LabelFrame(roi, text="Corners", padx=6, pady=6)
        corners.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 0))
        corner_rows = [
            ("Top Left", self.roi_tl_x_var, self.roi_tl_y_var),
            ("Top Right", self.roi_tr_x_var, self.roi_tr_y_var),
            ("Bottom Right", self.roi_br_x_var, self.roi_br_y_var),
            ("Bottom Left", self.roi_bl_x_var, self.roi_bl_y_var),
        ]
        for corner_row, (label, x_var, y_var) in enumerate(corner_rows):
            tk.Label(corners, text=label).grid(row=corner_row, column=0, sticky="w", pady=1)
            tk.Label(corners, text="X").grid(row=corner_row, column=1, sticky="e", padx=(6, 2))
            tk.Entry(corners, textvariable=x_var, width=7).grid(row=corner_row, column=2, sticky="w")
            tk.Label(corners, text="Y").grid(row=corner_row, column=3, sticky="e", padx=(6, 2))
            tk.Entry(corners, textvariable=y_var, width=7).grid(row=corner_row, column=4, sticky="w")
        tk.Button(corners, text="Apply", command=self.apply_roi_from_corners).grid(row=4, column=0, columnspan=5, sticky="ew", pady=(6, 0))
        area_row = tk.Frame(roi)
        area_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        tk.Label(area_row, text="Area (px2)").pack(side="left")
        tk.Entry(area_row, textvariable=self.roi_area_var, width=9).pack(side="left", padx=(6, 4))
        tk.Button(area_row, text="Apply", command=self.apply_roi_from_area).pack(side="left")
        roi_actions = tk.Frame(roi)
        roi_actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        tk.Button(roi_actions, text="Size", command=self.apply_roi_from_size).pack(side="left", padx=(0, 4))
        tk.Button(roi_actions, textvariable=self.live_roi_button_var, command=self.toggle_live_roi_selection).pack(side="left", padx=(0, 4))
        tk.Button(roi_actions, text="Clear", command=self.clear_live_roi_selection).pack(side="left")
        tk.Label(roi, textvariable=self.live_roi_status_var, fg=self.theme["muted"], wraplength=250, justify="left").grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        xyz = tk.LabelFrame(stage_tab, text="XYZ Position", padx=8, pady=8)
        xyz.pack(fill="x", pady=(0, 10))
        xyz.grid_columnconfigure(0, weight=1)
        self.stage_status_var = tk.StringVar(value="Stage: not connected")
        self.stage_version_var = tk.StringVar(value="Controller: -")
        self.stage_position_var = tk.StringVar(value="X: -, Y: -")
        tk.Label(xyz, textvariable=self.stage_status_var, font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        pos_panel = tk.Frame(xyz)
        pos_panel.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.current_x_label = tk.Label(pos_panel, text="X: -")
        self.current_x_label.pack(anchor="w")
        self.current_y_label = tk.Label(pos_panel, text="Y: -")
        self.current_y_label.pack(anchor="w", pady=(4, 0))
        self.current_z_label = tk.Label(pos_panel, textvariable=self.nis_z_current_z_var)
        self.current_z_label.pack(anchor="w", pady=(4, 0))

        map_panel = tk.Frame(xyz)
        map_panel.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        pixel_row = tk.Frame(map_panel)
        pixel_row.pack(fill="x")
        tk.Label(pixel_row, text="Stage units / pixel").pack(side="left")
        tk.Entry(pixel_row, textvariable=self.live_pixel_size_var, width=8).pack(side="left", padx=(6, 0))
        axis_row = tk.Frame(map_panel)
        axis_row.pack(fill="x", pady=(6, 0))
        tk.Checkbutton(axis_row, text="Invert X", variable=self.live_invert_x_var, command=self._update_live_cursor_readout).pack(side="left")
        tk.Checkbutton(axis_row, text="Invert Y", variable=self.live_invert_y_var, command=self._update_live_cursor_readout).pack(side="left", padx=(6, 0))
        tk.Checkbutton(axis_row, text="Swap XY", variable=self.live_swap_xy_var, command=self._update_live_cursor_readout).pack(side="left", padx=(6, 0))

        position_panel = tk.Frame(xyz)
        position_panel.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        tk.Label(position_panel, text="Position name").pack(anchor="w")
        tk.Entry(position_panel, textvariable=self.position_name_var, width=24).pack(fill="x", pady=(2, 6))
        for text, command in (
            ("Add Current Position", self.add_current_position),
            ("Update Selected Position", self.update_selected_position),
            ("Delete Selected Row", self.delete_selected_position),
            ("Reconnect Stage", self.reconnect_stage),
        ):
            tk.Button(position_panel, text=text, command=command).pack(fill="x", pady=2)

        edit_panel = tk.LabelFrame(stage_tab, text="Selected XYZ Site", padx=8, pady=8)
        edit_panel.pack(fill="x", pady=(0, 10))
        tk.Entry(edit_panel, textvariable=self.selected_name_var, width=24).pack(fill="x", pady=(0, 6))
        tk.Button(edit_panel, text="Rename", command=self.rename_selected_position).pack(fill="x", pady=(0, 6))
        coord_row = tk.Frame(edit_panel)
        coord_row.pack(fill="x")
        for label, var in (("X", self.selected_x_var), ("Y", self.selected_y_var), ("Z", self.selected_z_var)):
            tk.Label(coord_row, text=label).pack(side="left")
            tk.Entry(coord_row, textvariable=var, width=8).pack(side="left", padx=(3, 6))
        tk.Button(edit_panel, text="Use Current XYZ", command=self.capture_current_stage_position_into_selected).pack(fill="x", pady=(8, 2))
        tk.Button(edit_panel, text="Save Selected Edits", command=self.apply_selected_position_edits).pack(fill="x", pady=2)
        tk.Button(edit_panel, text="Go To Selected Position", command=self.goto_selected_position).pack(fill="x", pady=2)

        saved = tk.LabelFrame(stage_tab, text="Saved Positions", padx=8, pady=8)
        saved.pack(fill="both", expand=True, pady=(0, 10))
        tree_wrap = tk.Frame(saved)
        tree_wrap.pack(fill="both", expand=True)
        self.positions_tree = ttk.Treeview(tree_wrap, columns=("name", "x", "y", "z"), show="headings", height=8, style="Dark.Treeview")
        for name, label, width, anchor in (
            ("name", "Name", 105, "w"),
            ("x", "X", 58, "e"),
            ("y", "Y", 58, "e"),
            ("z", "Z", 58, "e"),
        ):
            self.positions_tree.heading(name, text=label)
            self.positions_tree.column(name, width=width, anchor=anchor)
        scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.positions_tree.yview)
        self.positions_tree.configure(yscrollcommand=scroll.set)
        self.positions_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.positions_tree.bind("<<TreeviewSelect>>", self.on_position_selected)

        self._build_nis_z_ui(stage_tab)

    def _build_center_workspace(self, parent):
        spectral = tk.LabelFrame(parent, text="Control Bar", padx=8, pady=8)
        spectral.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for col in range(6):
            spectral.grid_columnconfigure(col, weight=1)
        self.param_vars["scan_mode"] = tk.StringVar(value="Medium")
        self.param_vars["trigger_mode"] = tk.StringVar(value="Internal")
        self.param_vars["averages"] = tk.IntVar(value=1)
        self.param_vars["stabilization"] = tk.IntVar(value=0)
        self.param_vars["bands"] = tk.IntVar(value=0)
        self.param_vars["binning"] = tk.StringVar(value="None")
        self.param_vars["data_type"] = tk.StringVar(value="SinglePrecision")
        controls = [
            ("Spectral Resolution", "scan_mode", "menu", self.SCAN_MODES.keys(), 8),
            ("Bands", "bands", "entry", None, 5),
            ("Averages", "averages", "menu", ("1", "2", "3"), 3),
            ("Binning", "binning", "menu", self.BINNING_OPTIONS.keys(), 7),
            ("Step Wait [ms]", "stabilization", "entry", None, 6),
            ("Data", "data_type", "menu", self.DATA_TYPES.keys(), 13),
        ]
        for index, (label, key, kind, options, width) in enumerate(controls):
            control_row = (index // 3) * 2
            col = (index % 3) * 2
            tk.Label(spectral, text=label).grid(row=control_row, column=col, columnspan=2, sticky="w", padx=(0, 4), pady=(2, 0))
            if kind == "menu":
                menu = tk.OptionMenu(spectral, self.param_vars[key], *list(options))
                menu.config(width=width)
                menu.grid(row=control_row + 1, column=col, columnspan=2, sticky="ew", padx=(0, 14), pady=(0, 4))
            else:
                tk.Entry(spectral, textvariable=self.param_vars[key], width=width).grid(row=control_row + 1, column=col, columnspan=2, sticky="ew", padx=(0, 14), pady=(0, 4))
        tk.Button(spectral, text="Apply", command=self.apply_parameters_async).grid(row=3, column=4, columnspan=2, sticky="ew", padx=(0, 14), pady=(0, 4))

        self._build_views_and_log(parent)

    def _build_views_and_log(self, parent):
        views_frame = tk.LabelFrame(parent, text="Live View / Hyperspectral View", padx=8, pady=8)
        views_frame.grid(row=1, column=0, sticky="nsew")
        views_frame.grid_rowconfigure(0, weight=1)
        views_frame.grid_columnconfigure(0, weight=1)
        notebook = ttk.Notebook(views_frame)
        notebook.grid(row=0, column=0, sticky="nsew")

        live_tab = tk.Frame(notebook, bg=self.theme["panel"])
        hyper_tab = tk.Frame(notebook, bg=self.theme["panel"])
        notebook.add(live_tab, text="Live View")
        notebook.add(hyper_tab, text="Hyperspectral View")

        live_controls = tk.Frame(live_tab, bg=self.theme["panel"])
        live_controls.pack(fill="x", padx=8, pady=(8, 4))
        live_display_bar = tk.Frame(live_controls, bg=self.theme["panel"])
        live_display_bar.pack(fill="x")
        tk.Checkbutton(live_display_bar, text="Autocontrast", variable=self.live_autocontrast_var,
                       command=lambda: self._schedule_live_render(force=True),
                       bg=self.theme["panel"], fg=self.theme["text"], selectcolor=self.theme["field"],
                       activebackground=self.theme["panel"]).pack(side="left", padx=(12, 0))
        tk.Checkbutton(live_display_bar, text="Show Saturation", variable=self.live_show_saturation_var,
                       command=lambda: self._schedule_live_render(force=True),
                       bg=self.theme["panel"], fg=self.theme["text"], selectcolor=self.theme["field"],
                       activebackground=self.theme["panel"]).pack(side="left", padx=(8, 0))
        tk.Checkbutton(live_display_bar, text="Cross", variable=self.live_cross_enabled_var,
                       command=self.toggle_live_cross,
                       bg=self.theme["panel"], fg=self.theme["text"], selectcolor=self.theme["field"],
                       activebackground=self.theme["panel"]).pack(side="left", padx=(8, 0))
        tk.Label(live_display_bar, textvariable=self.live_profile_status_var, fg="#9aa6b2", bg=self.theme["panel"]).pack(side="left", padx=(10, 4))
        tk.Label(live_display_bar, textvariable=self.live_gamma_label_var, fg="#9aa6b2", bg=self.theme["panel"]).pack(side="left", padx=(10, 4))
        tk.Scale(live_display_bar, variable=self.live_gamma_var, from_=0.2, to=3.0, resolution=0.1,
                 orient="horizontal", length=110, showvalue=False, command=self.on_live_gamma_change,
                 bg=self.theme["panel"], fg=self.theme["text"], troughcolor=self.theme["field"],
                 highlightthickness=0).pack(side="left")
        tk.Button(live_display_bar, text="Reset Gamma", command=self.reset_live_gamma).pack(side="left", padx=(6, 0))
        tk.Button(live_display_bar, text="Snapshot", command=self.snapshot_live_view).pack(side="left", padx=(8, 0))
        tk.Label(live_display_bar, textvariable=self.live_zoom_label_var, fg="#9aa6b2", bg=self.theme["panel"]).pack(side="left", padx=(12, 4))
        tk.Button(live_display_bar, text="-", width=3, command=lambda: self.zoom_live_view(1 / 1.25)).pack(side="left")
        tk.Button(live_display_bar, text="Fit to view", command=self.fit_live_view).pack(side="left", padx=(6, 0))
        tk.Button(live_display_bar, text="+", width=3, command=lambda: self.zoom_live_view(1.25)).pack(side="left", padx=(6, 0))
        live_profile_grid = tk.Frame(live_tab, bg=self.theme["panel"])
        live_profile_grid.pack(fill="both", expand=True)
        live_profile_grid.grid_rowconfigure(0, weight=1)
        live_profile_grid.grid_columnconfigure(0, weight=1)
        self.live_view_canvas = tk.Canvas(live_profile_grid, bg=self.theme["canvas"], highlightthickness=0)
        self.live_view_canvas.bind("<Motion>", self.on_live_mouse_move)
        self.live_view_canvas.bind("<Button-1>", self.on_live_mouse_click)
        self.live_view_canvas.bind("<MouseWheel>", self.on_live_mousewheel)
        self.live_view_canvas.bind("<Button-4>", lambda event: self.zoom_live_view(1.25, event))
        self.live_view_canvas.bind("<Button-5>", lambda event: self.zoom_live_view(1 / 1.25, event))
        self.live_view_canvas.bind("<ButtonPress-3>", self.start_live_pan)
        self.live_view_canvas.bind("<B3-Motion>", self.on_live_pan_drag)
        self.live_view_canvas.bind("<ButtonRelease-3>", self.end_live_pan)
        self.live_view_canvas.bind("<Leave>", self.on_live_mouse_leave)
        self.live_view_canvas.grid(row=0, column=0, sticky="nsew")
        self.live_vertical_profile_canvas = tk.Canvas(live_profile_grid, bg=self.theme["canvas"], highlightthickness=0, width=120)
        self.live_vertical_profile_canvas.grid(row=0, column=1, sticky="ns", padx=(6, 0))
        self.live_horizontal_profile_canvas = tk.Canvas(live_profile_grid, bg=self.theme["canvas"], highlightthickness=0, height=105)
        self.live_horizontal_profile_canvas.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        hyper_controls = tk.Frame(hyper_tab, bg=self.theme["panel"])
        hyper_controls.pack(fill="x", padx=8, pady=(8, 4))
        tk.Button(hyper_controls, text="Prev Band", command=lambda: self.step_hyper_band(-1)).pack(side="left", padx=(0, 8))
        tk.Label(hyper_controls, textvariable=self.current_hyper_band_var, fg="#e7edf5").pack(side="left")
        ttk.Separator(hyper_controls, orient="vertical", style="Dark.TSeparator").pack(side="left", fill="y", padx=12)
        tk.Label(hyper_controls, textvariable=self.current_hyper_wavelength_var, fg="#9aa6b2").pack(side="left")
        jump_wrap = tk.Frame(hyper_controls, bg=self.theme["panel"])
        jump_wrap.pack(side="right", padx=(8, 0))
        tk.Button(jump_wrap, text="Go", command=self.jump_to_hyper_band).pack(side="right")
        tk.Entry(jump_wrap, textvariable=self.hyper_band_jump_var, width=6).pack(side="right", padx=(0, 6))
        tk.Label(jump_wrap, text="Band", fg="#9aa6b2").pack(side="right", padx=(0, 6))
        tk.Button(hyper_controls, text="Next Band", command=lambda: self.step_hyper_band(1)).pack(side="right")
        self.hyper_band_scale = tk.Scale(
            hyper_tab, from_=0, to=0, orient="horizontal", variable=self.current_hyper_band_index,
            command=self.on_hyper_band_changed, showvalue=False, highlightthickness=0, bd=0,
            bg=self.theme["panel"], fg=self.theme["text"], troughcolor=self.theme["panel_alt"],
            activebackground=self.theme["accent"], sliderlength=28, width=18, repeatdelay=150,
            repeatinterval=80, takefocus=1, cursor="hand2",
        )
        self.hyper_band_scale.pack(fill="x", padx=8, pady=(0, 6))
        self.hyper_view_canvas = tk.Canvas(hyper_tab, bg=self.theme["canvas"], highlightthickness=0)
        self.hyper_view_canvas.pack(fill="both", expand=True, pady=(0, 6))
        self.hyper_spectrum_canvas = tk.Canvas(hyper_tab, bg=self.theme["canvas"], highlightthickness=0, height=150)
        self.hyper_spectrum_canvas.pack(fill="x", padx=8, pady=(0, 8))
        self.live_view_canvas.bind("<Configure>", lambda _e: self._draw_live_view_placeholder())
        self.live_vertical_profile_canvas.bind("<Configure>", lambda _e: self._render_live_profiles())
        self.live_horizontal_profile_canvas.bind("<Configure>", lambda _e: self._render_live_profiles())
        self.hyper_view_canvas.bind("<Configure>", lambda _e: self.render_current_hyper_band())
        self.hyper_view_canvas.bind("<Button-1>", self.on_hyper_mouse_click)
        self.hyper_spectrum_canvas.bind("<Configure>", lambda _e: self._draw_hyper_spectrum_panel())
        for widget in (hyper_tab, self.hyper_band_scale, self.hyper_view_canvas, self.hyper_spectrum_canvas):
            widget.bind("<Left>", lambda _e: self.step_hyper_band(-1))
            widget.bind("<Right>", lambda _e: self.step_hyper_band(1))
            widget.bind("<MouseWheel>", self.on_hyper_mousewheel)
            widget.bind("<Button-4>", lambda _e: self.step_hyper_band(1))
            widget.bind("<Button-5>", lambda _e: self.step_hyper_band(-1))
            widget.bind("<Button-1>", lambda _e, target=widget: target.focus_set(), add="+")

        status_frame = tk.LabelFrame(parent, text="Status / Messages", padx=8, pady=8)
        status_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        status_strip = tk.Frame(status_frame)
        status_strip.pack(fill="x", pady=(0, 6))
        tk.Label(status_strip, textvariable=self.timelapse_status_var, font=("Segoe UI Semibold", 10)).pack(side="left")
        ttk.Separator(status_strip, orient="vertical", style="Dark.TSeparator").pack(side="left", fill="y", padx=12)
        tk.Label(status_strip, textvariable=self.time_remaining_var, fg="#9aa6b2").pack(side="left")
        ttk.Separator(status_strip, orient="vertical", style="Dark.TSeparator").pack(side="left", fill="y", padx=12)
        tk.Label(status_strip, textvariable=self.live_view_status_var, fg="#9aa6b2").pack(side="left")
        self.log_text = tk.Text(status_frame, height=7, state="disabled", wrap="word", bg=self.theme["field"], fg=self.theme["text"], insertbackground=self.theme["accent_soft"], relief="flat")
        self.log_text.pack(fill="x", expand=False)

    def _build_right_controls(self, parent):
        acquisition = tk.LabelFrame(parent, text="Acquisition / Timelapse", padx=8, pady=8)
        acquisition.pack(fill="x", pady=(0, 10))
        tk.Button(acquisition, text="Run Selected Site", command=self.manual_trigger_selected_position).pack(fill="x", pady=3)
        tk.Button(acquisition, text="Start Acquisition", command=self.start_acquisition).pack(fill="x", pady=3)
        tk.Button(acquisition, text="Abort Hera Acquisition", command=self.abort_acquisition).pack(fill="x", pady=3)
        ttk.Separator(acquisition, orient="horizontal", style="Dark.TSeparator").pack(fill="x", pady=8)

        self.interval_var = tk.DoubleVar(value=10.0)
        self.stop_after_var = tk.DoubleVar(value=0.0)
        for label, var in (
            ("Trigger", self.param_vars["trigger_mode"]),
            ("Interval (min)", self.interval_var),
            ("Dwell (s)", self.stage_dwell_var),
            ("Stop after (min)", self.stop_after_var),
            ("Speed XY", self.stage_speed_var),
        ):
            row = tk.Frame(acquisition)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, width=15, anchor="w").pack(side="left")
            if label == "Trigger":
                menu = tk.OptionMenu(row, var, *list(self.TRIGGER_MODES.keys()))
                menu.config(width=10)
                menu.pack(side="left")
            else:
                tk.Entry(row, textvariable=var, width=9).pack(side="left")
        tk.Label(acquisition, textvariable=self.timelapse_status_var, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(8, 0))
        tk.Label(acquisition, textvariable=self.time_remaining_var).pack(anchor="w", pady=(2, 8))
        tk.Button(acquisition, text="Start Timelapse", command=self.start_timelapse, bg="#ff8b3d", fg="#111111", activebackground="#ffb37a").pack(fill="x", pady=3)
        self.pause_button = tk.Button(acquisition, text="Pause", command=self.pause_or_resume_timelapse)
        self.pause_button.pack(fill="x", pady=3)
        tk.Button(acquisition, text="Stop Timelapse", command=self.stop_timelapse).pack(fill="x", pady=3)
        tk.Button(acquisition, text="Run One Cycle", command=self.run_one_cycle).pack(fill="x", pady=3)

        flatfield = tk.LabelFrame(parent, text="Flatfield", padx=8, pady=8)
        flatfield.pack(fill="x", pady=(0, 10))
        tk.Label(flatfield, textvariable=self.flatfield_status_var, anchor="w", justify="left", wraplength=240).pack(fill="x", pady=(0, 6))
        tk.Button(flatfield, text="Acquire Baseline", command=self.start_flatfield_acquisition).pack(fill="x", pady=2)
        tk.Checkbutton(flatfield, text="Use flatfield correction", variable=self.use_flatfield_var).pack(anchor="w", pady=(4, 2))
        tk.Checkbutton(flatfield, text="Acquire flatfield at timelapse start", variable=self.flatfield_at_timelapse_start_var).pack(anchor="w", pady=(2, 2))
        tk.Button(flatfield, text="Clear Flatfield", command=self.clear_flatfield).pack(fill="x", pady=2)

        saving = tk.LabelFrame(parent, text="Export", padx=8, pady=8)
        saving.pack(fill="x", pady=(0, 10))
        self.param_vars["output_path"] = tk.StringVar(value=os.path.join(os.path.abspath(os.path.dirname(__file__)), "output"))
        tk.Label(saving, text="Saving Folder").pack(anchor="w")
        tk.Entry(saving, textvariable=self.param_vars["output_path"], width=30).pack(fill="x", pady=(2, 6))
        tk.Button(saving, text="Browse", command=self.browse_output_path).pack(fill="x", pady=(0, 6))
        tk.Label(saving, text="Notes").pack(anchor="w", pady=(4, 0))
        tk.Entry(saving, textvariable=self.saving_notes_var, width=30).pack(fill="x", pady=(2, 0))
        self.save_pending_button = tk.Button(saving, text="Export", command=self.save_pending_acquisition, state="disabled")
        self.save_pending_button.pack(fill="x", pady=(6, 0))
        ttk.Separator(saving, orient="horizontal").pack(fill="x", pady=8)
        tk.Label(saving, text="HyperLAB").pack(anchor="w")
        tk.Entry(saving, textvariable=self.hyperlab_shortcut_var, width=30).pack(fill="x", pady=(2, 6))
        hyperlab_buttons = tk.Frame(saving)
        hyperlab_buttons.pack(fill="x")
        tk.Button(hyperlab_buttons, text="Browse", command=self.browse_hyperlab_shortcut).pack(side="left", fill="x", expand=True, padx=(0, 4))
        tk.Button(hyperlab_buttons, text="Open in HyperLAB", command=self.open_current_in_hyperlab).pack(side="left", fill="x", expand=True, padx=(4, 0))

    def _build_hera_ui(self, parent):
        frame = tk.LabelFrame(parent, text="Hera Acquisition", padx=8, pady=8)
        frame.pack(fill="x", pady=(0, 10))

        top = tk.Frame(frame)
        top.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        tk.Label(top, text="Connection and discovery are automatic.", fg="#9aa6b2").pack(side="left")
        tk.Label(top, textvariable=self.license_var, fg="#7ad97a").pack(side="right")

        buttons = tk.Frame(frame)
        buttons.grid(row=1, column=0, columnspan=3, sticky="w", pady=8)
        tk.Button(buttons, text="Preflight", command=self.preflight_check).pack(side="left", padx=6)
        tk.Button(buttons, text="Live Status", command=self.debug_live_status).pack(side="left", padx=6)
        tk.Button(buttons, text="Restart Live", command=self.restart_live_view).pack(side="left", padx=6)

        params = tk.LabelFrame(frame, text="Acquisition Parameters", padx=8, pady=8)
        params.grid(row=2, column=0, columnspan=3, sticky="ew")

        param_labels = [
            ("Gain [dB]:", "gain", 0.0),
            ("Exposure [ms]:", "exposure", 1.0),
            ("Spectral Resolution:", "scan_mode", "Medium"),
            ("Trigger mode:", "trigger_mode", "Internal"),
            ("Averages:", "averages", 1),
            ("Step Wait [ms]:", "stabilization", 0),
            ("Bands (0=default):", "bands", 0),
            ("Binning:", "binning", "None"),
            ("Output path:", "output_path", os.path.join(os.path.abspath(os.path.dirname(__file__)), "output")),
            ("Data type:", "data_type", "SinglePrecision"),
        ]

        self.param_vars = {}
        row = 0
        for label_text, key, default in param_labels:
            tk.Label(params, text=label_text).grid(row=row, column=0, sticky="w", pady=2)
            if key == "scan_mode":
                self.param_vars[key] = tk.StringVar(value=default)
                tk.OptionMenu(params, self.param_vars[key], *list(self.SCAN_MODES.keys())).grid(row=row, column=1, sticky="w")
            elif key == "trigger_mode":
                self.param_vars[key] = tk.StringVar(value=default)
                tk.OptionMenu(params, self.param_vars[key], *list(self.TRIGGER_MODES.keys())).grid(row=row, column=1, sticky="w")
            elif key == "binning":
                self.param_vars[key] = tk.StringVar(value=default)
                tk.OptionMenu(params, self.param_vars[key], *list(self.BINNING_OPTIONS.keys())).grid(row=row, column=1, sticky="w")
            elif key == "data_type":
                self.param_vars[key] = tk.StringVar(value=default)
                tk.OptionMenu(params, self.param_vars[key], *list(self.DATA_TYPES.keys())).grid(row=row, column=1, sticky="w")
            elif key == "output_path":
                self.param_vars[key] = tk.StringVar(value=default)
                tk.Entry(params, textvariable=self.param_vars[key], width=32).grid(row=row, column=1, sticky="w")
                tk.Button(params, text="Browse", command=self.browse_output_path).grid(row=row, column=2, padx=4)
            elif isinstance(default, int):
                self.param_vars[key] = tk.IntVar(value=default)
                tk.Entry(params, textvariable=self.param_vars[key], width=12).grid(row=row, column=1, sticky="w")
            else:
                self.param_vars[key] = tk.DoubleVar(value=default)
                tk.Entry(params, textvariable=self.param_vars[key], width=12).grid(row=row, column=1, sticky="w")
            row += 1

        for _k, _v in [("roi_x", 0), ("roi_y", 0), ("roi_w", 512), ("roi_h", 512)]:
            self.param_vars[_k] = tk.IntVar(value=_v)

        actions = tk.Frame(params)
        actions.grid(row=row, column=0, columnspan=3, pady=8, sticky="w")
        tk.Button(actions, text="Apply", command=self.apply_parameters_async).pack(side="left", padx=(0, 6))
        tk.Button(actions, text="Start Acquisition", command=self.start_acquisition).pack(side="left", padx=6)
        tk.Button(actions, text="Abort Hera Acquisition", command=self.abort_acquisition).pack(side="left", padx=6)

    def _build_tango_ui(self, parent):
        frame = tk.LabelFrame(parent, text="Stage Control", padx=10, pady=10)
        frame.pack(fill="both", expand=True)
        frame.grid_columnconfigure(0, weight=1)
        self.stage_speed_var = tk.DoubleVar(value=20.0)
        self.stage_dwell_var = tk.DoubleVar(value=0.0)
        self.live_pixel_size_var = tk.DoubleVar(value=1.0)
        self.live_invert_x_var = tk.BooleanVar(value=False)
        self.live_invert_y_var = tk.BooleanVar(value=False)
        self.live_swap_xy_var = tk.BooleanVar(value=False)
        self.position_name_var = tk.StringVar()
        self.selected_name_var = tk.StringVar()
        self.selected_x_var = tk.StringVar()
        self.selected_y_var = tk.StringVar()
        self.selected_z_var = tk.StringVar()

        tk.Label(frame, text="Position name").grid(row=0, column=0, sticky="w", pady=(0, 2))
        tk.Entry(frame, textvariable=self.position_name_var, width=24).grid(row=1, column=0, sticky="ew")

        actions = tk.Frame(frame)
        actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        tk.Button(actions, text="Add Current Position", command=self.add_current_position).pack(fill="x", pady=4)
        tk.Button(actions, text="Update Selected Position", command=self.update_selected_position).pack(fill="x", pady=4)
        tk.Button(actions, text="Delete Selected Row", command=self.delete_selected_position).pack(fill="x", pady=4)
        tk.Button(actions, text="Reconnect Stage", command=self.reconnect_stage).pack(fill="x", pady=4)

        rename_panel = tk.LabelFrame(frame, text="Rename Selected Position", padx=8, pady=8)
        rename_panel.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        tk.Entry(rename_panel, textvariable=self.selected_name_var, width=18).pack(side="left", padx=(0, 6))
        tk.Button(rename_panel, text="Rename", command=self.rename_selected_position).pack(side="left")

        self.stage_status_var = tk.StringVar(value="Stage: not connected")
        self.stage_version_var = tk.StringVar(value="Controller: -")
        self.stage_position_var = tk.StringVar(value="X: -, Y: -")
        tk.Label(frame, textvariable=self.stage_status_var, font=("Segoe UI", 10, "bold")).grid(row=4, column=0, sticky="w", pady=(12, 0))
        tk.Label(frame, textvariable=self.stage_version_var).grid(row=5, column=0, sticky="w", pady=(4, 0))

        pos_panel = tk.LabelFrame(frame, text="Current XYZ Position", padx=8, pady=8)
        pos_panel.grid(row=6, column=0, sticky="ew", pady=(10, 0))
        self.current_x_label = tk.Label(pos_panel, text="X: -")
        self.current_x_label.pack(anchor="w")
        self.current_y_label = tk.Label(pos_panel, text="Y: -")
        self.current_y_label.pack(anchor="w", pady=(4, 0))
        self.current_z_label = tk.Label(pos_panel, textvariable=self.nis_z_current_z_var)
        self.current_z_label.pack(anchor="w", pady=(4, 0))

        live_cal_panel = tk.LabelFrame(frame, text="Live Cursor Sample Mapping", padx=8, pady=8)
        live_cal_panel.grid(row=7, column=0, sticky="ew", pady=(10, 0))
        pixel_row = tk.Frame(live_cal_panel)
        pixel_row.pack(fill="x")
        tk.Label(pixel_row, text="Stage units / pixel").pack(side="left")
        tk.Entry(pixel_row, textvariable=self.live_pixel_size_var, width=8).pack(side="left", padx=(6, 0))
        axis_row = tk.Frame(live_cal_panel)
        axis_row.pack(fill="x", pady=(6, 0))
        tk.Checkbutton(axis_row, text="Invert X", variable=self.live_invert_x_var,
                       command=self._update_live_cursor_readout).pack(side="left")
        tk.Checkbutton(axis_row, text="Invert Y", variable=self.live_invert_y_var,
                       command=self._update_live_cursor_readout).pack(side="left", padx=(8, 0))
        tk.Checkbutton(axis_row, text="Swap XY", variable=self.live_swap_xy_var,
                       command=self._update_live_cursor_readout).pack(side="left", padx=(8, 0))

        goto_panel = tk.LabelFrame(frame, text="Go To Saved Position", padx=8, pady=8)
        goto_panel.grid(row=8, column=0, sticky="ew", pady=(10, 0))
        top_row = tk.Frame(goto_panel)
        top_row.pack(fill="x")
        tk.Button(top_row, text="Go", width=6, command=self.goto_selected_position).pack(side="left")
        tk.Label(top_row, text="Select a row in the table, then press Go", wraplength=180, justify="left", fg="#9aa6b2").pack(side="left", padx=8)
        coord_row = tk.Frame(goto_panel)
        coord_row.pack(fill="x", pady=(8, 0))
        tk.Label(coord_row, text="X").pack(side="left")
        tk.Entry(coord_row, textvariable=self.selected_x_var, width=10).pack(side="left", padx=(4, 10))
        tk.Label(coord_row, text="Y").pack(side="left")
        tk.Entry(coord_row, textvariable=self.selected_y_var, width=10).pack(side="left", padx=(4, 10))
        tk.Label(coord_row, text="Z").pack(side="left")
        tk.Entry(coord_row, textvariable=self.selected_z_var, width=10).pack(side="left", padx=(4, 0))
        coord_actions = tk.Frame(goto_panel)
        coord_actions.pack(fill="x", pady=(8, 0))
        tk.Button(coord_actions, text="Use Current XYZ", command=self.capture_current_stage_position_into_selected).pack(side="left", padx=(0, 6))
        tk.Button(coord_actions, text="Save Selected Edits", command=self.apply_selected_position_edits).pack(side="left", padx=6)

        tl = tk.LabelFrame(frame, text="Timelapse Settings", padx=8, pady=8)
        tl.grid(row=9, column=0, sticky="ew", pady=(10, 0))
        tk.Label(tl, text="Interval (min)").grid(row=0, column=0, sticky="w")
        self.interval_var = tk.DoubleVar(value=10.0)
        tk.Entry(tl, textvariable=self.interval_var, width=8).grid(row=0, column=1, sticky="w", padx=(6, 10))
        tk.Label(tl, text="Dwell (s)").grid(row=0, column=2, sticky="w")
        tk.Entry(tl, textvariable=self.stage_dwell_var, width=8).grid(row=0, column=3, sticky="w")
        tk.Label(tl, text="Stop after (min)").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.stop_after_var = tk.DoubleVar(value=0.0)
        tk.Entry(tl, textvariable=self.stop_after_var, width=8).grid(row=1, column=1, sticky="w", padx=(6, 10), pady=(10, 0))
        tk.Label(tl, text="Speed XY").grid(row=1, column=2, sticky="w", pady=(10, 0))
        tk.Entry(tl, textvariable=self.stage_speed_var, width=8).grid(row=1, column=3, sticky="w", pady=(10, 0))
        tk.Label(tl, textvariable=self.timelapse_status_var, font=("Segoe UI", 10, "bold")).grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))
        tk.Label(tl, textvariable=self.time_remaining_var).grid(row=2, column=2, columnspan=2, sticky="w", pady=(10, 0))

    def _build_nis_z_ui(self, parent):
        frame = tk.LabelFrame(parent, text="NIS Z Bridge", padx=10, pady=10)
        frame.pack(fill="x", pady=(10, 0))

        conn_row = tk.Frame(frame)
        conn_row.pack(fill="x", pady=(0, 6))
        tk.Label(conn_row, text="Shared folder:", fg=self.theme["muted"]).pack(side="left")
        tk.Entry(conn_row, textvariable=self.nis_z_shared_root_var, width=32).pack(side="left", padx=(6, 0))

        z_row = tk.Frame(frame)
        z_row.pack(fill="x", pady=(6, 6))
        tk.Label(z_row, text="NIS Z position:").pack(side="left")
        tk.Label(z_row, textvariable=self.nis_z_current_z_var, fg=self.theme["accent_soft"],
                 font=("Segoe UI Semibold", 10)).pack(side="left", padx=(8, 0))

        btns = tk.Frame(frame)
        btns.pack(fill="x", pady=(0, 8))
        tk.Button(btns, text="GET Z", command=self._nis_z_get).pack(side="left", padx=(0, 6))
        tk.Button(btns, text="STOP Z", command=self._nis_z_stop).pack(side="left")

        rel_frame = tk.LabelFrame(frame, text="Relative Move (um)", padx=8, pady=6)
        rel_frame.pack(fill="x", pady=(0, 8))
        step_row = tk.Frame(rel_frame)
        step_row.pack(fill="x", pady=(0, 4))
        tk.Label(step_row, text="Step (um):").pack(side="left")
        tk.Entry(step_row, textvariable=self.nis_z_step_var, width=8).pack(side="left", padx=(6, 0))
        btn_row = tk.Frame(rel_frame)
        btn_row.pack(fill="x")
        tk.Button(btn_row, text="Move +", command=lambda: self._nis_z_move_step(+1)).pack(side="left", padx=(0, 6))
        tk.Button(btn_row, text="Move -", command=lambda: self._nis_z_move_step(-1)).pack(side="left")

        tol_row = tk.Frame(frame)
        tol_row.pack(fill="x", pady=(0, 4))
        tk.Label(tol_row, text="Z tolerance (um):").pack(side="left")
        tk.Entry(tol_row, textvariable=self.nis_z_tolerance_var, width=6).pack(side="left", padx=(6, 0))
        tk.Label(tol_row, text="(skip move if already within this range)", fg=self.theme["muted"]).pack(side="left", padx=(8, 0))

        timeout_row = tk.Frame(frame)
        timeout_row.pack(fill="x")
        tk.Label(timeout_row, text="Response timeout (s):").pack(side="left")
        tk.Entry(timeout_row, textvariable=self.nis_z_timeout_var, width=5).pack(side="left", padx=(6, 0))

    def _build_log_ui(self, parent):
        state_frame = tk.LabelFrame(parent, text="Run Console", padx=10, pady=10)
        state_frame.pack(fill="x")
        self.app_state_var = tk.StringVar(value=self.app_state)
        tk.Label(state_frame, text="Current state:").pack(side="left")
        self.app_state_label = tk.Label(state_frame, textvariable=self.app_state_var, fg="#7ad97a", font=("Segoe UI Semibold", 10))
        self.app_state_label.pack(side="left", padx=6)
        ttk.Separator(state_frame, orient="vertical", style="Dark.TSeparator").pack(side="left", fill="y", padx=12)
        tk.Label(state_frame, textvariable=self.center_stage_summary_var, fg="#9aa6b2").pack(side="left")
        ttk.Separator(state_frame, orient="vertical", style="Dark.TSeparator").pack(side="left", fill="y", padx=12)
        tk.Label(state_frame, textvariable=self.current_cycle_var, fg="#9aa6b2").pack(side="left")
        ttk.Separator(state_frame, orient="vertical", style="Dark.TSeparator").pack(side="left", fill="y", padx=12)
        tk.Label(state_frame, textvariable=self.current_site_var, fg="#9aa6b2").pack(side="left")
        ttk.Separator(state_frame, orient="vertical", style="Dark.TSeparator").pack(side="left", fill="y", padx=12)
        tk.Label(state_frame, textvariable=self.nis_z_status_var, fg=self.theme["accent_soft"]).pack(side="left")

        views_frame = tk.LabelFrame(parent, text="Views", padx=10, pady=10)
        views_frame.pack(fill="both", expand=True, pady=(10, 10))
        notebook = ttk.Notebook(views_frame)
        notebook.pack(fill="both", expand=True)

        live_tab = tk.Frame(notebook, bg=self.theme["panel"])
        hyper_tab = tk.Frame(notebook, bg=self.theme["panel"])
        notebook.add(live_tab, text="Live View")
        notebook.add(hyper_tab, text="Hyperspectral View")

        live_controls = tk.Frame(live_tab, bg=self.theme["panel"])
        live_controls.pack(fill="x", padx=8, pady=(8, 4))

        live_cursor_bar = tk.Frame(live_controls, bg=self.theme["panel"])
        live_cursor_bar.pack(fill="x")
        tk.Label(live_cursor_bar, textvariable=self.live_cursor_var, fg="#e7edf5", bg=self.theme["panel"],
                 font=("Segoe UI Semibold", 10), anchor="w").pack(side="left", fill="x", expand=True)

        live_display_bar = tk.Frame(live_controls, bg=self.theme["panel"])
        live_display_bar.pack(fill="x", pady=(4, 0))
        tk.Checkbutton(live_display_bar, text="Autocontrast", variable=self.live_autocontrast_var,
                       command=lambda: self._schedule_live_render(force=True),
                       bg=self.theme["panel"], fg=self.theme["text"], selectcolor=self.theme["field"],
                       activebackground=self.theme["panel"]).pack(side="left", padx=(12, 0))
        tk.Checkbutton(live_display_bar, text="Show Saturation", variable=self.live_show_saturation_var,
                       command=lambda: self._schedule_live_render(force=True),
                       bg=self.theme["panel"], fg=self.theme["text"], selectcolor=self.theme["field"],
                       activebackground=self.theme["panel"]).pack(side="left", padx=(8, 0))
        tk.Checkbutton(live_display_bar, text="Cross", variable=self.live_cross_enabled_var,
                       command=self.toggle_live_cross,
                       bg=self.theme["panel"], fg=self.theme["text"], selectcolor=self.theme["field"],
                       activebackground=self.theme["panel"]).pack(side="left", padx=(8, 0))
        tk.Label(live_display_bar, textvariable=self.live_profile_status_var, fg="#9aa6b2", bg=self.theme["panel"]).pack(side="left", padx=(10, 4))
        tk.Label(live_display_bar, textvariable=self.live_gamma_label_var, fg="#9aa6b2", bg=self.theme["panel"]).pack(side="left", padx=(10, 4))
        tk.Scale(live_display_bar, variable=self.live_gamma_var, from_=0.2, to=3.0, resolution=0.1,
                 orient="horizontal", length=110, showvalue=False, command=self.on_live_gamma_change,
                 bg=self.theme["panel"], fg=self.theme["text"], troughcolor=self.theme["field"],
                 highlightthickness=0).pack(side="left")
        tk.Button(live_display_bar, text="Reset Gamma", command=self.reset_live_gamma).pack(side="left", padx=(6, 0))
        tk.Button(live_display_bar, text="Snapshot", command=self.snapshot_live_view).pack(side="left", padx=(8, 0))

        live_zoom_bar = tk.Frame(live_controls, bg=self.theme["panel"])
        live_zoom_bar.pack(fill="x", pady=(4, 0))
        tk.Label(live_zoom_bar, textvariable=self.live_zoom_label_var, fg="#9aa6b2", bg=self.theme["panel"]).pack(side="left", padx=(12, 4))
        tk.Button(live_zoom_bar, text="-", width=3, command=lambda: self.zoom_live_view(1 / 1.25)).pack(side="left")
        tk.Button(live_zoom_bar, text="Fit to view", command=self.fit_live_view).pack(side="left", padx=(6, 0))
        tk.Button(live_zoom_bar, text="+", width=3, command=lambda: self.zoom_live_view(1.25)).pack(side="left", padx=(6, 0))
        tk.Label(live_zoom_bar, text="Mouse wheel zoom; right-drag pan", fg="#728091", bg=self.theme["panel"]).pack(side="left", padx=(10, 0))

        live_roi_bar = tk.Frame(live_controls, bg=self.theme["panel"])
        live_roi_bar.pack(fill="x", pady=(4, 0))
        tk.Button(live_roi_bar, textvariable=self.live_roi_button_var, command=self.toggle_live_roi_selection).pack(side="right")
        tk.Button(live_roi_bar, text="Clear ROI", command=self.clear_live_roi_selection).pack(side="right", padx=(0, 6))
        tk.Label(live_roi_bar, textvariable=self.live_roi_status_var, fg="#9aa6b2", bg=self.theme["panel"],
                 anchor="w").pack(side="left", fill="x", expand=True)
        live_profile_grid = tk.Frame(live_tab, bg=self.theme["panel"])
        live_profile_grid.pack(fill="both", expand=True)
        live_profile_grid.grid_rowconfigure(0, weight=1)
        live_profile_grid.grid_columnconfigure(0, weight=1)
        self.live_view_canvas = tk.Canvas(live_profile_grid, bg="#101418", highlightthickness=0)
        self.live_view_canvas.bind("<Motion>", self.on_live_mouse_move)
        self.live_view_canvas.bind("<Button-1>", self.on_live_mouse_click)
        self.live_view_canvas.bind("<MouseWheel>", self.on_live_mousewheel)
        self.live_view_canvas.bind("<Button-4>", lambda event: self.zoom_live_view(1.25, event))
        self.live_view_canvas.bind("<Button-5>", lambda event: self.zoom_live_view(1 / 1.25, event))
        self.live_view_canvas.bind("<ButtonPress-3>", self.start_live_pan)
        self.live_view_canvas.bind("<B3-Motion>", self.on_live_pan_drag)
        self.live_view_canvas.bind("<ButtonRelease-3>", self.end_live_pan)
        self.live_view_canvas.bind("<Leave>", self.on_live_mouse_leave)
        self.live_view_canvas.grid(row=0, column=0, sticky="nsew")
        self.live_vertical_profile_canvas = tk.Canvas(live_profile_grid, bg="#101418", highlightthickness=0, width=120)
        self.live_vertical_profile_canvas.grid(row=0, column=1, sticky="ns", padx=(6, 0))
        self.live_horizontal_profile_canvas = tk.Canvas(live_profile_grid, bg="#101418", highlightthickness=0, height=105)
        self.live_horizontal_profile_canvas.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        hyper_controls = tk.Frame(hyper_tab, bg=self.theme["panel"])
        hyper_controls.pack(fill="x", padx=8, pady=(8, 4))
        tk.Button(hyper_controls, text="Prev Band", command=lambda: self.step_hyper_band(-1)).pack(side="left", padx=(0, 8))
        tk.Label(hyper_controls, textvariable=self.current_hyper_band_var, fg="#e7edf5").pack(side="left")
        ttk.Separator(hyper_controls, orient="vertical", style="Dark.TSeparator").pack(side="left", fill="y", padx=12)
        tk.Label(hyper_controls, textvariable=self.current_hyper_wavelength_var, fg="#9aa6b2").pack(side="left")
        jump_wrap = tk.Frame(hyper_controls, bg=self.theme["panel"])
        jump_wrap.pack(side="right", padx=(8, 0))
        tk.Button(jump_wrap, text="Go", command=self.jump_to_hyper_band).pack(side="right")
        tk.Entry(jump_wrap, textvariable=self.hyper_band_jump_var, width=6).pack(side="right", padx=(0, 6))
        tk.Label(jump_wrap, text="Band", fg="#9aa6b2").pack(side="right", padx=(0, 6))
        tk.Button(hyper_controls, text="Next Band", command=lambda: self.step_hyper_band(1)).pack(side="right")
        self.hyper_band_scale = tk.Scale(
            hyper_tab,
            from_=0,
            to=0,
            orient="horizontal",
            variable=self.current_hyper_band_index,
            command=self.on_hyper_band_changed,
            showvalue=False,
            highlightthickness=0,
            bd=0,
            bg=self.theme["panel"],
            fg=self.theme["text"],
            troughcolor=self.theme["panel_alt"],
            activebackground=self.theme["accent"],
            sliderlength=28,
            width=18,
            repeatdelay=150,
            repeatinterval=80,
            takefocus=1,
            cursor="hand2",
        )
        self.hyper_band_scale.pack(fill="x", padx=8, pady=(0, 6))
        self.hyper_view_canvas = tk.Canvas(hyper_tab, bg="#101418", highlightthickness=0)
        self.hyper_view_canvas.pack(fill="both", expand=True)
        self.live_view_canvas.bind("<Configure>", lambda _e: self._draw_live_view_placeholder())
        self.live_vertical_profile_canvas.bind("<Configure>", lambda _e: self._render_live_profiles())
        self.live_horizontal_profile_canvas.bind("<Configure>", lambda _e: self._render_live_profiles())
        self.hyper_view_canvas.bind("<Configure>", lambda _e: self.render_current_hyper_band())
        for widget in (hyper_tab, self.hyper_band_scale, self.hyper_view_canvas):
            widget.bind("<Left>", lambda _e: self.step_hyper_band(-1))
            widget.bind("<Right>", lambda _e: self.step_hyper_band(1))
            widget.bind("<MouseWheel>", self.on_hyper_mousewheel)
            widget.bind("<Button-4>", lambda _e: self.step_hyper_band(1))
            widget.bind("<Button-5>", lambda _e: self.step_hyper_band(-1))
            widget.bind("<Button-1>", lambda _e, target=widget: target.focus_set(), add="+")

        pos_frame = tk.LabelFrame(parent, text="Saved Positions", padx=10, pady=10)
        pos_frame.pack(fill="x", pady=(0, 10))
        header = tk.Frame(pos_frame)
        header.pack(fill="x", pady=(0, 8))
        tk.Label(header, text="Choose a site in the list, edit it on the left, then run or schedule it from the top bar.", fg="#9aa6b2").pack(side="left")

        center_tree_wrap = tk.Frame(pos_frame)
        center_tree_wrap.pack(fill="both", expand=True)
        self.positions_tree = ttk.Treeview(center_tree_wrap, columns=("name", "x", "y", "z"), show="headings", height=4, style="Dark.Treeview")
        self.positions_tree.heading("name", text="Name")
        self.positions_tree.heading("x", text="X")
        self.positions_tree.heading("y", text="Y")
        self.positions_tree.heading("z", text="Z")
        self.positions_tree.column("name", width=260, anchor="w")
        self.positions_tree.column("x", width=150, anchor="e")
        self.positions_tree.column("y", width=150, anchor="e")
        self.positions_tree.column("z", width=150, anchor="e")
        center_scroll = ttk.Scrollbar(center_tree_wrap, orient="vertical", command=self.positions_tree.yview)
        self.positions_tree.configure(yscrollcommand=center_scroll.set)
        self.positions_tree.pack(side="left", fill="both", expand=True)
        center_scroll.pack(side="right", fill="y")
        self.positions_tree.bind("<<TreeviewSelect>>", self.on_position_selected)

        status_strip = tk.Frame(parent)
        status_strip.pack(fill="x", pady=(0, 10))
        tk.Label(status_strip, textvariable=self.timelapse_status_var, font=("Segoe UI Semibold", 10)).pack(side="left")
        ttk.Separator(status_strip, orient="vertical", style="Dark.TSeparator").pack(side="left", fill="y", padx=12)
        tk.Label(status_strip, textvariable=self.time_remaining_var, fg="#9aa6b2").pack(side="left")
        ttk.Separator(status_strip, orient="vertical", style="Dark.TSeparator").pack(side="left", fill="y", padx=12)
        tk.Label(status_strip, textvariable=self.last_export_var, fg="#9aa6b2").pack(side="left")

        log_frame = tk.LabelFrame(parent, text="Status / Messages", padx=10, pady=10)
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frame, height=16, state="disabled", wrap="word", bg="#0f1318", fg="#e7edf5", insertbackground="#ffb37a", relief="flat")
        self.log_text.pack(fill="both", expand=True)

    def browse_dll(self):
        file_path = filedialog.askopenfilename(title="Select Hera API DLL", filetypes=[("DLL files", "*.dll"), ("All files", "*.*")])
        if file_path:
            self.dll_path_var.set(file_path)

    def browse_tango_dll(self):
        file_path = filedialog.askopenfilename(title="Select Tango DLL", filetypes=[("DLL files", "*.dll"), ("All files", "*.*")])
        if file_path:
            self.tango_dll_var.set(file_path)

    def browse_output_path(self):
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self.param_vars["output_path"].set(folder)

    def browse_hyperlab_shortcut(self):
        file_path = filedialog.askopenfilename(
            title="Select Nireos HyperLAB shortcut or application",
            filetypes=[("Shortcut or executable", "*.lnk *.exe"), ("All files", "*.*")],
        )
        if file_path:
            self.hyperlab_shortcut_var.set(file_path)

    def open_current_in_hyperlab(self):
        hdr_path = self.last_export_path
        if not hdr_path or not os.path.exists(hdr_path):
            from tkinter import messagebox
            messagebox.showinfo("Open in HyperLAB", "No exported hyperspectral cube is available yet.")
            self.log("Open in HyperLAB skipped: no exported hyperspectral cube is available yet.")
            return

        shortcut_path = self.hyperlab_shortcut_var.get().strip()
        if not shortcut_path or not os.path.exists(shortcut_path):
            from tkinter import messagebox
            messagebox.showerror("Open in HyperLAB", f"HyperLAB shortcut not found:\n{shortcut_path}")
            self.log(f"Open in HyperLAB failed: shortcut not found: {shortcut_path}")
            return

        try:
            try:
                os.startfile(shortcut_path, "open", f'"{hdr_path}"')
                self.log(f"Opened current hyperspectral cube in HyperLAB: {hdr_path}")
            except TypeError:
                os.startfile(shortcut_path)
                self._copy_last_export_path_to_clipboard(hdr_path)
                self.log(f"Opened HyperLAB. Last export path copied to clipboard: {hdr_path}")
        except Exception as exc:
            try:
                os.startfile(shortcut_path)
                self._copy_last_export_path_to_clipboard(hdr_path)
                from tkinter import messagebox
                messagebox.showinfo(
                    "Open in HyperLAB",
                    "HyperLAB was opened, but Windows did not accept the cube path automatically. "
                    "The last .hdr path was copied to the clipboard.",
                )
                self.log(f"Opened HyperLAB without file argument. Last export path copied to clipboard: {hdr_path}")
            except Exception as fallback_exc:
                from tkinter import messagebox
                messagebox.showerror("Open in HyperLAB", f"Could not open HyperLAB:\n{fallback_exc}")
                self.log(f"Open in HyperLAB failed: {exc}; fallback failed: {fallback_exc}")

    def _copy_last_export_path_to_clipboard(self, hdr_path):
        self.clipboard_clear()
        self.clipboard_append(hdr_path)
