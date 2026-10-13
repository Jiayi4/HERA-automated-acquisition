import copy
import json
import math
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from hera_app.controllers import SavedPosition
from hera_app.tissue_scan import FieldCalibration, build_tissue_plan, select_tissue_test_tiles, validate_tissue_plan


class TissueScanMixin:
    def open_tissue_scan_dialog(self):
        existing = getattr(self, "tissue_scan_dialog", None)
        if existing and existing.winfo_exists():
            existing.lift()
            return
        try:
            signature = self._tissue_signature()
        except Exception as exc:
            messagebox.showerror("Tissue Scan Plan", str(exc), parent=self)
            return
        state = getattr(self, "tissue_scan_state", None)
        if not state or state["signature"] != signature:
            state = {"signature": signature, "landmarks": {}, "boundaries": {}, "focus": []}
            self.tissue_scan_state = state
        self.tissue_scan_plan = None
        self.tissue_scan_pick = None
        self.tissue_scan_capture_busy = False
        dialog = tk.Toplevel(self)
        self.tissue_scan_dialog = dialog
        dialog.title("Tissue Scan Plan")
        dialog.transient(self)
        dialog.geometry("790x650")
        dialog.minsize(730, 580)
        dialog.protocol("WM_DELETE_WINDOW", self._close_tissue_scan_dialog)
        header = tk.Frame(dialog, padx=14, pady=10)
        header.pack(fill="x")
        tk.Label(header, text="Tissue Scan Plan", font=("Segoe UI", 14, "bold")).pack(side="left")
        tk.Label(header, text="Overlap 10%", fg=self.theme["muted"]).pack(side="right")
        self.tissue_scan_status = tk.StringVar(value="Pick A near the center, B near a side, C in a different direction; use the same landmark.")
        self.tissue_scan_notebook = ttk.Notebook(dialog)
        self.tissue_scan_notebook.pack(fill="both", expand=True, padx=14)
        field, region, preview = (tk.Frame(self.tissue_scan_notebook, padx=10, pady=10) for _ in range(3))
        for frame, title in zip((field, region, preview), ("1  Field Calibration", "2  Tissue & Focus", "3  Preview")):
            self.tissue_scan_notebook.add(frame, text=title)
        self._build_tissue_field_tab(field)
        self._build_tissue_region_tab(region)
        self._build_tissue_preview_tab(preview)
        self.tissue_scan_notebook.bind("<<NotebookTabChanged>>", self._tissue_tab_changed)
        status_label = tk.Label(dialog, textvariable=self.tissue_scan_status, anchor="w", wraplength=740)
        status_label.pack(fill="x", padx=14, pady=10)
        dialog.bind("<Configure>", lambda event: status_label.configure(wraplength=max(300, event.width - 28))
                    if event.widget is dialog else None, add="+")
        self._apply_theme_recursive(dialog)
        self._refresh_tissue_records()

    def _build_tissue_field_tab(self, parent):
        self.tissue_scan_field_summary = tk.StringVar()
        tk.Label(parent, textvariable=self.tissue_scan_field_summary, anchor="w").pack(fill="x", pady=(0, 10))
        self.tissue_scan_landmark_tree = ttk.Treeview(
            parent, columns=("pixel", "xy"), show="tree headings", height=3, selectmode="browse"
        )
        tree = self.tissue_scan_landmark_tree
        tree.heading("#0", text="Landmark capture")
        tree.column("#0", width=130, stretch=False)
        tree.heading("pixel", text="Image pixel")
        tree.heading("xy", text="Stage XY [mm]")
        tree.column("pixel", width=160)
        tree.column("xy", width=260)
        tree.pack(fill="x")
        picks = tk.Frame(parent)
        picks.pack(fill="x", pady=10)
        for point in ("A", "B", "C"):
            tk.Button(picks, text=f"Pick {point}", command=lambda name=point: self._arm_tissue_landmark(name),
                      width=12).pack(side="left", padx=(0, 8))
        tk.Label(parent, text="Calibration profile", anchor="w").pack(fill="x", pady=(12, 3))
        self.tissue_scan_profile_name = tk.StringVar(value=self.tissue_scan_state.get("profile_name", "Current optics"))
        tk.Entry(parent, textvariable=self.tissue_scan_profile_name).pack(fill="x")
        files = tk.Frame(parent)
        files.pack(fill="x", pady=10)
        tk.Button(files, text="Load Calibration", command=self.load_tissue_calibration).pack(side="left")
        tk.Button(files, text="Save Calibration", command=self.save_tissue_calibration).pack(side="left", padx=8)
        tk.Button(parent, text="Next: Tissue & Focus", command=lambda: self._tissue_next_tab(1)).pack(
            side="bottom", anchor="e", pady=8
        )

    def _build_tissue_region_tab(self, parent):
        self.tissue_scan_boundary_labels = {}
        boundary_grid = tk.Frame(parent)
        boundary_grid.pack(fill="x")
        boundary_grid.columnconfigure(1, weight=1)
        for row, name in enumerate(("Left", "Right", "Top", "Bottom")):
            tk.Label(boundary_grid, text=name, width=8, anchor="w").grid(row=row, column=0, pady=4)
            value = tk.StringVar(value="Not captured")
            self.tissue_scan_boundary_labels[name] = value
            tk.Label(boundary_grid, textvariable=value, anchor="w").grid(row=row, column=1, sticky="w", padx=8)
            tk.Button(boundary_grid, text="Capture", width=9,
                      command=lambda key=name: self.capture_tissue_boundary(key)).grid(row=row, column=2, padx=4)
            tk.Button(boundary_grid, text="Go To", width=7,
                      command=lambda key=name: self._goto_tissue_record(key)).grid(row=row, column=3)
        options = tk.Frame(parent)
        options.pack(fill="x", pady=(8, 12))
        self.tissue_scan_include_z = tk.BooleanVar(value=True)
        tk.Checkbutton(options, text="Capture focused Z", variable=self.tissue_scan_include_z).pack(side="left")
        tk.Label(options, text="Edge margin [% FOV]").pack(side="left", padx=(15, 5))
        self.tissue_scan_margin = tk.StringVar(value="5")
        tk.Entry(options, textvariable=self.tissue_scan_margin, width=6).pack(side="left")
        tk.Label(parent, text="Additional focus points", anchor="w", font=("Segoe UI", 10, "bold")).pack(fill="x")
        self.tissue_scan_focus_tree = ttk.Treeview(parent, columns=("xy", "z"), show="headings", height=5)
        self.tissue_scan_focus_tree.heading("xy", text="Stage XY [mm]")
        self.tissue_scan_focus_tree.heading("z", text="Focused Z [um]")
        self.tissue_scan_focus_tree.pack(fill="both", expand=True, pady=6)
        actions = tk.Frame(parent)
        actions.pack(fill="x")
        tk.Button(actions, text="Add Focus Point", command=self.capture_tissue_focus).pack(side="left")
        tk.Button(actions, text="Remove", command=self._remove_tissue_focus).pack(side="left", padx=6)
        tk.Button(actions, text="Go To", command=lambda: self._goto_tissue_record(None)).pack(side="left")
        tk.Button(parent, text="Preview Grid", command=self.preview_tissue_grid).pack(side="bottom", anchor="e", pady=8)

    def _build_tissue_preview_tab(self, parent):
        self.tissue_scan_summary = tk.StringVar(value="No grid generated")
        tk.Label(parent, textvariable=self.tissue_scan_summary, anchor="w", justify="left").pack(fill="x")
        self.tissue_scan_canvas = tk.Canvas(parent, height=310, highlightthickness=0)
        self.tissue_scan_canvas.pack(fill="both", expand=True, pady=8)
        self.tissue_scan_canvas.bind("<Configure>", lambda _event: self._draw_tissue_preview())
        self.tissue_scan_canvas.bind("<Button-1>", self._select_tissue_tile)
        self.tissue_scan_tile_info = tk.StringVar(value="No tile selected")
        tk.Label(parent, textvariable=self.tissue_scan_tile_info, anchor="w", wraplength=690).pack(fill="x")
        actions = tk.Frame(parent)
        actions.pack(fill="x", pady=10)
        tk.Button(actions, text="Go To Tile", command=self._goto_tissue_tile).pack(side="left")
        tk.Button(actions, text="Export Plan", command=self.export_tissue_plan).pack(side="left", padx=8)
        tk.Button(actions, text="Generate Saved Sites", command=self.generate_tissue_sites).pack(side="right")
        self.tissue_scan_selected_tile = 0

    def _tissue_signature(self):
        roi = self._capture_current_roi_for_position()
        with self.live_frame_lock:
            size = self.live_display_frame_size
        if not roi or not size:
            raise ValueError("Apply a fixed ROI and start Live View before opening Tissue Scan Plan.")
        return {"roi": list(roi), "frame_size": list(size), "rotation": self._get_live_display_rotation(),
                "binning": self.param_vars["binning"].get()}

    def _tissue_roi_pixel(self, image_x, image_y):
        signature = self.tissue_scan_state["signature"]
        rx, ry, rw, rh = signature["roi"]
        width, height = signature["frame_size"]
        ox, oy = self._live_crop_offset
        local_x, local_y = image_x - ox, image_y - oy
        with self.live_frame_lock:
            info, preview = self.live_frame_info, self.latest_live_frame
        if not info or not preview:
            raise ValueError("Wait for a fresh Live frame before Capture.")
        raw_width, raw_height = info[:2]
        if abs(raw_width - rw) <= 2 and abs(raw_height - rh) <= 2:
            roi_x = (local_x + 0.5) * rw / width - 0.5
            roi_y = (local_y + 0.5) * rh / height - 0.5
        else:
            # A software-cropped preview starts at a rounded-down preview pixel.
            sx, sy = raw_width / preview[0], raw_height / preview[1]
            if width != math.ceil((rx + rw) / sx) - int(rx / sx) or height != math.ceil((ry + rh) / sy) - int(ry / sy):
                raise ValueError("Live framing does not match the selected ROI. Restart Live View and retry.")
            roi_x = (int(rx / sx) + local_x + 0.5) * sx - rx - 0.5
            roi_y = (int(ry / sy) + local_y + 0.5) * sy - ry - 0.5
        return self._raw_live_xy_to_display_xy(roi_x, roi_y, rw, rh)[:2]

    def _tissue_center_xyz(self, xyz):
        calibration = self._tissue_calibration()
        px, py = self._tissue_roi_pixel(*self.live_cross_point)
        width, height = self._live_display_dimensions(*self.tissue_scan_state["signature"]["roi"][2:])
        du, dv = ((width - 1) / 2 - px) / width, ((height - 1) / 2 - py) / height
        return (xyz[0] - du * calibration.right[0] - dv * calibration.down[0],
                xyz[1] - du * calibration.right[1] - dv * calibration.down[1], xyz[2])

    def _check_tissue_context(self):
        if self._tissue_signature() != self.tissue_scan_state["signature"]:
            raise ValueError("ROI, live image size or binning changed. Reopen Tissue Scan Plan and recalibrate.")
        reason = self._acquisition_busy_reason(include_sdk=False)
        if reason:
            raise ValueError(f"Wait: {reason}.")
        if self.timelapse_thread and self.timelapse_thread.is_alive():
            raise ValueError("Stop the timelapse before configuring Tissue Scan Plan.")

    def _tissue_error(self, exc):
        self.tissue_scan_status.set(str(exc))
        self.log(f"Tissue Scan: {exc}")
        messagebox.showerror("Tissue Scan Plan", str(exc), parent=self.tissue_scan_dialog)

    def _arm_tissue_landmark(self, point):
        try:
            self._check_tissue_context()
            if self.tissue_scan_capture_busy:
                return
            if self.live_roi_selecting:
                raise ValueError("Finish ROI selection first.")
            self.tissue_scan_pick = point
            self.tissue_scan_status.set(
                f"Pick {point}: click the same landmark in Live View after the stage has stopped."
            )
        except Exception as exc:
            self._tissue_error(exc)

    def _tissue_landmark_click(self, image_pos):
        point = getattr(self, "tissue_scan_pick", None)
        if not point:
            return False
        try:
            self._check_tissue_context()
            x, y, _width, _height = image_pos
            px, py = self._tissue_roi_pixel(x, y)
            self.tissue_scan_pick = None
            self.live_cross_enabled_var.set(True)
            self.live_cross_point = (x, y)
            self._schedule_live_render(force=True)

            def accept(xyz):
                self.tissue_scan_state["landmarks"][point] = (px, py, xyz[0], xyz[1])
                self.log(f"Tissue Scan landmark {point}: ROI pixel=({px:.3f}, {py:.3f}), "
                         f"Stage XY=({xyz[0]:.6f}, {xyz[1]:.6f}) mm.")
                self._invalidate_tissue_plan()
                self._refresh_tissue_records()
                self.tissue_scan_status.set(f"Captured {point}. Move the same landmark to a different part of the field.")

            self._capture_tissue_xyz(accept, need_z=False)
        except Exception as exc:
            self._tissue_error(exc)
        return True

    def _capture_tissue_xyz(self, accept, need_z):
        self._check_tissue_context()
        if self.tissue_scan_capture_busy:
            return
        if not self.tango or not self.tango.connected:
            raise ValueError("Connect the Tango stage first.")
        if need_z and not getattr(self, "micro_z_connected", False):
            raise ValueError("Connect Z and focus the tissue before Capture, or turn off Capture focused Z.")
        self.tissue_scan_capture_busy = True
        dialog = self.tissue_scan_dialog
        self.tissue_scan_status.set("Reading position...")

        def complete(xyz, error):
            if getattr(self, "tissue_scan_dialog", None) is not dialog:
                return
            self.tissue_scan_capture_busy = False
            try:
                self._check_tissue_context()
                if error:
                    raise ValueError(error)
                accept(xyz)
            except Exception as exc:
                self._tissue_error(exc)

        def worker():
            xyz, error = None, None
            try:
                with self.stage_lock:
                    x, y, _, _ = self.tango.get_position()
                z = self._get_current_z_or_nan() if need_z else None
                if need_z and (z is None or not math.isfinite(z)):
                    raise ValueError("A real focused Z could not be read. Reconnect Z and retry.")
                with self.stage_lock:
                    end_x, end_y, _, _ = self.tango.get_position()
                if math.hypot(end_x - x, end_y - y) > 0.0001 or getattr(self, "stage_motion_inflight", False):
                    raise ValueError("The stage moved during Capture. Stop it and retry.")
                if not all(math.isfinite(value) for value in (x, y)):
                    raise ValueError("The stage returned invalid coordinates.")
                xyz = (float(x), float(y), float(z) if need_z else None)
            except Exception as exc:
                error = str(exc)
            self._safe_after(0, lambda: complete(xyz, error))

        threading.Thread(target=worker, daemon=True).start()

    def _tissue_calibration(self):
        points = self.tissue_scan_state["landmarks"]
        ordered = [points[name] for name in ("A", "B", "C") if name in points]
        signature = self.tissue_scan_state["signature"]
        width, height = self._live_display_dimensions(*signature["roi"][2:])
        return FieldCalibration.from_landmarks(ordered, (width, height))

    def _tissue_tab_changed(self, _event=None):
        self.tissue_scan_pick = None
        if self.tissue_scan_notebook.index("current") == 1:
            self.reset_live_cross_center()
            self.tissue_scan_status.set("Align each tissue boundary with the centered Cross; focus before Capture.")

    def _tissue_next_tab(self, tab):
        try:
            self._check_tissue_context()
            if self.tissue_scan_capture_busy:
                raise ValueError("Wait for Capture to finish.")
            self._tissue_calibration()
            self.tissue_scan_notebook.select(tab)
        except Exception as exc:
            self._tissue_error(exc)

    def capture_tissue_boundary(self, name):
        try:
            self._tissue_calibration()
            self._check_tissue_center()

            def accept(xyz):
                self._check_tissue_center()
                xyz = self._tissue_center_xyz(xyz)
                self.tissue_scan_state["boundaries"][name] = xyz
                self.log(f"Tissue Scan boundary {name}: X={xyz[0]:.6f}, Y={xyz[1]:.6f} mm, "
                         + (f"Z={xyz[2]:.3f} um." if xyz[2] is not None else "Z not captured."))
                self._invalidate_tissue_plan()
                self._refresh_tissue_records()
                self.tissue_scan_status.set(f"Captured {name}: X={xyz[0]:.4f}, Y={xyz[1]:.4f} mm.")

            self._capture_tissue_xyz(accept, self.tissue_scan_include_z.get())
        except Exception as exc:
            self._tissue_error(exc)

    def _check_tissue_center(self):
        self._check_tissue_context()
        width, height = self.tissue_scan_state["signature"]["frame_size"]
        ox, oy = self._live_crop_offset
        center = (ox + width // 2, oy + height // 2)
        if not self.live_cross_enabled_var.get() or self.live_cross_point != center:
            raise ValueError("Click Center in Live View and align the boundary with that Cross before Capture.")

    def capture_tissue_focus(self):
        try:
            self._check_tissue_center()

            def accept(xyz):
                self._check_tissue_center()
                xyz = self._tissue_center_xyz(xyz)
                focus = self.tissue_scan_state["focus"]
                for i, old in enumerate(focus):
                    if math.hypot(old[0] - xyz[0], old[1] - xyz[1]) < 1e-7:
                        focus[i] = xyz
                        break
                else:
                    focus.append(xyz)
                self._invalidate_tissue_plan()
                self._refresh_tissue_records()
                self.log(f"Tissue Scan focus: X={xyz[0]:.6f}, Y={xyz[1]:.6f} mm, Z={xyz[2]:.3f} um.")
                self.tissue_scan_status.set(f"Focused point added: Z={xyz[2]:.3f} um.")

            self._capture_tissue_xyz(accept, True)
        except Exception as exc:
            self._tissue_error(exc)

    def _remove_tissue_focus(self):
        selected = self.tissue_scan_focus_tree.selection()
        if selected and not self.tissue_scan_capture_busy:
            del self.tissue_scan_state["focus"][int(selected[0])]
            self._invalidate_tissue_plan()
            self._refresh_tissue_records()

    def _goto_tissue_record(self, name):
        try:
            self._check_tissue_context()
            if self.tissue_scan_capture_busy:
                raise ValueError("Wait for Capture to finish.")
            if name:
                xyz = self.tissue_scan_state["boundaries"].get(name)
            else:
                selected = self.tissue_scan_focus_tree.selection()
                xyz = self.tissue_scan_state["focus"][int(selected[0])] if selected else None
            if xyz is None:
                raise ValueError("Capture or select a position first.")
            self._move_stage_to_saved_position_async(
                SavedPosition(name or "Focus point", xyz[0], xyz[1], xyz[2] if xyz[2] is not None else 0,
                              tuple(self.tissue_scan_state["signature"]["roi"]), z_is_real=xyz[2] is not None)
            )
        except Exception as exc:
            self._tissue_error(exc)

    def _refresh_tissue_records(self):
        state = self.tissue_scan_state
        tree = self.tissue_scan_landmark_tree
        tree.delete(*tree.get_children())
        for name in ("A", "B", "C"):
            record = state["landmarks"].get(name)
            values = (f"{record[0]:.0f}, {record[1]:.0f}", f"{record[2]:.6f}, {record[3]:.6f}") if record else ("-", "-")
            tree.insert("", "end", iid=name, text=name, values=values)
        try:
            calibration = self._tissue_calibration()
            self.tissue_scan_field_summary.set(
                f"Field: {math.hypot(*calibration.right):.4f} x {math.hypot(*calibration.down):.4f} mm | Ready"
            )
        except ValueError:
            self.tissue_scan_field_summary.set("Field calibration: waiting for A, B and C")
        for name, label in self.tissue_scan_boundary_labels.items():
            xyz = state["boundaries"].get(name)
            if xyz:
                z = f"{xyz[2]:.3f} um" if xyz[2] is not None else "Not captured"
                label.set(f"X {xyz[0]:.4f}  Y {xyz[1]:.4f} mm   Z {z}")
            else:
                label.set("Not captured")
        tree = self.tissue_scan_focus_tree
        tree.delete(*tree.get_children())
        for i, (x, y, z) in enumerate(state["focus"]):
            tree.insert("", "end", iid=str(i), values=(f"{x:.6f}, {y:.6f}", f"{z:.3f}"))

    def _invalidate_tissue_plan(self):
        self.tissue_scan_plan = None
        self.tissue_scan_summary.set("Preview needs refreshing")
        self.tissue_scan_tile_info.set("No tile selected")
        self._draw_tissue_preview()

    def _make_tissue_plan(self):
        self._check_tissue_context()
        if self.tissue_scan_capture_busy:
            raise ValueError("Wait for Capture to finish.")
        state = self.tissue_scan_state
        plan = build_tissue_plan(self._tissue_calibration(), state["boundaries"], state["focus"],
                                 margin=float(self.tissue_scan_margin.get()) / 100)
        for tile in plan["tiles"]:
            error = self._micro_z_validate_target_range(tile["z"])
            if error:
                raise ValueError(f"{tile['name']}: {error}")
        plan["signature"] = state["signature"]
        plan["margin_percent"] = float(self.tissue_scan_margin.get())
        return plan

    def preview_tissue_grid(self):
        try:
            self.tissue_scan_plan = self._make_tissue_plan()
            self.tissue_scan_selected_tile = 0
            plan = self.tissue_scan_plan
            values = [tile["z"] for tile in plan["tiles"]]
            self.tissue_scan_summary.set(
                f"{plan['rows']} rows x {plan['columns']} columns | {len(values)} tiles | Overlap 10%\n"
                f"Estimated Z: {min(values):.3f} - {max(values):.3f} um | "
                f"{plan['focus_extrapolated_count']} tiles beyond focused area"
            )
            self.tissue_scan_status.set("Initial Z only; check edge tiles and uneven tissue before scanning.")
            self.tissue_scan_notebook.select(2)
            self._draw_tissue_preview()
        except Exception as exc:
            self._invalidate_tissue_plan()
            self._tissue_error(exc)

    def _draw_tissue_preview(self):
        canvas = getattr(self, "tissue_scan_canvas", None)
        if not canvas or not canvas.winfo_exists():
            return
        canvas.delete("all")
        plan = self.tissue_scan_plan
        if not plan:
            return
        tiles = plan["tiles"]
        low_u = min(tile["u"] for tile in tiles) - 0.5
        high_u = max(tile["u"] for tile in tiles) + 0.5
        low_v = min(tile["v"] for tile in tiles) - 0.5
        high_v = max(tile["v"] for tile in tiles) + 0.5
        width, height = max(canvas.winfo_width(), 100), max(canvas.winfo_height(), 100)
        signature = self.tissue_scan_state["signature"]
        field_w, field_h = self._live_display_dimensions(*signature["roi"][2:])
        aspect = field_w / field_h
        scale = min((width - 36) / ((high_u - low_u) * aspect), (height - 36) / (high_v - low_v))
        left = (width - (high_u - low_u) * aspect * scale) / 2
        top = (height - (high_v - low_v) * scale) / 2
        self.tissue_scan_preview_transform = (left, top, scale, aspect, low_u, low_v)

        def point(u, v):
            return left + (u - low_u) * scale * aspect, top + (v - low_v) * scale

        bounds = plan["bounds"]
        canvas.create_rectangle(*point(bounds[0], bounds[1]), *point(bounds[2], bounds[3]),
                                fill=self.theme["panel"], outline="")
        path = []
        for i, tile in enumerate(tiles):
            color = self.theme["accent_soft"] if tile["focus_extrapolated"] else self.theme["accent"]
            if i == self.tissue_scan_selected_tile:
                color = "#46d66f"
            canvas.create_rectangle(*point(tile["u"] - 0.5, tile["v"] - 0.5),
                                    *point(tile["u"] + 0.5, tile["v"] + 0.5), outline=color,
                                    width=2 if i == self.tissue_scan_selected_tile else 1)
            path.extend(point(tile["u"], tile["v"]))
        if len(path) > 2:
            canvas.create_line(*path, fill=self.theme["muted"], dash=(3, 5))
        for xyz in list(self.tissue_scan_state["boundaries"].values()) + self.tissue_scan_state["focus"]:
            if xyz[2] is not None:
                u, v = self._tissue_calibration().project(xyz[:2], plan["origin"])
                x, y = point(u, v)
                canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=self.theme["text"], outline="")
        tile = tiles[self.tissue_scan_selected_tile]
        self.tissue_scan_tile_info.set(
            f"{tile['name']} | X {tile['x']:.6f}  Y {tile['y']:.6f} mm | Z {tile['z']:.3f} um"
            + (" | Check focus: outside measured area" if tile["focus_extrapolated"] else "")
        )

    def _select_tissue_tile(self, event):
        if not self.tissue_scan_plan:
            return
        left, top, scale, aspect, low_u, low_v = self.tissue_scan_preview_transform
        u, v = (event.x - left) / (scale * aspect) + low_u, (event.y - top) / scale + low_v
        tiles = self.tissue_scan_plan["tiles"]
        self.tissue_scan_selected_tile = min(range(len(tiles)), key=lambda i: (tiles[i]["u"] - u) ** 2 + (tiles[i]["v"] - v) ** 2)
        self._draw_tissue_preview()

    def _require_current_tissue_plan(self):
        self._check_tissue_context()
        if self.tissue_scan_capture_busy:
            raise ValueError("Wait for Capture to finish.")
        plan = self.tissue_scan_plan
        if not plan or plan["margin_percent"] != float(self.tissue_scan_margin.get()):
            raise ValueError("Click Preview Grid before continuing.")
        return plan

    def _tissue_position(self, tile):
        return SavedPosition(tile["name"], tile["x"], tile["y"], tile["z"],
                             tuple(self.tissue_scan_state["signature"]["roi"]), z_is_real=True)

    def _goto_tissue_tile(self):
        try:
            plan = self._require_current_tissue_plan()
            self._move_stage_to_saved_position_async(self._tissue_position(plan["tiles"][self.tissue_scan_selected_tile]))
        except Exception as exc:
            self._tissue_error(exc)

    def generate_tissue_sites(self):
        try:
            plan = self._require_current_tissue_plan()
            count = len(plan["tiles"])
            if self.positions and not messagebox.askyesno(
                "Replace Saved Sites", f"Replace {len(self.positions)} Saved Sites with {count} tissue tiles?",
                parent=self.tissue_scan_dialog,
            ):
                return
            self.positions = [self._tissue_position(tile) for tile in plan["tiles"]]
            self.tissue_layout_plan = copy.deepcopy(plan)
            self.tissue_layout_selected_cell = None
            self.tissue_layout_calibration = copy.deepcopy(self.tissue_scan_state)
            self.tissue_layout_sites = list(self.positions)
            self.selected_position_index = 0
            self.refresh_positions_tree()
            self.timelapse_sites_var.set("all")
            self.log(f"Tissue Scan generated {count} sites: {plan['rows']}x{plan['columns']}, overlap=10%, "
                     f"ROI={self.tissue_scan_state['signature']['roi']}, "
                     f"focus extrapolated={plan['focus_extrapolated_count']}. Check saved Z before scanning.")
            self.tissue_scan_status.set(f"Generated {count} Saved Sites. Check focus, export the table, then Run One Loop.")
            self.open_tissue_layout()
        except Exception as exc:
            self._tissue_error(exc)

    def save_tissue_calibration(self):
        try:
            self._check_tissue_context()
            if self.tissue_scan_capture_busy:
                raise ValueError("Wait for Capture to finish.")
            self._tissue_calibration()
            path = filedialog.asksaveasfilename(parent=self.tissue_scan_dialog, title="Save Field Calibration",
                                               defaultextension=".json", filetypes=[("Calibration", "*.json")])
            if path:
                state = self.tissue_scan_state
                state["profile_name"] = self.tissue_scan_profile_name.get().strip()
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump({"type": "hera_tissue_calibration", "version": 1, "signature": state["signature"],
                               "profile_name": state["profile_name"], "landmarks": state["landmarks"]}, handle, indent=2)
                self.tissue_scan_status.set("Calibration saved")
        except Exception as exc:
            self._tissue_error(exc)

    def load_tissue_calibration(self):
        try:
            self._check_tissue_context()
            if self.tissue_scan_capture_busy:
                raise ValueError("Wait for Capture to finish.")
            path = filedialog.askopenfilename(parent=self.tissue_scan_dialog, title="Load Field Calibration",
                                             filetypes=[("Calibration", "*.json")])
            if not path:
                return
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            if data.get("type") != "hera_tissue_calibration" or data.get("version") != 1:
                raise ValueError("Not a supported Tissue Scan Plan calibration file.")
            if data["signature"] != self.tissue_scan_state["signature"]:
                raise ValueError("This calibration uses a different ROI, live size, rotation or binning.")
            points = data["landmarks"]
            FieldCalibration.from_landmarks([points[key] for key in ("A", "B", "C")],
                                           self._live_display_dimensions(*data["signature"]["roi"][2:]))
            if not messagebox.askyesno("Reuse Calibration", "Are the objective and optical magnification unchanged?",
                                      parent=self.tissue_scan_dialog):
                return
            self.tissue_scan_state["landmarks"] = points
            self.tissue_scan_state["boundaries"] = {}
            self.tissue_scan_state["focus"] = []
            self.tissue_scan_profile_name.set(data.get("profile_name", "Current optics"))
            self.tissue_scan_pick = None
            self._invalidate_tissue_plan()
            self._refresh_tissue_records()
            self.tissue_scan_status.set("Calibration loaded. Capture boundaries for this tissue.")
        except Exception as exc:
            self._tissue_error(exc)

    def export_tissue_plan(self):
        try:
            plan = self._require_current_tissue_plan()
            path = filedialog.asksaveasfilename(parent=self.tissue_scan_dialog, title="Export Tissue Scan Plan",
                                               defaultextension=".json", filetypes=[("Scan plan", "*.json")])
            if not path:
                return
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"type": "hera_tissue_scan_plan", "version": 1, "coordinate_units": "FOV",
                           "coordinate_orientation": "Live View", "stage_units": "mm", "z_units": "um",
                           "calibration": self.tissue_scan_state, "plan": plan}, handle, indent=2)
            self.tissue_scan_status.set("Plan exported. Use Scan Layout > Save Plan after manual Z updates.")
        except Exception as exc:
            self._tissue_error(exc)

    def _close_tissue_scan_dialog(self):
        dialog = getattr(self, "tissue_scan_dialog", None)
        self.tissue_scan_pick = None
        self.tissue_scan_dialog = None
        if dialog and dialog.winfo_exists():
            dialog.destroy()

    def open_tissue_layout(self):
        window = getattr(self, "tissue_layout_window", None)
        if window and window.winfo_exists():
            self._draw_tissue_layout()
            window.deiconify()
            window.lift()
            return
        window = tk.Toplevel(self)
        self.tissue_layout_window = window
        window.title("Scan Layout")
        window.transient(self)
        window.geometry("630x530")
        window.minsize(480, 380)
        window.protocol("WM_DELETE_WINDOW", self._close_tissue_layout)
        toolbar = tk.Frame(window, padx=12, pady=8)
        toolbar.pack(fill="x")
        tk.Label(toolbar, text="Scan Layout", font=("Segoe UI", 12, "bold")).pack(side="left")
        tk.Button(toolbar, text="Load Plan", command=self.load_tissue_layout_plan).pack(side="right")
        self.tissue_layout_save_button = tk.Button(toolbar, text="Save Plan", command=self.save_tissue_layout_plan)
        self.tissue_layout_save_button.pack(side="right", padx=6)
        actions = tk.Frame(window, padx=12, pady=6)
        actions.pack(side="bottom", fill="x")
        self.tissue_layout_go_button = tk.Button(actions, text="Go To", command=self.goto_tissue_layout_tile)
        self.tissue_layout_go_button.pack(side="left")
        self.tissue_layout_z_button = tk.Button(actions, text="Update Z", command=self.update_tissue_layout_z)
        self.tissue_layout_z_button.pack(side="left", padx=6)
        self.tissue_layout_test_button = tk.Button(actions, text="Run 2x2 Test", command=self.run_tissue_2x2_test)
        self.tissue_layout_test_button.pack(side="left")
        self.tissue_layout_generate_button = tk.Button(actions, text="Generate Sites", command=self.generate_sites_from_tissue_plan)
        self.tissue_layout_generate_button.pack(side="right")
        self.tissue_layout_summary = tk.StringVar(value="No layout loaded")
        tk.Label(window, textvariable=self.tissue_layout_summary, anchor="w").pack(fill="x", padx=12)
        legend = tk.Frame(window)
        legend.pack(fill="x", padx=12, pady=(6, 0))
        for label, color in (("Planned", "muted"), ("Selected", "accent"), ("Active Site", "accent_orange"), ("Current ROI", "success")):
            tk.Label(legend, text=label, fg=self.theme[color]).pack(side="left", padx=(0, 16))
        self.tissue_layout_canvas = tk.Canvas(window, highlightthickness=0)
        self.tissue_layout_canvas.pack(fill="both", expand=True, padx=12, pady=8)
        self.tissue_layout_canvas.bind("<Configure>", lambda _event: self._draw_tissue_layout())
        self.tissue_layout_canvas.bind("<Button-1>", self._select_tissue_layout_tile)
        self.tissue_layout_selection_text = tk.StringVar(value="No tile selected")
        tk.Label(window, textvariable=self.tissue_layout_selection_text, anchor="w", wraplength=450).pack(fill="x", padx=12)
        self.tissue_layout_status = tk.StringVar(value="Waiting for position")
        status = tk.Label(window, textvariable=self.tissue_layout_status, anchor="w", justify="left", wraplength=600)
        status.pack(fill="x", padx=12, pady=(0, 10))
        window.bind("<Configure>", lambda event: status.configure(wraplength=max(300, event.width - 24))
                    if event.widget is window else None, add="+")
        self._apply_theme_recursive(window)
        for label, color in zip(legend.winfo_children(), ("muted", "accent", "accent_orange", "success")):
            label.configure(fg=self.theme[color])
        self._draw_tissue_layout()
        self._poll_tissue_layout()

    def _tissue_layout_records(self):
        plan = getattr(self, "tissue_layout_plan", None)
        if not plan:
            return []
        calibration = FieldCalibration(tuple(plan["field_right_mm"]), tuple(plan["field_down_mm"]))
        references = getattr(self, "tissue_layout_sites", [])
        present = {id(position) for position in self.positions}
        by_name = {position.name: position for position in self.positions}
        records = []
        for i, planned in enumerate(plan["tiles"]):
            record = dict(planned)
            position = references[i] if i < len(references) and id(references[i]) in present else None
            if not references:
                position = by_name.get(planned["name"])
            if position:
                record.update(name=position.name, x=position.x, y=position.y, z=position.z,
                              roi=list(position.roi) if position.roi else None,
                              z_is_real=position.z_is_real)
                record["u"], record["v"] = calibration.project((position.x, position.y), plan["origin"])
            records.append(record)
        return records

    def _draw_tissue_layout(self):
        canvas = getattr(self, "tissue_layout_canvas", None)
        if not canvas or not canvas.winfo_exists():
            return
        canvas.delete("all")
        records = self._tissue_layout_records()
        button_state = "normal" if records else "disabled"
        self.tissue_layout_save_button.configure(state=button_state)
        self.tissue_layout_generate_button.configure(state=button_state)
        if not records:
            self.tissue_layout_drawn_records = []
            self.tissue_layout_cache_key = self._tissue_layout_snapshot_key()
            self.tissue_layout_summary.set("No layout loaded")
            self.tissue_layout_status.set("Load a plan or generate tissue sites first.")
            self._refresh_tissue_layout_selection()
            return
        plan = self.tissue_layout_plan
        width, height = max(canvas.winfo_width(), 100), max(canvas.winfo_height(), 100)
        low_u, high_u = min(t["u"] for t in records) - 0.5, max(t["u"] for t in records) + 0.5
        low_v, high_v = min(t["v"] for t in records) - 0.5, max(t["v"] for t in records) + 0.5
        roi = plan["signature"]["roi"]
        field_w, field_h = self._live_display_dimensions(roi[2], roi[3])
        # Loaded plans keep their own orientation, even if the current Live View differs.
        if plan["signature"]["rotation"] != self._get_live_display_rotation():
            field_w, field_h = (roi[3], roi[2]) if plan["signature"]["rotation"] in (90, 270) else (roi[2], roi[3])
        aspect = field_w / field_h
        scale = min((width - 32) / ((high_u - low_u) * aspect), (height - 32) / (high_v - low_v))
        left = (width - (high_u - low_u) * aspect * scale) / 2
        top = (height - (high_v - low_v) * scale) / 2
        self.tissue_layout_transform = (left, top, scale, aspect, low_u, low_v)
        self.tissue_layout_drawn_records = records
        self.tissue_layout_cache_key = self._tissue_layout_snapshot_key()
        self.tissue_layout_overlay_key = None
        for tile in records:
            canvas.create_rectangle(*self._tissue_layout_point(tile["u"] - 0.5, tile["v"] - 0.5),
                                    *self._tissue_layout_point(tile["u"] + 0.5, tile["v"] + 0.5),
                                    outline=self.theme["muted"], tags="planned")
        self.tissue_layout_summary.set(f"{plan['rows']} rows x {plan['columns']} columns | "
                                       f"{len(records)} tiles | Overlap {plan['overlap_percent']}%")
        self._refresh_tissue_layout_selection()
        self._update_tissue_layout_overlay()

    def _tissue_layout_point(self, u, v):
        left, top, scale, aspect, low_u, low_v = self.tissue_layout_transform
        return left + (u - low_u) * scale * aspect, top + (v - low_v) * scale

    def _tissue_layout_selected_record(self):
        records = getattr(self, "tissue_layout_drawn_records", [])
        if not records:
            raise ValueError("Load or generate a plan first.")
        cell = getattr(self, "tissue_layout_selected_cell", None)
        record = next((t for t in records if (t["row"], t["column"]) == cell), records[0])
        self.tissue_layout_selected_cell = (record["row"], record["column"])
        return record

    def _tissue_layout_position_map(self):
        plan = getattr(self, "tissue_layout_plan", None)
        if not plan:
            raise ValueError("Load or generate a plan first.")
        references = getattr(self, "tissue_layout_sites", [])
        present = {id(p) for p in self.positions}
        by_name = {p.name: p for p in self.positions}
        result = {}
        for index, tile in enumerate(plan["tiles"]):
            if references:
                position = references[index] if index < len(references) else None
                if position is not None and id(position) not in present:
                    position = None
            else:
                position = by_name.get(tile["name"])
            if position is not None:
                result[(tile["row"], tile["column"])] = position
        return result

    def _tissue_layout_position_for_cell(self, cell):
        position = self._tissue_layout_position_map().get(cell)
        if position is not None:
            return position
        raise ValueError("Generate Sites first, or select a tile still present in Saved Sites.")

    def _refresh_tissue_layout_selection(self):
        canvas = self.tissue_layout_canvas
        canvas.delete("selected")
        for button in (self.tissue_layout_go_button, self.tissue_layout_z_button, self.tissue_layout_test_button):
            button.configure(state="disabled")
        try:
            record = self._tissue_layout_selected_record()
        except ValueError:
            self.tissue_layout_selection_text.set("No tile selected")
            return
        canvas.create_rectangle(*self._tissue_layout_point(record["u"] - 0.5, record["v"] - 0.5),
                                *self._tissue_layout_point(record["u"] + 0.5, record["v"] + 0.5),
                                outline=self.theme["accent"], width=2, tags="selected")
        self.tissue_layout_selection_text.set(f"Selected: {record['name']} | X {record['x']:.4f}  "
                                             f"Y {record['y']:.4f} mm | Z {record['z']:.3f} um")
        if getattr(self, "tissue_layout_z_update_busy", False):
            return
        try:
            self._tissue_layout_position_for_cell(self.tissue_layout_selected_cell)
        except ValueError:
            return
        self.tissue_layout_go_button.configure(state="normal")
        self.tissue_layout_z_button.configure(state="normal")
        try:
            select_tissue_test_tiles(self._tissue_layout_available_records(), self.tissue_layout_selected_cell)
            self.tissue_layout_test_button.configure(state="normal")
        except ValueError:
            pass

    def _select_tissue_layout_tile(self, event):
        records = getattr(self, "tissue_layout_drawn_records", [])
        if not records:
            return
        left, top, scale, aspect, low_u, low_v = self.tissue_layout_transform
        u, v = (event.x - left) / (scale * aspect) + low_u, (event.y - top) / scale + low_v
        candidates = [t for t in records if abs(t["u"] - u) <= 0.5 and abs(t["v"] - v) <= 0.5]
        if not candidates:
            return
        tile = min(candidates, key=lambda t: (t["u"] - u) ** 2 + (t["v"] - v) ** 2)
        self.tissue_layout_selected_cell = (tile["row"], tile["column"])
        self._refresh_tissue_layout_selection()

    def _tissue_layout_available_records(self):
        positions = self._tissue_layout_position_map()
        return [record for record in self.tissue_layout_drawn_records if (record["row"], record["column"]) in positions]

    def _tissue_layout_require_idle(self):
        if getattr(self, "tissue_layout_z_update_busy", False) or getattr(self, "tissue_scan_capture_busy", False):
            raise ValueError("Wait for the position read to finish.")
        reason = self._acquisition_busy_reason(include_sdk=False)
        if reason:
            raise ValueError(f"Wait: {reason}.")
        if self.timelapse_thread and self.timelapse_thread.is_alive():
            raise ValueError("Stop the running site sequence before using this action.")

    def goto_tissue_layout_tile(self):
        try:
            self._tissue_layout_require_idle()
            record = self._tissue_layout_selected_record()
            position = self._tissue_layout_position_for_cell((record["row"], record["column"]))
            self.selected_position_index = next(i for i, p in enumerate(self.positions) if p is position)
            self.refresh_positions_tree()
            self._apply_position_roi_to_ui(position)
            self._move_stage_to_saved_position_async(position)
        except Exception as exc:
            messagebox.showerror("Scan Layout", str(exc), parent=self.tissue_layout_window)

    def update_tissue_layout_z(self):
        try:
            self._tissue_layout_require_idle()
            record = self._tissue_layout_selected_record()
            position = self._tissue_layout_position_for_cell((record["row"], record["column"]))
            if not self.tango or not self.tango.connected or not getattr(self, "micro_z_connected", False):
                raise ValueError("Connect the Stage and Z before Update Z.")
            window, plan = self.tissue_layout_window, self.tissue_layout_plan
            snapshot = (position.x, position.y, position.z, position.roi, position.z_is_real)
            tolerance = max(0.0005, min(0.005, 0.02 * min(math.hypot(*plan["field_right_mm"]),
                                                        math.hypot(*plan["field_down_mm"]))))
            self.tissue_layout_z_update_busy = True
            self._refresh_tissue_layout_selection()

            def complete(z, error):
                self.tissue_layout_z_update_busy = False
                if getattr(self, "tissue_layout_window", None) is not window:
                    return
                try:
                    self._tissue_layout_require_idle()
                    if error:
                        raise ValueError(error)
                    if self.tissue_layout_plan is not plan or not any(p is position for p in self.positions) or \
                            (position.x, position.y, position.z, position.roi, position.z_is_real) != snapshot:
                        raise ValueError("The plan or site changed during Update Z. Retry the read.")
                    safety_error = self._micro_z_validate_target_range(z)
                    if safety_error:
                        raise ValueError(safety_error)
                    position.z = z
                    position.z_is_real = True
                    self.refresh_positions_tree()
                    self.log(f"Tissue Scan Plan updated {position.name}: Z={z:.3f} um; XY and ROI unchanged.")
                    self._draw_tissue_layout()
                except Exception as exc:
                    messagebox.showerror("Scan Layout", str(exc), parent=window)
                finally:
                    self._refresh_tissue_layout_selection()

            def worker():
                z, error = None, None
                try:
                    with self.stage_lock:
                        x, y, _, _ = self.tango.get_position()
                    if not all(math.isfinite(value) for value in (x, y)) or math.hypot(x - snapshot[0], y - snapshot[1]) > tolerance:
                        raise ValueError("The Stage is not at the selected tile. Use Go To before Update Z.")
                    z = float(self._get_current_z_or_nan())
                    if not math.isfinite(z):
                        raise ValueError("A real focused Z could not be read. Reconnect Z and retry.")
                    with self.stage_lock:
                        end_x, end_y, _, _ = self.tango.get_position()
                    if not all(math.isfinite(value) for value in (end_x, end_y)) or math.hypot(end_x - x, end_y - y) > 0.0001:
                        raise ValueError("The Stage moved during Update Z. Stop it and retry.")
                except Exception as exc:
                    error = str(exc)
                self._safe_after(0, lambda: complete(z, error))

            threading.Thread(target=worker, daemon=True).start()
        except Exception as exc:
            messagebox.showerror("Scan Layout", str(exc), parent=self.tissue_layout_window)

    def run_tissue_2x2_test(self):
        try:
            self._tissue_layout_require_idle()
            self._tissue_layout_selected_record()
            tiles = select_tissue_test_tiles(self._tissue_layout_available_records(), self.tissue_layout_selected_cell)
            positions = [self._tissue_layout_position_for_cell((tile["row"], tile["column"])) for tile in tiles]
            self.log("Tissue Scan Plan 2x2 test requested: " + ", ".join(p.name for p in positions))
            self.run_one_cycle(positions_override=positions)
        except Exception as exc:
            messagebox.showerror("Scan Layout", str(exc), parent=self.tissue_layout_window)

    def _update_tissue_layout_overlay(self):
        canvas = self.tissue_layout_canvas
        plan = getattr(self, "tissue_layout_plan", None)
        if not plan or not getattr(self, "tissue_layout_drawn_records", None):
            canvas.delete("tracking")
            self.tissue_layout_status.set("Load a plan or generate tissue sites first.")
            return
        site_var = getattr(self, "current_site_var", None)
        state_var = getattr(self, "app_state_var", None)
        site = site_var.get() if site_var else "-"
        state = state_var.get() if state_var else "Ready"
        xy = getattr(self, "latest_stage_xy", None)
        connected = bool(self.tango and self.tango.connected)
        roi = self._capture_current_roi_for_position()
        overlay_key = (site, state, xy, connected, roi, self._get_live_display_rotation())
        if overlay_key == getattr(self, "tissue_layout_overlay_key", None):
            return
        self.tissue_layout_overlay_key = overlay_key
        canvas.delete("tracking")
        active = next((t for t in self.tissue_layout_drawn_records if t["name"] == site), None)
        if active:
            canvas.create_rectangle(*self._tissue_layout_point(active["u"] - 0.5, active["v"] - 0.5),
                                    *self._tissue_layout_point(active["u"] + 0.5, active["v"] + 0.5),
                                    outline=self.theme["accent_orange"], width=3, tags="tracking")
        status = f"Site: {site} | {state}"
        if not connected or not xy:
            self.tissue_layout_status.set(status + "\nStage position unavailable")
            return
        status += f"\nX {xy[0]:.6f}  Y {xy[1]:.6f} mm"
        if not roi or list(roi) != plan["signature"]["roi"] or self._get_live_display_rotation() != plan["signature"]["rotation"]:
            self.tissue_layout_status.set(status + " | ROI/orientation differs from plan")
            return
        calibration = FieldCalibration(tuple(plan["field_right_mm"]), tuple(plan["field_down_mm"]))
        u, v = calibration.project(xy, plan["origin"])
        canvas.create_rectangle(*self._tissue_layout_point(u - 0.5, v - 0.5),
                                *self._tissue_layout_point(u + 0.5, v + 0.5),
                                outline=self.theme["success"], width=2, tags="tracking")
        center_x, center_y = self._tissue_layout_point(u, v)
        canvas.create_oval(center_x - 3, center_y - 3, center_x + 3, center_y + 3,
                           fill=self.theme["success"], outline="", tags="tracking")
        if center_x < 0 or center_y < 0 or center_x > canvas.winfo_width() or center_y > canvas.winfo_height():
            status += " | Outside layout"
        self.tissue_layout_status.set(status)

    def _tissue_layout_snapshot_key(self):
        return (id(getattr(self, "tissue_layout_plan", None)),
                tuple((id(p), p.name, p.x, p.y, p.z) for p in self.positions))

    def _poll_tissue_layout(self):
        window = getattr(self, "tissue_layout_window", None)
        if not window or not window.winfo_exists() or getattr(self, "is_closing", False):
            return
        if window.winfo_ismapped():
            key = self._tissue_layout_snapshot_key()
            if key != getattr(self, "tissue_layout_cache_key", None):
                self._draw_tissue_layout()
            else:
                self._update_tissue_layout_overlay()
        self.tissue_layout_job = self.after(300, self._poll_tissue_layout)

    def load_tissue_layout_plan(self):
        try:
            path = filedialog.askopenfilename(parent=self.tissue_layout_window, title="Load Scan Layout",
                                             filetypes=[("Scan plan", "*.json")])
            if not path:
                return
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            if data.get("type") != "hera_tissue_scan_plan" or data.get("version") != 1:
                raise ValueError("Not a supported Tissue Scan Plan file.")
            plan = validate_tissue_plan(data["plan"])
            self.tissue_layout_plan = plan
            self.tissue_layout_selected_cell = None
            self.tissue_layout_calibration = copy.deepcopy(data.get("calibration", {}))
            self.tissue_layout_sites = []
            self._draw_tissue_layout()
            self.log(f"Tissue Scan layout loaded: {path}")
        except Exception as exc:
            messagebox.showerror("Scan Layout", str(exc), parent=self.tissue_layout_window)

    def generate_sites_from_tissue_plan(self):
        try:
            if getattr(self, "tissue_layout_z_update_busy", False):
                raise ValueError("Wait for Update Z to finish.")
            reason = self._acquisition_busy_reason(include_sdk=False)
            if reason:
                raise ValueError(f"Wait: {reason}.")
            if self.timelapse_thread and self.timelapse_thread.is_alive():
                raise ValueError("Stop the timelapse before replacing Saved Sites.")
            if getattr(self, "tissue_scan_capture_busy", False):
                raise ValueError("Wait for Capture to finish.")
            source = getattr(self, "tissue_layout_plan", None)
            if not source:
                raise ValueError("Load a plan first.")
            plan = validate_tissue_plan(source)
            generated = []
            for tile in plan["tiles"]:
                if not tile.get("z_is_real", True):
                    raise ValueError(f"{tile['name']} has no real saved Z. Refocus it before restoring this plan.")
                error = self._micro_z_validate_target_range(tile["z"])
                if error:
                    raise ValueError(f"{tile['name']}: {error}")
                generated.append(SavedPosition(tile["name"], tile["x"], tile["y"], tile["z"],
                                               tuple(tile["roi"]), z_is_real=True))
            if self.positions and not messagebox.askyesno(
                "Replace Saved Sites", f"Replace {len(self.positions)} Saved Sites with {len(generated)} sites from this plan?",
                parent=self.tissue_layout_window,
            ):
                return
            self.positions = generated
            self.tissue_layout_plan = plan
            self.tissue_layout_sites = list(generated)
            self.selected_position_index = 0
            self.refresh_positions_tree()
            self.timelapse_sites_var.set("all")
            self._draw_tissue_layout()
            self.log(f"Tissue Scan restored {len(generated)} Saved Sites from plan, including XYZ and per-site ROI.")
            messagebox.showinfo("Saved Sites Restored", f"Restored {len(generated)} sites. Check alignment and focus with Go To before Run One Loop.",
                                parent=self.tissue_layout_window)
        except Exception as exc:
            messagebox.showerror("Scan Layout", str(exc), parent=self.tissue_layout_window)

    def save_tissue_layout_plan(self):
        try:
            if getattr(self, "tissue_layout_z_update_busy", False):
                raise ValueError("Wait for Update Z to finish before saving the plan.")
            source = getattr(self, "tissue_layout_plan", None)
            if not source:
                raise ValueError("Load or generate a plan first.")
            plan = copy.deepcopy(source)
            references = getattr(self, "tissue_layout_sites", [])
            if references:
                present = {id(position) for position in self.positions}
                records = self._tissue_layout_records()
                plan["tiles"] = [record for reference, record in zip(references, records) if id(reference) in present]
            plan = validate_tissue_plan(plan)
            path = filedialog.asksaveasfilename(parent=self.tissue_layout_window, title="Save Current Scan Plan",
                                               defaultextension=".json", filetypes=[("Scan plan", "*.json")])
            if not path:
                return
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"type": "hera_tissue_scan_plan", "version": 1, "coordinate_units": "FOV",
                           "coordinate_orientation": "Live View", "stage_units": "mm", "z_units": "um",
                           "calibration": getattr(self, "tissue_layout_calibration", {}), "plan": plan}, handle, indent=2)
            self.log(f"Tissue Scan current layout and Saved Site corrections saved: {path}")
        except Exception as exc:
            messagebox.showerror("Scan Layout", str(exc), parent=self.tissue_layout_window)

    def _close_tissue_layout(self):
        job = getattr(self, "tissue_layout_job", None)
        if job:
            self.after_cancel(job)
        self.tissue_layout_job = None
        window = getattr(self, "tissue_layout_window", None)
        self.tissue_layout_window = None
        if window and window.winfo_exists():
            window.destroy()
