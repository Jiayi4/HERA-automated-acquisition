import csv
import math
import os
import threading
import time
from datetime import datetime, timedelta


class TimelapseMixin:
    def run_one_cycle(self):
        if self.timelapse_thread and self.timelapse_thread.is_alive():
            self.log("Timelapse is already running.")
            return
        if not self.positions:
            self.log("Add at least one stage position before running a cycle.")
            return

        self.timelapse_stop_event.clear()
        self.timelapse_pause_event.clear()
        self.trigger_log = []
        self.timelapse_started_at = datetime.now()
        self.timelapse_stop_at = None
        self.timelapse_roi = self.selected_export_roi if self.roi_selection_active else None
        self.pause_button.config(text="Pause")
        self.timelapse_status_var.set("Timelapse: running")
        self.update_state("RunningTimelapse")

        self.timelapse_thread = threading.Thread(target=self._timelapse_worker, args=(True,), daemon=True)
        self.timelapse_thread.start()
        if self.timelapse_roi:
            self.log(f"Running one cycle. ROI active for all sites: {self.timelapse_roi}.")
        else:
            self.log("Running one cycle. No ROI active; all sites will acquire the full frame.")

    def start_timelapse(self):
        if self.timelapse_thread and self.timelapse_thread.is_alive():
            self.log("Timelapse is already running.")
            return
        if not self.positions:
            self.log("Add at least one stage position before starting timelapse.")
            return

        interval_min = float(self.interval_var.get())
        if interval_min <= 0:
            self.log("Interval must be greater than zero.")
            return

        self.timelapse_stop_event.clear()
        self.timelapse_pause_event.clear()
        self.trigger_log = []
        self.timelapse_started_at = datetime.now()
        stop_after = float(self.stop_after_var.get())
        self.timelapse_stop_at = self.timelapse_started_at + timedelta(minutes=stop_after) if stop_after > 0 else None
        self.timelapse_roi = self.selected_export_roi if self.roi_selection_active else None
        self.pause_button.config(text="Pause")
        self.timelapse_status_var.set("Timelapse: running")
        self.update_state("RunningTimelapse")

        self.timelapse_thread = threading.Thread(target=self._timelapse_worker, args=(False,), daemon=True)
        self.timelapse_thread.start()
        if self.timelapse_roi:
            self.log(f"Timelapse started. ROI active for all sites: {self.timelapse_roi}.")
        else:
            self.log("Timelapse started. No ROI active; all sites will acquire the full frame.")

    def pause_or_resume_timelapse(self):
        if not self.timelapse_thread or not self.timelapse_thread.is_alive():
            self.log("Timelapse is not running.")
            return
        if self.timelapse_pause_event.is_set():
            self.timelapse_pause_event.clear()
            self.pause_button.config(text="Pause")
            self.timelapse_status_var.set("Timelapse: running")
            self.update_state("RunningTimelapse")
            self.log("Timelapse resumed.")
        else:
            self.timelapse_pause_event.set()
            self.pause_button.config(text="Resume")
            self.timelapse_status_var.set("Timelapse: paused")
            self.update_state("Paused")
            self.log("Timelapse paused.")

    def stop_timelapse(self):
        self.timelapse_stop_event.set()
        self.timelapse_pause_event.clear()
        self.timelapse_roi = None
        self.pause_button.config(text="Pause")
        self.timelapse_status_var.set("Timelapse: stopping")
        self.log("Timelapse stop requested.")

    def _timelapse_worker(self, single_cycle=False):
        cycle = 0
        interval_min = float(self.interval_var.get())
        try:
            if self.flatfield_at_timelapse_start_var.get():
                self._log_async("Acquiring flatfield baseline before timelapse start...")
                tag = self._sanitize_export_tag(f"flatfield_{time.strftime('%Y%m%d_%H%M%S')}")
                self._arm_and_start_acquisition(export_tag=tag, acquisition_role="flatfield")
                self._await_acquisition_completion()
                self._log_async("Flatfield baseline acquired and saved. Starting timelapse cycles.")

            while not self.timelapse_stop_event.is_set():
                if self.timelapse_stop_at and datetime.now() >= self.timelapse_stop_at:
                    self._log_async("Reached requested stop time.")
                    break

                cycle_started_at = datetime.now()
                cycle += 1
                self._set_var_async(self.current_cycle_var, f"Cycle: {cycle}")
                self._log_async(f"Cycle {cycle} started.")
                for position in list(self.positions):
                    if self.timelapse_stop_event.is_set():
                        break
                    self._wait_while_paused()
                    if self.timelapse_stop_event.is_set():
                        break

                    export_path, confirmed_z, z_status = self.run_stage_site_acquisition(position, cycle_index=cycle)
                    x, y, _, _ = self.tango.get_position()
                    self.trigger_log.append(
                        {
                            "Cycle": cycle,
                            "Site": position.name,
                            "X": f"{x:.6f}",
                            "Y": f"{y:.6f}",
                            "Z": f"{confirmed_z:.6f}" if confirmed_z is not None else "",
                            "ZStatus": z_status,
                            "Timestamp": datetime.now().isoformat(timespec="seconds"),
                            "ExportPath": export_path,
                            "Status": "confirmed",
                        }
                    )
                    self._log_async(f"Cycle {cycle}: completed {position.name} -> {export_path}")

                if self.timelapse_stop_event.is_set():
                    break
                if single_cycle:
                    self._log_async("Single cycle complete.")
                    break
                if self.timelapse_stop_at and datetime.now() >= self.timelapse_stop_at:
                    self._log_async("Reached requested stop time.")
                    break

                next_cycle_time = cycle_started_at + timedelta(minutes=interval_min)
                self._log_async(f"Cycle {cycle} complete. Waiting {interval_min:.2f} minutes before next cycle.")
                while datetime.now() < next_cycle_time:
                    if self.timelapse_stop_event.is_set():
                        break
                    self._wait_while_paused()
                    if self.timelapse_stop_at and datetime.now() >= self.timelapse_stop_at:
                        self.timelapse_stop_event.set()
                        break
                    time.sleep(0.25)
        except Exception as exc:
            self._log_async(f"Timelapse failed: {exc}")
            self._safe_after(0, lambda: self.update_state("Error"))
        finally:
            self._write_trigger_log_if_needed()
            self._safe_after(0, self._finish_timelapse)

    def _finish_timelapse(self):
        self.timelapse_stop_event.set()
        self.timelapse_pause_event.clear()
        self.pause_button.config(text="Pause")
        self.timelapse_status_var.set("Timelapse: idle")
        self.time_remaining_var.set("Time remaining: -")
        self.current_cycle_var.set("Cycle: -")
        self.current_site_var.set("Site: -")
        if self.app_state != self.STATE_LABELS["Error"]:
            self.update_state("Ready" if self.controller and self.controller.connected else "Idle")
        self.log("Timelapse stopped.")

    def _write_trigger_log_if_needed(self):
        if not self.trigger_log:
            return
        output_dir = self.param_vars["output_path"].get()
        os.makedirs(output_dir, exist_ok=True)
        log_path = os.path.join(output_dir, f"hera_tango_trigger_log_{time.strftime('%Y%m%d_%H%M%S')}.csv")
        with open(log_path, "w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=["Cycle", "Site", "X", "Y", "Z", "ZStatus", "Timestamp", "ExportPath", "Status"])
            writer.writeheader()
            writer.writerows(self.trigger_log)
        self._log_async(f"Trigger log saved: {log_path}")

    def _wait_while_paused(self):
        while self.timelapse_pause_event.is_set() and not self.timelapse_stop_event.is_set():
            time.sleep(0.1)

    def _update_time_remaining(self):
        if self.timelapse_thread and self.timelapse_thread.is_alive() and self.timelapse_stop_at:
            remaining = self.timelapse_stop_at - datetime.now()
            seconds = max(int(remaining.total_seconds()), 0)
            self.time_remaining_var.set(f"Time remaining: {seconds / 60:.2f} min")
        elif not (self.timelapse_thread and self.timelapse_thread.is_alive()):
            self.time_remaining_var.set("Time remaining: -")

    def run_stage_site_acquisition(self, position, cycle_index=None):
        with self.stage_lock:
            if not self.tango or not self.tango.connected:
                raise RuntimeError("Connect the Tango stage before running a site acquisition.")
            self.apply_stage_motion_settings()
            self.log(f"Moving to {position.name} ...")
            self.tango.move_absolute_xy(position.x, position.y)
            self.tango.wait_for_xy_stop(60000)
            self.update_stage_position_display()
            self._set_var_async(self.current_site_var, f"Site: {position.name}")

            dwell = float(self.stage_dwell_var.get())
            if dwell > 0:
                self.log(f"Settling at {position.name} for {dwell:.1f} seconds.")
                time.sleep(dwell)

        # Move Z after XY is settled. Skip if NIS Z bridge is not active.
        confirmed_z = None
        z_status = "no Z"
        if self.nis_z is not None:
            try:
                target_z = float(position.z)
                if not math.isnan(target_z):
                    self._log_async(f"NIS Z: targeting {target_z:.3f} um for {position.name}...")
                    confirmed_z, z_status = self._move_z_to_position(target_z)
            except (TypeError, ValueError):
                pass

        self.log(f"Starting Hera acquisition at {position.name}.")
        if cycle_index is None:
            export_tag = self._sanitize_export_tag(f"{position.name}_{time.strftime('%Y%m%d_%H%M%S')}")
        else:
            export_tag = self._sanitize_export_tag(f"{position.name}_{cycle_index:03d}")
        self._arm_and_start_acquisition(export_tag=export_tag, forced_roi=self.timelapse_roi)
        export_path = self._await_acquisition_completion()
        return export_path, confirmed_z, z_status
