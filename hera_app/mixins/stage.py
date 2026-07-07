import math
import threading

from hera_app.controllers import SavedPosition


class StageMixin:
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
            self.positions.append(SavedPosition(name, x, y, z, roi))
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
            z = self._parse_optional_z(self.selected_z_var.get())
            roi = self._capture_current_roi_for_position()
            if self.selected_position_index is None:
                self.positions.append(SavedPosition(name, x, y, z, roi))
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
        self._move_stage_to_xy_async(position.x, position.y, position.name)

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
                export_path, confirmed_z, _ = self.run_stage_site_acquisition(position)
                z_info = f", Z={confirmed_z:.3f} um" if confirmed_z is not None else ""
                self._log_async(f"Manual site run completed for {position.name}{z_info}: {export_path}")
            except Exception as exc:
                self._log_async(f"Manual site run failed: {exc}")
                self._safe_after(0, lambda: self.update_state("Error"))

        threading.Thread(target=worker, daemon=True).start()

