import csv
import math
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from hera_app.controllers import SavedPosition


class StageMixin:
    WAFER_GRID_ROW_COUNTS = (4, 6, 8, 8, 8, 8, 6, 4)

    def apply_stage_motion_settings(self):
        if not self.tango or not self.tango.connected:
            self.log("Connect the stage before applying motion settings.")
            return
        try:
            speed_xy = float(self.stage_speed_var.get())
            if speed_xy <= 0:
                raise RuntimeError("Stage speed must be greater than zero.")
            self.tango.apply_motion_settings(speed_xy=speed_xy, accel_xy=1.0, secure_vel_xy=50.0)
            velocities = self.tango.get_velocity()
            self.log(
                f"Stage motion updated: speedXY={speed_xy:.3f}, "
                f"controllerVel=(X={velocities[0]:.3f}, Y={velocities[1]:.3f})"
            )
        except Exception as exc:
            self.log(f"Failed to apply stage motion settings: {exc}")
            self.update_state("Error")

    def update_stage_position_display(self):
        if self.tango and self.tango.connected:
            try:
                x, y, _, _ = self.tango.get_position()
                self.latest_stage_xy = (x, y)
                self.stage_position_var.set(f"X: {x:.3f}, Y: {y:.3f}")
                self.current_x_label.config(text=f"X: {x:.3f}")
                self.current_y_label.config(text=f"Y: {y:.3f}")
                self._update_live_cursor_readout()
            except Exception:
                pass
        else:
            self.latest_stage_xy = None

    def start_stage_polling(self):
        self._poll_stage_position()

    def _stage_poll_interval_ms(self):
        try:
            if self.timelapse_thread and self.timelapse_thread.is_alive():
                return 1000
        except Exception:
            pass
        return 250

    def _poll_stage_position(self):
        if self.is_closing:
            self.stage_poll_job = None
            return
        self._update_time_remaining()
        if self.tango and self.tango.connected and not getattr(self, "stage_poll_inflight", False):
            self.stage_poll_inflight = True
            def _worker():
                try:
                    with self.stage_lock:
                        x, y, _, _ = self.tango.get_position()
                    def _apply(x=x, y=y):
                        if self.is_closing:
                            return
                        self.latest_stage_xy = (x, y)
                        self.stage_position_var.set(f"X: {x:.3f}, Y: {y:.3f}")
                        self.current_x_label.config(text=f"X: {x:.3f}")
                        self.current_y_label.config(text=f"Y: {y:.3f}")
                        self._update_live_cursor_readout()
                    self._safe_after(0, _apply)
                except Exception:
                    pass
                finally:
                    self.stage_poll_inflight = False
            threading.Thread(target=_worker, daemon=True).start()
        elif not (self.tango and self.tango.connected):
            self.latest_stage_xy = None
            self.stage_poll_inflight = False
        self.stage_poll_job = self._safe_after(self._stage_poll_interval_ms(), self._poll_stage_position)

    def _format_saved_z(self, z):
        if z is None:
            return ""
        try:
            if math.isnan(float(z)):
                return ""
        except Exception:
            return ""
        return f"{float(z):.3f}"

    def _current_cached_z(self):
        z = getattr(self, "z_last_value", None)
        if z is None:
            return math.nan
        return z

    def _get_current_z_or_nan(self):
        """Read Nikon Ti Z synchronously for position saving; return NaN if unavailable."""
        if hasattr(self, "_read_micro_z_for_save"):
            return self._read_micro_z_for_save()
        return math.nan

    def _z_disabled_log_text(self, name):
        return f"Saved dummy Z={self.dummy_z_position:.3f} for {name} because Z control is not connected."

    def _get_position_save_z(self):
        """Use Nikon Ti Z if available; otherwise use a dummy Z so XY sites remain usable."""
        current_z = self._get_current_z_or_nan()
        try:
            if not math.isnan(float(current_z)):
                return float(current_z), False
        except Exception:
            pass
        cached_z = self._current_cached_z()
        try:
            if not math.isnan(float(cached_z)):
                return float(cached_z), False
        except Exception:
            pass
        return float(self.dummy_z_position), True

    def _parse_optional_z(self, text):
        text = text.strip()
        return float(text) if text else float(self.dummy_z_position)

    def _parse_optional_z_with_state(self, text):
        text = text.strip()
        if not text:
            return float(self.dummy_z_position), False
        z = float(text)
        try:
            if (
                abs(z - float(self.dummy_z_position)) <= 1e-9
                and not getattr(self, "micro_z_connected", False)
                and getattr(self, "z_last_value", None) is None
            ):
                return z, False
        except Exception:
            pass
        return z, True

    def _next_site_name(self):
        existing = {pos.name for pos in self.positions}
        n = 1
        while True:
            candidate = f"Site_{n}"
            if candidate not in existing:
                return candidate
            n += 1

    def _is_auto_site_name(self, name):
        text = str(name).strip().lower()
        return text.startswith("site_") and text[5:].isdigit()

    def add_current_position(self):
        try:
            if not self.tango or not self.tango.connected:
                raise RuntimeError("Connect the stage before saving positions.")
            x, y, _, _ = self.tango.get_position()
            requested_name = self.selected_name_var.get().strip()
            if not requested_name and hasattr(self, "position_name_var"):
                requested_name = self.position_name_var.get().strip()
            existing_names = {position.name for position in self.positions}
            if requested_name in existing_names and self._is_auto_site_name(requested_name):
                requested_name = self._next_site_name()
            requested_name = requested_name or self._next_site_name()
            name = self._unique_position_name(requested_name)
            z, used_dummy_z = self._get_position_save_z()
            roi = self._capture_current_roi_for_position()
            self.positions.append(SavedPosition(name, x, y, z, roi, z_is_real=not used_dummy_z))
            self.selected_position_index = len(self.positions) - 1
            self._populate_selected_position_fields(self.positions[self.selected_position_index])
            self.refresh_positions_tree()
            self.log(
                f"Added position {name} at X={x:.3f}, Y={y:.3f}, "
                f"Z={self._format_saved_z(z) or '-'}, ROI={self._format_roi_short(roi)}."
            )
            if used_dummy_z:
                self.log(self._z_disabled_log_text(name))
        except Exception as exc:
            self.log(f"Failed to add position: {exc}")
            self.update_state("Error")

    def refresh_positions_tree(self):
        for item in self.positions_tree.get_children():
            self.positions_tree.delete(item)
        for index, pos in enumerate(self.positions):
            self.positions_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    str(index + 1),
                    pos.name,
                    f"{pos.x:.3f}",
                    f"{pos.y:.3f}",
                    self._format_saved_z(pos.z),
                    "yes" if self._get_position_roi(pos) else "-",
                ),
            )
        if self.selected_position_index is None and self.positions:
            self.selected_position_index = 0
        if self.selected_position_index is not None and 0 <= self.selected_position_index < len(self.positions):
            self.positions_tree.selection_set(str(self.selected_position_index))
            self.positions_tree.focus(str(self.selected_position_index))
            self._populate_selected_position_fields(self.positions[self.selected_position_index])
            self.center_stage_summary_var.set(
                f"Selected position: {self.positions[self.selected_position_index].name}  |  "
                f"X={self.positions[self.selected_position_index].x:.3f}  "
                f"Y={self.positions[self.selected_position_index].y:.3f}  "
                f"Z={self._format_saved_z(self.positions[self.selected_position_index].z) or '-'}  "
                f"ROI={self._format_roi_short(self._get_position_roi(self.positions[self.selected_position_index]))}"
            )
        else:
            self._clear_selected_position_fields()
            self.center_stage_summary_var.set("Selected position: none")

    def export_saved_sites_csv(self):
        try:
            if not self.positions:
                raise RuntimeError("There are no Saved Sites to export.")
            output_dir = self.param_vars.get("output_path").get() if self.param_vars.get("output_path") else self.default_output_dir
            if not os.path.isdir(output_dir):
                output_dir = self.default_output_dir
            csv_path = filedialog.asksaveasfilename(
                title="Export Saved Sites",
                initialdir=output_dir,
                initialfile="wafer_sites.csv",
                defaultextension=".csv",
                filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
            )
            if not csv_path:
                return
            fieldnames = ("Site", "Name", "X", "Y", "Z", "ZIsReal", "ROIX", "ROIY", "ROIW", "ROIH")
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
                writer.writeheader()
                for site_number, position in enumerate(self.positions, start=1):
                    roi = self._get_position_roi(position)
                    roi_values = roi if roi else ("", "", "", "")
                    writer.writerow(
                        {
                            "Site": site_number,
                            "Name": position.name,
                            "X": f"{float(position.x):.9f}",
                            "Y": f"{float(position.y):.9f}",
                            "Z": self._format_saved_z(position.z),
                            "ZIsReal": "1" if bool(getattr(position, "z_is_real", False)) else "0",
                            "ROIX": roi_values[0],
                            "ROIY": roi_values[1],
                            "ROIW": roi_values[2],
                            "ROIH": roi_values[3],
                        }
                    )
            self.log(f"Exported {len(self.positions)} Saved Sites: {csv_path}")
        except Exception as exc:
            self.log(f"Failed to export Saved Sites: {exc}")
            messagebox.showerror("Export Saved Sites", str(exc), parent=self)

    def _csv_float(self, row, key, row_number):
        try:
            value = float(str(row.get(key, "")).strip())
        except Exception as exc:
            raise RuntimeError(f"CSV row {row_number}: invalid {key} value.") from exc
        if not math.isfinite(value):
            raise RuntimeError(f"CSV row {row_number}: {key} must be finite.")
        return value

    def _csv_optional_roi(self, row, row_number):
        keys = ("ROIX", "ROIY", "ROIW", "ROIH")
        values = [str(row.get(key, "")).strip() for key in keys]
        if not any(values):
            return None
        if not all(values):
            raise RuntimeError(f"CSV row {row_number}: ROI requires ROIX, ROIY, ROIW, and ROIH.")
        try:
            roi = tuple(int(value) for value in values)
        except Exception as exc:
            raise RuntimeError(f"CSV row {row_number}: ROI values must be integers.") from exc
        roi = self._normalize_roi_tuple(roi)
        if not roi:
            raise RuntimeError(f"CSV row {row_number}: ROI width and height must be greater than zero.")
        return roi

    def import_saved_sites_csv(self):
        try:
            if getattr(self, "acquisition_inflight", False):
                raise RuntimeError("Wait for the current acquisition to finish before importing Saved Sites.")
            if self.timelapse_thread and self.timelapse_thread.is_alive():
                raise RuntimeError("Stop the timelapse before importing Saved Sites.")
            input_dir = self.param_vars.get("output_path").get() if self.param_vars.get("output_path") else self.default_output_dir
            if not os.path.isdir(input_dir):
                input_dir = self.default_output_dir
            csv_path = filedialog.askopenfilename(
                title="Import Saved Sites",
                initialdir=input_dir,
                filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
            )
            if not csv_path:
                return
            imported = []
            names = set()
            with open(csv_path, "r", newline="", encoding="utf-8-sig") as csv_file:
                reader = csv.DictReader(csv_file)
                required = {"Name", "X", "Y"}
                if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
                    raise RuntimeError("CSV must contain Name, X, and Y columns.")
                for row_number, row in enumerate(reader, start=2):
                    name = str(row.get("Name", "")).strip()
                    if not name:
                        raise RuntimeError(f"CSV row {row_number}: Name is required.")
                    if name in names:
                        raise RuntimeError(f"CSV row {row_number}: duplicate Name '{name}'.")
                    names.add(name)
                    x = self._csv_float(row, "X", row_number)
                    y = self._csv_float(row, "Y", row_number)
                    z_text = str(row.get("Z", "")).strip()
                    if z_text:
                        z = self._csv_float(row, "Z", row_number)
                    else:
                        z = float(self.dummy_z_position)
                    z_is_real = str(row.get("ZIsReal", "0")).strip().lower() in {"1", "true", "yes", "y"}
                    roi = self._csv_optional_roi(row, row_number)
                    imported.append(SavedPosition(name, x, y, z, roi, z_is_real=z_is_real))
            if not imported:
                raise RuntimeError("The selected CSV contains no Saved Sites.")
            if self.positions and not messagebox.askyesno(
                "Replace Saved Sites",
                f"Replace the existing {len(self.positions)} Saved Sites with {len(imported)} imported sites?",
                parent=self,
            ):
                return
            self.positions = imported
            self.selected_position_index = 0
            self.refresh_positions_tree()
            if hasattr(self, "timelapse_sites_var"):
                self.timelapse_sites_var.set("all")
            self.log(f"Imported {len(imported)} Saved Sites: {csv_path}")
        except Exception as exc:
            self.log(f"Failed to import Saved Sites: {exc}")
            messagebox.showerror("Import Saved Sites", str(exc), parent=self)

    def open_wafer_grid_dialog(self):
        existing = getattr(self, "wafer_grid_dialog", None)
        try:
            if existing and existing.winfo_exists():
                existing.lift()
                existing.focus_force()
                return
        except Exception:
            pass

        dialog = tk.Toplevel(self)
        self.wafer_grid_dialog = dialog
        dialog.title("4-inch Wafer Grid")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.protocol("WM_DELETE_WINDOW", self._close_wafer_grid_dialog)

        body = tk.Frame(dialog, padx=10, pady=10)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="Calibration", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 6)
        )
        tk.Label(body, text="Point").grid(row=1, column=0, sticky="w")
        tk.Label(body, text="X").grid(row=1, column=1, sticky="w")
        tk.Label(body, text="Y").grid(row=1, column=2, sticky="w")

        self.wafer_grid_calibration_vars = {}
        for row_index, point_name in enumerate(("R4-C4", "R4-C5", "R5-C4"), start=2):
            x_var = tk.StringVar(value="")
            y_var = tk.StringVar(value="")
            self.wafer_grid_calibration_vars[point_name] = (x_var, y_var)
            tk.Label(body, text=point_name, width=8, anchor="w").grid(row=row_index, column=0, sticky="w", pady=2)
            tk.Entry(body, textvariable=x_var, width=12).grid(row=row_index, column=1, padx=(0, 5), pady=2)
            tk.Entry(body, textvariable=y_var, width=12).grid(row=row_index, column=2, padx=(0, 7), pady=2)
            tk.Button(
                body,
                text="Capture",
                command=lambda name=point_name: self.capture_wafer_grid_calibration_point(name),
                width=8,
            ).grid(row=row_index, column=3, pady=2)

        offset_row = tk.Frame(body)
        offset_row.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(7, 0))
        tk.Label(offset_row, text="Center Offset X").pack(side="left")
        self.wafer_grid_offset_x_var = tk.StringVar(value="-3.938")
        self.wafer_grid_offset_y_var = tk.StringVar(value="-4.071")
        tk.Entry(offset_row, textvariable=self.wafer_grid_offset_x_var, width=9).pack(side="left", padx=(4, 8))
        tk.Label(offset_row, text="Y").pack(side="left")
        tk.Entry(offset_row, textvariable=self.wafer_grid_offset_y_var, width=9).pack(side="left", padx=(4, 0))

        actions = tk.Frame(body)
        actions.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(9, 0))
        tk.Button(actions, text="Generate 52 Sites", command=self.generate_wafer_grid_sites).pack(
            side="left", fill="x", expand=True, padx=(0, 5)
        )
        tk.Button(actions, text="Cancel", command=self._close_wafer_grid_dialog, width=8).pack(side="right")

        self._apply_theme_recursive(dialog)
        dialog.update_idletasks()
        try:
            x = self.winfo_rootx() + max(20, (self.winfo_width() - dialog.winfo_width()) // 2)
            y = self.winfo_rooty() + max(20, (self.winfo_height() - dialog.winfo_height()) // 3)
            dialog.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _close_wafer_grid_dialog(self):
        dialog = getattr(self, "wafer_grid_dialog", None)
        self.wafer_grid_dialog = None
        self.wafer_grid_calibration_vars = {}
        try:
            if dialog and dialog.winfo_exists():
                dialog.destroy()
        except Exception:
            pass

    def capture_wafer_grid_calibration_point(self, point_name):
        try:
            if not self.tango or not self.tango.connected:
                raise RuntimeError("Connect the stage first.")
            variables = self.wafer_grid_calibration_vars.get(point_name)
            if not variables:
                raise RuntimeError(f"Unknown calibration point {point_name}.")
            with self.stage_lock:
                x, y, _, _ = self.tango.get_position()
            variables[0].set(f"{x:.6f}")
            variables[1].set(f"{y:.6f}")
            self.log(f"Captured wafer calibration {point_name}: X={x:.6f}, Y={y:.6f}.")
        except Exception as exc:
            self.log(f"Failed to capture wafer calibration point: {exc}")
            messagebox.showerror("Wafer Grid", str(exc), parent=getattr(self, "wafer_grid_dialog", self))

    def _read_wafer_grid_calibration(self):
        points = {}
        for point_name in ("R4-C4", "R4-C5", "R5-C4"):
            variables = self.wafer_grid_calibration_vars.get(point_name)
            if not variables:
                raise RuntimeError(f"Capture {point_name} first.")
            try:
                points[point_name] = (float(variables[0].get()), float(variables[1].get()))
            except Exception as exc:
                raise RuntimeError(f"Enter or capture valid X/Y coordinates for {point_name}.") from exc
        return points

    def _build_wafer_grid_positions(self, anchor, column_vector, row_vector, z, roi, z_is_real):
        anchor_x, anchor_y = (float(value) for value in anchor)
        column_x, column_y = (float(value) for value in column_vector)
        row_x, row_y = (float(value) for value in row_vector)
        generated = []
        for row_number, column_count in enumerate(self.WAFER_GRID_ROW_COUNTS, start=1):
            columns = range(1, column_count + 1)
            if row_number % 2 == 0:
                columns = reversed(tuple(columns))
            for column_number in columns:
                centered_column = column_number - ((column_count + 1) / 2.0)
                anchor_column = -0.5  # R4-C4 in an eight-chip row.
                column_steps = centered_column - anchor_column
                row_steps = row_number - 4
                x = anchor_x + (column_steps * column_x) + (row_steps * row_x)
                y = anchor_y + (column_steps * column_y) + (row_steps * row_y)
                generated.append(
                    SavedPosition(
                        f"R{row_number:02d}-C{column_number:02d}",
                        x,
                        y,
                        z,
                        roi,
                        z_is_real=z_is_real,
                    )
                )
        return generated

    def generate_wafer_grid_sites(self):
        try:
            if getattr(self, "acquisition_inflight", False):
                raise RuntimeError("Wait for the current acquisition to finish.")
            if self.timelapse_thread and self.timelapse_thread.is_alive():
                raise RuntimeError("Stop the timelapse before replacing Saved Sites.")
            points = self._read_wafer_grid_calibration()
            try:
                offset_x = float(self.wafer_grid_offset_x_var.get())
                offset_y = float(self.wafer_grid_offset_y_var.get())
            except Exception as exc:
                raise RuntimeError("Enter valid Center Offset X/Y values.") from exc
            corner_anchor = points["R4-C4"]
            column_vector = (
                points["R4-C5"][0] - corner_anchor[0],
                points["R4-C5"][1] - corner_anchor[1],
            )
            row_vector = (
                points["R5-C4"][0] - corner_anchor[0],
                points["R5-C4"][1] - corner_anchor[1],
            )
            anchor = (corner_anchor[0] + offset_x, corner_anchor[1] + offset_y)
            column_pitch = math.hypot(*column_vector)
            row_pitch = math.hypot(*row_vector)
            determinant = (column_vector[0] * row_vector[1]) - (column_vector[1] * row_vector[0])
            if column_pitch <= 1e-6 or row_pitch <= 1e-6:
                raise RuntimeError("Calibration points must be at different XY positions.")
            if abs(determinant) <= (column_pitch * row_pitch * 0.01):
                raise RuntimeError("The row and column calibration directions are nearly parallel.")
            if self.positions and not messagebox.askyesno(
                "Replace Saved Sites",
                f"Replace the existing {len(self.positions)} Saved Sites with the 52-chip wafer grid?",
                parent=getattr(self, "wafer_grid_dialog", self),
            ):
                return

            z, used_dummy_z = self._get_position_save_z()
            roi = self._capture_current_roi_for_position()
            generated = self._build_wafer_grid_positions(
                anchor,
                column_vector,
                row_vector,
                z,
                roi,
                z_is_real=not used_dummy_z,
            )
            if len(generated) != 52:
                raise RuntimeError(f"Expected 52 generated sites, got {len(generated)}.")
            self.positions = generated
            self.selected_position_index = 0
            self.refresh_positions_tree()
            if hasattr(self, "timelapse_sites_var"):
                self.timelapse_sites_var.set("all")
            self.log(
                "Generated 52 wafer sites in serpentine order: "
                f"column pitch={column_pitch:.6f}, row pitch={row_pitch:.6f}, "
                f"center offset=({offset_x:.6f}, {offset_y:.6f}), "
                f"ROI={self._format_roi_short(roi)}, initial Z={self._format_saved_z(z) or '-'}; "
                "calibration includes the wafer rotation."
            )
            if used_dummy_z:
                self.log("Wafer sites have dummy Z values. Connect Z and update site focus values before timelapse.")
            else:
                self.log("All generated wafer sites use the current Z as their initial saved focus; update individual sites if the wafer is tilted.")
            self._close_wafer_grid_dialog()
        except Exception as exc:
            self.log(f"Failed to generate wafer grid: {exc}")
            messagebox.showerror("Wafer Grid", str(exc), parent=getattr(self, "wafer_grid_dialog", self))

    def on_position_selected(self, _event=None):
        selection = self.positions_tree.selection()
        if selection:
            self.selected_position_index = int(selection[0])
            position = self.positions[self.selected_position_index]
            self._populate_selected_position_fields(position)
            self._apply_position_roi_to_ui(position)
            if hasattr(self, "micro_z_target_var") and self._format_saved_z(position.z):
                self.micro_z_target_var.set(self._format_saved_z(position.z))
            self.center_stage_summary_var.set(
                f"Selected position: {position.name}  |  X={position.x:.3f}  "
                f"Y={position.y:.3f}  Z={self._format_saved_z(position.z) or '-'}  "
                f"ROI={self._format_roi_short(self._get_position_roi(position))}"
            )
        else:
            self.selected_position_index = None
            self._clear_selected_position_fields()
            self.center_stage_summary_var.set("Selected position: none")

    def _populate_selected_position_fields(self, position):
        self.selected_name_var.set(position.name)
        self.selected_x_var.set(f"{position.x:.3f}")
        self.selected_y_var.set(f"{position.y:.3f}")
        self.selected_z_var.set(self._format_saved_z(position.z))
        if hasattr(self, "micro_z_target_var"):
            self.micro_z_target_var.set(self._format_saved_z(position.z))

    def _clear_selected_position_fields(self):
        self.selected_name_var.set("")
        self.selected_x_var.set("")
        self.selected_y_var.set("")
        self.selected_z_var.set("")
        if hasattr(self, "micro_z_target_var"):
            self.micro_z_target_var.set("")

    def capture_current_stage_position_into_selected(self):
        try:
            if not self.tango or not self.tango.connected:
                raise RuntimeError("Connect the stage before capturing current XYZ.")
            x, y, _, _ = self.tango.get_position()
            z, used_dummy_z = self._get_position_save_z()
            if not self.selected_name_var.get().strip():
                default_name = f"Site_{len(self.positions) + 1}" if self.selected_position_index is None else self.positions[self.selected_position_index].name
                self.selected_name_var.set(default_name)
            self.selected_x_var.set(f"{x:.3f}")
            self.selected_y_var.set(f"{y:.3f}")
            self.selected_z_var.set(self._format_saved_z(z))
            self.log(f"Loaded current stage position into editor: X={x:.3f}, Y={y:.3f}, Z={self._format_saved_z(z) or '-'}")
            if used_dummy_z:
                self.log("Saved dummy Z in the position editor because Z control is not connected.")
        except Exception as exc:
            self.log(f"Failed to capture current stage position: {exc}")
            self.update_state("Error")

    def apply_selected_position_edits(self):
        try:
            raw_name = self.selected_name_var.get().strip()
            name = self._unique_position_name(raw_name, ignore_index=self.selected_position_index)
            if not name:
                raise RuntimeError("Enter a position name first.")
            x = float(self.selected_x_var.get())
            y = float(self.selected_y_var.get())
            z, z_is_real = self._parse_optional_z_with_state(self.selected_z_var.get())
            roi = self._capture_current_roi_for_position()
            if self.selected_position_index is None:
                self.positions.append(SavedPosition(name, x, y, z, roi, z_is_real=z_is_real))
                self.selected_position_index = len(self.positions) - 1
                self.log(
                    f"Added new position {name} at X={x:.3f}, Y={y:.3f}, "
                    f"Z={self._format_saved_z(z) or '-'}, ROI={self._format_roi_short(roi)}."
                )
            else:
                position = self.positions[self.selected_position_index]
                position.name = name
                position.x = x
                position.y = y
                position.z = z
                position.roi = roi
                position.z_is_real = z_is_real
                self.log(
                    f"Saved edits for {name}: X={x:.3f}, Y={y:.3f}, "
                    f"Z={self._format_saved_z(z) or '-'}, ROI={self._format_roi_short(roi)}."
                )
            self._populate_selected_position_fields(self.positions[self.selected_position_index])
            self.refresh_positions_tree()
        except Exception as exc:
            self.log(f"Failed to save selected position edits: {exc}")
            self.update_state("Error")

    def _get_selected_position(self):
        if self.selected_position_index is None or not (0 <= self.selected_position_index < len(self.positions)):
            raise RuntimeError("Select a saved position first.")
        return self.positions[self.selected_position_index]

    def _get_selected_positions(self):
        selected_indices = []
        try:
            selection = self.positions_tree.selection()
        except Exception:
            selection = ()
        for item in selection:
            try:
                index = int(item)
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(self.positions) and index not in selected_indices:
                selected_indices.append(index)
        if not selected_indices:
            return [self._get_selected_position()]
        selected_indices.sort()
        return [self.positions[index] for index in selected_indices]

    def update_selected_position(self):
        try:
            position = self._get_selected_position()
            if not self.tango or not self.tango.connected:
                raise RuntimeError("Connect the stage before updating positions.")
            x, y, _, _ = self.tango.get_position()
            position.x = x
            position.y = y
            position.z, used_dummy_z = self._get_position_save_z()
            position.z_is_real = not used_dummy_z
            position.roi = self._capture_current_roi_for_position()
            self._populate_selected_position_fields(position)
            self.refresh_positions_tree()
            self.log(
                f"Updated {position.name} to X={x:.3f}, Y={y:.3f}, "
                f"Z={self._format_saved_z(position.z) or '-'}, ROI={self._format_roi_short(position.roi)}."
            )
            if used_dummy_z:
                self.log(self._z_disabled_log_text(position.name))
        except Exception as exc:
            self.log(f"Failed to update selected position: {exc}")
            self.update_state("Error")

    def rename_selected_position(self):
        try:
            position = self._get_selected_position()
            new_name = self.selected_name_var.get().strip()
            if not new_name:
                raise RuntimeError("Enter a new position name first.")
            old_name = position.name
            position.name = self._unique_position_name(new_name, ignore_index=self.selected_position_index)
            self._populate_selected_position_fields(position)
            self.refresh_positions_tree()
            self.log(f'Renamed "{old_name}" to "{position.name}".')
        except Exception as exc:
            self.log(f"Failed to rename position: {exc}")
            self.update_state("Error")

    def delete_selected_position(self):
        try:
            selected_indices = []
            try:
                selection = self.positions_tree.selection()
            except Exception:
                selection = ()
            for item in selection:
                try:
                    index = int(item)
                except (TypeError, ValueError):
                    continue
                if 0 <= index < len(self.positions) and index not in selected_indices:
                    selected_indices.append(index)
            if not selected_indices:
                position = self._get_selected_position()
                selected_indices = [self.selected_position_index]
                deleted_names = [position.name]
            else:
                selected_indices.sort()
                deleted_names = [self.positions[index].name for index in selected_indices]
            for index in reversed(selected_indices):
                del self.positions[index]
            self.selected_position_index = None
            self.refresh_positions_tree()
            self.center_stage_summary_var.set("Selected position: none")
            self.log(f"Deleted position(s): {', '.join(deleted_names)}.")
        except Exception as exc:
            self.log(f"Failed to delete position: {exc}")
            self.update_state("Error")

    def _parse_stage_float(self, var, label):
        try:
            return float(var.get())
        except Exception as exc:
            raise RuntimeError(f"Enter a valid {label}.") from exc

    def go_to_stage_xy(self):
        try:
            target_x = self._parse_stage_float(self.xy_target_x_var, "Target X")
            target_y = self._parse_stage_float(self.xy_target_y_var, "Target Y")
        except Exception as exc:
            self.log(f"Go To XY ignored: {exc}")
            self.update_state("Error")
            return
        self._move_stage_to_xy_async(target_x, target_y, f"XY target X={target_x:.3f}, Y={target_y:.3f}")

    def jog_stage_xy(self, direction_x, direction_y):
        if getattr(self, "stage_motion_inflight", False):
            self.log("XY jog ignored because stage motion is still in progress.")
            return
        try:
            step = self._parse_stage_float(self.xy_step_var, "step size")
            if step <= 0:
                raise RuntimeError("Step size must be greater than zero.")
            if not self.tango or not self.tango.connected:
                raise RuntimeError("Connect the stage before moving.")
            with self.stage_lock:
                current_x, current_y, _, _ = self.tango.get_position()
            target_x = current_x + (float(direction_x) * step)
            target_y = current_y + (float(direction_y) * step)
            self.xy_target_x_var.set(f"{target_x:.3f}")
            self.xy_target_y_var.set(f"{target_y:.3f}")
        except Exception as exc:
            self.log(f"XY jog ignored: {exc}")
            self.update_state("Error")
            return
        axis = "X" if direction_x else "Y"
        sign = "+" if (direction_x or direction_y) > 0 else "-"
        self._move_stage_to_xy_async(target_x, target_y, f"{axis}{sign} jog ({step:.3f})")

    def _move_stage_to_xy_async(self, target_x, target_y, label):
        if getattr(self, "stage_motion_inflight", False):
            self.log(f"{label} ignored because stage motion is still in progress.")
            return
        self.stage_motion_inflight = True
        self.stage_motion_stop_requested = False
        self._refresh_run_action_controls()

        def worker():
            try:
                if not self.tango or not self.tango.connected:
                    raise RuntimeError("Connect the stage before moving.")
                with self.stage_lock:
                    speed_xy = float(self.stage_speed_var.get())
                    if speed_xy <= 0:
                        raise RuntimeError("Stage speed must be greater than zero.")
                    self.tango.apply_motion_settings(speed_xy=speed_xy, accel_xy=1.0, secure_vel_xy=50.0)
                    self._log_async(f"Moving stage to {label}.")
                    self.tango.move_absolute_xy(float(target_x), float(target_y))
                    self.tango.wait_for_xy_stop(60000)
                    self._safe_after(0, self.update_stage_position_display)
                if getattr(self, "stage_motion_stop_requested", False):
                    self._log_async("Stage XY motion stopped.")
                else:
                    self._log_async(f"Reached {label}.")
            except Exception as exc:
                self._log_async(f"Stage XY move failed: {exc}")
                self._safe_after(0, lambda: self.update_state("Error"))
            finally:
                self.stage_motion_inflight = False
                self.stage_motion_stop_requested = False
                self._safe_after(0, self._refresh_run_action_controls)

        threading.Thread(target=worker, daemon=True).start()

    def _move_stage_to_saved_position_async(self, position):
        name = str(position.name)
        target_x = float(position.x)
        target_y = float(position.y)
        target_z = None
        has_saved_z = False
        try:
            has_saved_z = bool(self._position_has_real_saved_z(position))
        except Exception:
            try:
                has_saved_z = not math.isnan(float(position.z))
            except Exception:
                has_saved_z = False
        if has_saved_z:
            target_z = float(position.z)

        if getattr(self, "stage_motion_inflight", False):
            self.log(f"{name} ignored because stage motion is still in progress.")
            return
        self.stage_motion_inflight = True
        self.stage_motion_stop_requested = False
        self._refresh_run_action_controls()

        def worker():
            try:
                if not self.tango or not self.tango.connected:
                    raise RuntimeError("Connect the stage before moving.")
                with self.stage_lock:
                    speed_xy = float(self.stage_speed_var.get())
                    if speed_xy <= 0:
                        raise RuntimeError("Stage speed must be greater than zero.")
                    self.tango.apply_motion_settings(speed_xy=speed_xy, accel_xy=1.0, secure_vel_xy=50.0)
                    self._log_async(f"Moving stage to {name}.")
                    self.tango.move_absolute_xy(target_x, target_y)
                    self.tango.wait_for_xy_stop(60000)
                    self._safe_after(0, self.update_stage_position_display)

                if getattr(self, "stage_motion_stop_requested", False):
                    self._log_async("Stage XY motion stopped before saved Z move.")
                    return

                if has_saved_z:
                    if getattr(self, "micro_z_connected", False):
                        self._log_async(f"Moving Z to saved focus for {name}: {target_z:.3f} um.")
                        confirmed_z, z_status = self._move_z_to_position(target_z, label=f"{name} Go To")
                        if z_status == "ok" and confirmed_z is not None:
                            self._log_async(f"Reached {name}: Z={confirmed_z:.3f} um.")
                        else:
                            self._log_async(f"Reached {name} XY, but saved Z move failed: {z_status}.")
                            self._safe_after(0, lambda: self.update_state("Error"))
                    else:
                        self._log_async(f"Reached {name} XY. Connect Z to also move to saved focus.")
                else:
                    self._log_async(f"Reached {name} XY. No saved Z for this site.")
            except Exception as exc:
                self._log_async(f"Stage site move failed: {exc}")
                self._safe_after(0, lambda: self.update_state("Error"))
            finally:
                self.stage_motion_inflight = False
                self.stage_motion_stop_requested = False
                self._safe_after(0, self._refresh_run_action_controls)

        threading.Thread(target=worker, daemon=True).start()

    def stop_stage_xy_motion(self):
        if not self.tango or not self.tango.connected:
            self.log("Connect the stage before stopping XY motion.")
            return
        self.stage_motion_stop_requested = True

        def worker():
            try:
                self.tango.stop_axes()
                self._log_async("Stop XY requested.")
                self._safe_after(0, self.update_stage_position_display)
            except Exception as exc:
                self._log_async(f"Failed to stop XY motion: {exc}")
                self._safe_after(0, lambda: self.update_state("Error"))

        threading.Thread(target=worker, daemon=True).start()

    def goto_selected_position(self):
        try:
            position = self._get_selected_position()
        except Exception as exc:
            self.log(f"Failed to go to selected position: {exc}")
            self.update_state("Error")
            return
        self._move_stage_to_saved_position_async(position)

    def manual_trigger_selected_position(self):
        try:
            position = self._get_selected_position()
        except Exception as exc:
            self.log(f"Manual site run failed: {exc}")
            self.update_state("Error")
            return
        busy_reason = self._acquisition_busy_reason()
        if busy_reason:
            self.log(f"Run selected site ignored because {busy_reason}.")
            return
        if not self._validate_auto_save_export_options():
            return

        def worker():
            try:
                export_path, _, confirmed_z, _ = self.run_stage_site_acquisition(position)
                z_info = f", Z={confirmed_z:.3f} um" if confirmed_z is not None else ""
                self._log_async(f"Manual site run completed for {position.name}{z_info}: {export_path}")
            except Exception as exc:
                self._log_async(f"Manual site run failed: {exc}")
                self._safe_after(0, lambda: self.update_state("Error"))

        threading.Thread(target=worker, daemon=True).start()

