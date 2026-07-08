import csv
import math
import os
import threading
import time
from datetime import datetime, timedelta


class TimelapseStopped(Exception):
    pass


class TimelapseMixin:
    def _begin_timelapse_run(self):
        self.timelapse_run_id += 1
        return self.timelapse_run_id

    def _roi_plan_message(self, label, positions):
        positions = list(positions)
        saved_count = sum(1 for position in positions if self._get_position_roi(position))
        total = len(positions)
        fallback_roi = self._normalize_roi_tuple(self.timelapse_roi)
        if saved_count and fallback_roi:
            return (
                f"{label}. Using saved ROI for {saved_count}/{total} site(s); "
                f"current ROI fallback for sites without saved ROI: {self._format_roi(fallback_roi)}."
            )
        if saved_count:
            return f"{label}. Using saved ROI for {saved_count}/{total} site(s); sites without ROI acquire full frame."
        if fallback_roi:
            return f"{label}. No per-site ROI saved; using current ROI for all sites: {self._format_roi(fallback_roi)}."
        return f"{label}. No ROI active; all sites will acquire the full frame."

    def select_all_timelapse_sites(self):
        sites_var = getattr(self, "timelapse_sites_var", None)
        if sites_var is not None:
            sites_var.set("all")
        self.log("Timelapse site selection set to all sites.")

    def _timelapse_site_selection_text(self):
        sites_var = getattr(self, "timelapse_sites_var", None)
        if sites_var is None:
            return "all"
        try:
            return str(sites_var.get()).strip()
        except Exception:
            return "all"

    def _parse_timelapse_site_indices(self, text, site_count):
        text = (text or "").strip()
        if not text or text.lower() in {"all", "*"}:
            return list(range(site_count))
        normalized = text.replace(";", ",").replace(" ", ",").replace("\t", ",")
        indices = []
        seen = set()
        invalid = []
        for token in (part.strip() for part in normalized.split(",")):
            if not token:
                continue
            try:
                if "-" in token:
                    start_text, end_text = (part.strip() for part in token.split("-", 1))
                    start = int(start_text)
                    end = int(end_text)
                    step = 1 if end >= start else -1
                    site_numbers = range(start, end + step, step)
                else:
                    site_numbers = (int(token),)
            except ValueError:
                invalid.append(token)
                continue
            for site_number in site_numbers:
                if site_number < 1 or site_number > site_count:
                    invalid.append(str(site_number))
                    continue
                index = site_number - 1
                if index not in seen:
                    seen.add(index)
                    indices.append(index)
        if invalid:
            valid_range = f"1-{site_count}" if site_count else "none"
            raise ValueError(f"Invalid site selection {', '.join(invalid)}. Valid site numbers: {valid_range}.")
        if not indices:
            raise ValueError("No valid sites were selected.")
        return indices

    def _timelapse_selected_positions(self):
        positions = list(self.positions)
        if not positions:
            return []
        indices = self._parse_timelapse_site_indices(self._timelapse_site_selection_text(), len(positions))
        return [positions[index] for index in indices]

    def _timelapse_site_selection_label(self, positions):
        positions = list(positions)
        site_numbers = []
        for selected_position in positions:
            for index, position in enumerate(self.positions):
                if position is selected_position:
                    site_numbers.append(str(index + 1))
                    break
        return ", ".join(site_numbers) if site_numbers else "none"

    def run_one_cycle(self):
        if self.timelapse_thread and self.timelapse_thread.is_alive():
            self.log("Timelapse is already running.")
            return
        try:
            cycle_positions = self._timelapse_selected_positions()
        except Exception as exc:
            self.log(f"Choose valid site numbers before running one loop: {exc}")
            return
        if not cycle_positions:
            self.log("Add at least one stage position before running one loop.")
            return
        if not self._validate_auto_save_export_options():
            return
        if not self._validate_timelapse_z_plan(cycle_positions):
            return

        self.timelapse_stop_event.clear()
        self.timelapse_pause_event.clear()
        self.trigger_log = []
        self.trigger_log_path = ""
        self._begin_trigger_log_file()
        self.timelapse_started_at = datetime.now()
        self.total_run_time_var.set("00:00")
        self.timelapse_stop_at = None
        self.timelapse_roi = self._get_active_roi()
        self.pause_button.config(text="Pause")
        self.timelapse_status_var.set("Timelapse: running")
        self.update_state("RunningTimelapse")

        run_id = self._begin_timelapse_run()
        self.timelapse_thread = threading.Thread(target=self._timelapse_worker, args=(True, cycle_positions, run_id), daemon=True)
        self.timelapse_thread.start()
        site_label = self._timelapse_site_selection_label(cycle_positions)
        self.log(self._roi_plan_message(f"Running one loop for site(s): {site_label}", cycle_positions))
        self.log(self._z_plan_message(f"Running one loop for site(s): {site_label}", cycle_positions))
        self.log(f"Auto-save products: {self._export_selection_text()}.")

    def start_timelapse(self):
        if self.timelapse_thread and self.timelapse_thread.is_alive():
            self.log("Timelapse is already running.")
            return
        try:
            timelapse_positions = self._timelapse_selected_positions()
        except Exception as exc:
            self.log(f"Choose valid site numbers before starting timelapse: {exc}")
            return
        if not timelapse_positions:
            self.log("Add at least one stage position before starting timelapse.")
            return

        interval_min = float(self.interval_var.get())
        if interval_min < 0:
            self.log("Interval must be zero or greater.")
            return
        if not self._validate_auto_save_export_options():
            return
        if not self._validate_timelapse_z_plan(timelapse_positions):
            return

        self.timelapse_stop_event.clear()
        self.timelapse_pause_event.clear()
        self.trigger_log = []
        self.trigger_log_path = ""
        self._begin_trigger_log_file()
        self.timelapse_started_at = datetime.now()
        self.total_run_time_var.set("00:00")
        stop_after = float(self.stop_after_var.get())
        self.timelapse_stop_at = self.timelapse_started_at + timedelta(minutes=stop_after) if stop_after > 0 else None
        self.timelapse_roi = self._get_active_roi()
        self.pause_button.config(text="Pause")
        self.timelapse_status_var.set("Timelapse: running")
        self.update_state("RunningTimelapse")

        run_id = self._begin_timelapse_run()
        self.timelapse_thread = threading.Thread(target=self._timelapse_worker, args=(False, timelapse_positions, run_id), daemon=True)
        self.timelapse_thread.start()
        site_label = self._timelapse_site_selection_label(timelapse_positions)
        self.log(self._roi_plan_message(f"Timelapse started for site(s): {site_label}", timelapse_positions))
        self.log(self._z_plan_message(f"Timelapse started for site(s): {site_label}", timelapse_positions))
        self.log(f"Auto-save products: {self._export_selection_text()}.")

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
        if not self.timelapse_thread or not self.timelapse_thread.is_alive():
            self.timelapse_stop_event.set()
            self.timelapse_pause_event.clear()
            self.timelapse_roi = None
            self.pause_button.config(text="Pause")
            self.timelapse_status_var.set("Timelapse: idle")
            self.log("Timelapse is not running.")
            return

        self.timelapse_stop_event.set()
        self.timelapse_pause_event.clear()
        self.timelapse_roi = None
        self.pause_button.config(text="Pause")
        self.timelapse_status_var.set("Timelapse: stopping")
        self._abort_current_timelapse_acquisition()
        self.log("Timelapse stop requested.")

    def _abort_current_timelapse_acquisition(self, reason="Timelapse stopped by user."):
        aborted = False
        if getattr(self, "hera_service_acquisition_inflight", False):
            client = getattr(self, "hera_service_client", None)
            try:
                self.helper_acquisition_abort_expected = True
                if client:
                    client.kill()
                    self.hera_service_client = None
                self.hera_service_acquisition_inflight = False
                self.helper_acquisition_request_id = None
                self.acquisition_success = False
                self.last_acquisition_error = reason
                self.acquisition_done_event.set()
                self._set_acquisition_inflight(False)
                self._fail_run_progress("Progress: acquisition aborted")
                self._schedule_helper_reconnect()
                self._log_async("Helper service acquisition was killed for timelapse stop/timeout.")
                return True
            except Exception as exc:
                self._log_async(f"Could not kill helper service acquisition during timelapse stop/timeout: {exc}")

        helper_process = getattr(self, "helper_acquisition_process", None)
        if helper_process and helper_process.poll() is None:
            try:
                self.helper_acquisition_abort_expected = True
                helper_process.kill()
                self.helper_acquisition_process = None
                self.acquisition_success = False
                self.last_acquisition_error = reason
                self.acquisition_done_event.set()
                self._set_acquisition_inflight(False)
                self._fail_run_progress("Progress: acquisition aborted")
                self._schedule_helper_reconnect()
                self._log_async("Helper acquisition process was killed for timelapse stop/timeout.")
                return True
            except Exception as exc:
                self._log_async(f"Could not kill helper acquisition process during timelapse stop/timeout: {exc}")

        if not self.controller or not self.controller.connected:
            return aborted
        try:
            if not self.controller.is_acquiring():
                return aborted
            self.controller.abort_hyperspectral_acquisition()
            self.acquisition_success = False
            self.last_acquisition_error = reason
            self.acquisition_done_event.set()
            self._set_acquisition_inflight(False)
            self._log_async("Current Hera acquisition aborted for timelapse stop/timeout.")
            aborted = True
        except Exception as exc:
            self._log_async(f"Could not abort current Hera acquisition during timelapse stop/timeout: {exc}")
        return aborted

    def _start_live_view_for_interval(self):
        if getattr(self, "is_closing", False):
            return

        def request_live_view():
            if getattr(self, "is_closing", False):
                return
            if self.timelapse_stop_event.is_set():
                return
            if getattr(self, "acquisition_inflight", False) or getattr(self, "hera_service_acquisition_inflight", False):
                return
            if not self.controller or not self.controller.connected:
                self.log("Interval wait: reconnecting Hera so live view can run for focus adjustment.")
                self._schedule_helper_reconnect()
                return
            try:
                if self.controller.is_live_capturing():
                    self.log("Interval wait: live view is already running for focus adjustment.", detail=True)
                    return
            except Exception:
                pass
            self.log("Interval wait: starting live view for focus adjustment.")
            self.start_live_view()

        self._safe_after(0, request_live_view)

    def _timelapse_worker(self, single_cycle=False, positions_override=None, run_id=None):
        if run_id is None:
            run_id = self.timelapse_run_id
        cycle = 0
        interval_min = float(self.interval_var.get())
        positions = list(positions_override) if positions_override is not None else list(self.positions)
        try:
            while not self.timelapse_stop_event.is_set():
                if self.timelapse_stop_at and datetime.now() >= self.timelapse_stop_at:
                    self._log_async("Reached requested stop time.")
                    break

                cycle += 1
                self.next_loop_deadline = None
                self._set_var_async(self.next_loop_remaining_var, "-")
                self._set_var_async(self.current_cycle_var, str(cycle))
                self._log_async(f"Cycle {cycle} started.")
                for position in positions:
                    if self.timelapse_stop_event.is_set():
                        break
                    self._wait_while_paused()
                    if self.timelapse_stop_event.is_set():
                        break

                    self._run_site_with_retries(position, cycle)

                if self.timelapse_stop_event.is_set():
                    break
                if single_cycle:
                    self._log_async("Test run complete." if positions_override is not None else "Single cycle complete.")
                    break
                if self.timelapse_stop_at and datetime.now() >= self.timelapse_stop_at:
                    self._log_async("Reached requested stop time.")
                    break

                if interval_min <= 0:
                    self.next_loop_deadline = None
                    self._set_var_async(self.next_loop_remaining_var, "00:00")
                    self._log_async(f"Cycle {cycle} complete. Interval is 0; starting next cycle immediately.")
                else:
                    next_cycle_time = datetime.now() + timedelta(minutes=interval_min)
                    self.next_loop_deadline = next_cycle_time
                    self._start_live_view_for_interval()
                    self._log_async(
                        f"Cycle {cycle} complete. Waiting {interval_min:.2f} minutes from loop completion before next cycle."
                    )
                    while datetime.now() < next_cycle_time:
                        if self.timelapse_stop_event.is_set():
                            break
                        self._wait_while_paused()
                        if self.timelapse_stop_at and datetime.now() >= self.timelapse_stop_at:
                            self.timelapse_stop_event.set()
                            break
                        time.sleep(0.25)
                    self.next_loop_deadline = None
                    self._set_var_async(self.next_loop_remaining_var, "-")
        except TimelapseStopped as exc:
            self._log_async(str(exc) or "Timelapse stopped.")
        except Exception as exc:
            self._log_async(f"Timelapse failed: {exc}")
            self._safe_after(0, lambda: self.update_state("Error"))
        finally:
            self._write_trigger_log_if_needed()
            self._safe_after(0, lambda run_id=run_id: self._finish_timelapse(run_id))

    def _finish_timelapse(self, run_id=None):
        if run_id is not None and run_id != self.timelapse_run_id:
            return
        self.timelapse_stop_event.set()
        self.timelapse_pause_event.clear()
        self.next_loop_deadline = None
        self.pause_button.config(text="Pause")
        self.timelapse_status_var.set("Timelapse: idle")
        self.time_remaining_var.set("Time remaining: -")
        self.next_loop_remaining_var.set("-")
        if getattr(self, "timelapse_started_at", None):
            elapsed = datetime.now() - self.timelapse_started_at
            self.total_run_time_var.set(self._format_countdown_seconds(int(elapsed.total_seconds())))
        self.current_cycle_var.set("-")
        self.current_site_var.set("-")
        if self.app_state != self.STATE_LABELS["Error"]:
            self.update_state("Ready" if self.controller and self.controller.connected else "Idle")
        if not getattr(self, "is_closing", False) and not (self.controller and self.controller.connected):
            self.log("Reconnecting Hera after helper timelapse.")
            self._schedule_helper_reconnect()
        self.log("Timelapse stopped.")

    def _write_trigger_log_if_needed(self):
        if not self.trigger_log:
            return
        if getattr(self, "trigger_log_path", ""):
            self._log_async(f"Trigger log saved: {self.trigger_log_path}")
            return
        output_dir = self.param_vars["output_path"].get()
        os.makedirs(output_dir, exist_ok=True)
        log_path = os.path.join(output_dir, f"hera_tango_trigger_log_{time.strftime('%Y%m%d_%H%M%S')}.csv")
        with open(log_path, "w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=self._trigger_log_fieldnames())
            writer.writeheader()
            writer.writerows(self.trigger_log)
        self._log_async(f"Trigger log saved: {log_path}")

    def _trigger_log_fieldnames(self):
        return [
            "Cycle",
            "Site",
            "Attempt",
            "X",
            "Y",
            "TargetZ",
            "Z",
            "ZDelta",
            "ZStatus",
            "Timestamp",
            "ExportPath",
            "ROI",
            "Status",
            "Error",
        ]

    def _begin_trigger_log_file(self):
        try:
            output_dir = self.param_vars["output_path"].get()
            os.makedirs(output_dir, exist_ok=True)
            self.trigger_log_path = os.path.join(output_dir, f"hera_tango_trigger_log_{time.strftime('%Y%m%d_%H%M%S')}.csv")
            with open(self.trigger_log_path, "w", newline="", encoding="utf-8") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=self._trigger_log_fieldnames())
                writer.writeheader()
            self._log_async(f"Trigger log started: {self.trigger_log_path}")
        except Exception as exc:
            self.trigger_log_path = ""
            self._log_async(f"Could not start trigger log file: {exc}")

    def _record_trigger_log_entry(self, entry):
        fieldnames = self._trigger_log_fieldnames()
        row = {field: entry.get(field, "") for field in fieldnames}
        self.trigger_log.append(row)
        if not getattr(self, "trigger_log_path", ""):
            self._begin_trigger_log_file()
        if not getattr(self, "trigger_log_path", ""):
            return
        try:
            with open(self.trigger_log_path, "a", newline="", encoding="utf-8") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
                writer.writerow(row)
        except Exception as exc:
            self._log_async(f"Could not append trigger log entry: {exc}")

    def _timelapse_site_retry_count(self):
        retries_var = getattr(self, "timelapse_site_retries_var", None)
        try:
            retries = int(retries_var.get()) if retries_var is not None else 1
        except Exception:
            retries = 1
        return max(0, retries)

    def _current_stage_xy_strings(self):
        try:
            if self.tango and self.tango.connected:
                x, y, _, _ = self.tango.get_position()
                return f"{x:.6f}", f"{y:.6f}"
        except Exception:
            pass
        return "", ""

    def _run_site_with_retries(self, position, cycle_index):
        attempts = self._timelapse_site_retry_count() + 1
        last_error = ""
        for attempt in range(1, attempts + 1):
            if self.timelapse_stop_event.is_set():
                raise TimelapseStopped("Timelapse stopped before site acquisition.")
            try:
                if attempt > 1:
                    self._log_async(f"Retrying {position.name} (attempt {attempt}/{attempts})...")
                export_path, target_z, confirmed_z, z_status = self.run_stage_site_acquisition(position, cycle_index=cycle_index)
                if self.timelapse_stop_event.is_set():
                    raise TimelapseStopped("Timelapse stopped by user.")
                x, y = self._current_stage_xy_strings()
                z_delta = confirmed_z - target_z if confirmed_z is not None and target_z is not None else None
                self._record_trigger_log_entry(
                    {
                        "Cycle": cycle_index,
                        "Site": position.name,
                        "Attempt": attempt,
                        "X": x,
                        "Y": y,
                        "TargetZ": f"{target_z:.6f}" if target_z is not None else "",
                        "Z": f"{confirmed_z:.6f}" if confirmed_z is not None else "",
                        "ZDelta": f"{z_delta:.6f}" if z_delta is not None else "",
                        "ZStatus": z_status,
                        "Timestamp": datetime.now().isoformat(timespec="seconds"),
                        "ExportPath": export_path,
                        "ROI": self._format_roi_short(self._get_position_roi(position) or self.timelapse_roi),
                        "Status": "confirmed",
                        "Error": "",
                    }
                )
                self._log_async(f"Cycle {cycle_index}: completed {position.name} -> {export_path}")
                return True
            except TimelapseStopped:
                raise
            except Exception as exc:
                last_error = str(exc)
                self._log_async(f"Cycle {cycle_index}: {position.name} attempt {attempt}/{attempts} failed: {last_error}")
                self._safe_after(0, lambda: self.update_state("RunningTimelapse"))
                if attempt < attempts and not self.timelapse_stop_event.is_set():
                    time.sleep(2.0)

        x, y = self._current_stage_xy_strings()
        self._record_trigger_log_entry(
            {
                "Cycle": cycle_index,
                "Site": position.name,
                "Attempt": attempts,
                "X": x,
                "Y": y,
                "Z": "",
                "ZStatus": "failed",
                "Timestamp": datetime.now().isoformat(timespec="seconds"),
                "ExportPath": "",
                "ROI": self._format_roi_short(self._get_position_roi(position) or self.timelapse_roi),
                "Status": "failed",
                "Error": last_error,
            }
        )
        self._log_async(f"Cycle {cycle_index}: skipped {position.name} after {attempts} failed attempt(s).")
        return False

    def _wait_while_paused(self):
        while self.timelapse_pause_event.is_set() and not self.timelapse_stop_event.is_set():
            time.sleep(0.1)

    def _timelapse_acquisition_timeout_sec(self, requested_timeout=None):
        candidates = []
        for value in (
            requested_timeout,
            getattr(self, "helper_process_timeout_sec", None),
            getattr(self, "helper_acquisition_timeout_sec", None),
            600,
        ):
            try:
                if value is not None:
                    candidates.append(float(value))
            except Exception:
                pass
        return max(candidates or [600.0]) + 60.0

    def _await_timelapse_acquisition_completion(self, timeout_sec=None):
        timeout_sec = self._timelapse_acquisition_timeout_sec(timeout_sec)
        deadline = time.time() + timeout_sec
        abort_requested = False
        while time.time() < deadline:
            if self.acquisition_done_event.wait(timeout=0.25):
                break
            if self.timelapse_stop_event.is_set() and not abort_requested:
                abort_requested = True
                self._abort_current_timelapse_acquisition()
        else:
            reason = f"Timed out waiting for Hera acquisition to complete after {timeout_sec:.0f} s."
            self._log_async(reason)
            self._abort_current_timelapse_acquisition(reason=reason)
            self.acquisition_success = False
            self.last_acquisition_error = reason
            self.acquisition_done_event.set()
            raise RuntimeError(reason)

        if self.timelapse_stop_event.is_set() and not self.acquisition_success:
            raise TimelapseStopped("Timelapse stopped by user.")
        if not self.acquisition_success:
            raise RuntimeError(self.last_acquisition_error or "Hera acquisition failed.")
        return self.last_export_path

    def _update_time_remaining(self):
        if self.timelapse_thread and self.timelapse_thread.is_alive() and getattr(self, "timelapse_started_at", None):
            elapsed = datetime.now() - self.timelapse_started_at
            self.total_run_time_var.set(self._format_countdown_seconds(int(elapsed.total_seconds())))
        if self.timelapse_thread and self.timelapse_thread.is_alive() and self.timelapse_stop_at:
            remaining = self.timelapse_stop_at - datetime.now()
            seconds = max(int(remaining.total_seconds()), 0)
            self.time_remaining_var.set(f"Time remaining: {seconds / 60:.2f} min")
        elif not (self.timelapse_thread and self.timelapse_thread.is_alive()):
            self.time_remaining_var.set("Time remaining: -")
        next_loop_deadline = getattr(self, "next_loop_deadline", None)
        if self.timelapse_thread and self.timelapse_thread.is_alive() and next_loop_deadline:
            remaining = next_loop_deadline - datetime.now()
            seconds = max(int(math.ceil(remaining.total_seconds())), 0)
            self.next_loop_remaining_var.set(self._format_countdown_seconds(seconds))
        elif not (self.timelapse_thread and self.timelapse_thread.is_alive()) or not next_loop_deadline:
            self.next_loop_remaining_var.set("-")

    def _format_countdown_seconds(self, seconds):
        seconds = max(0, int(seconds))
        minutes, sec = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{sec:02d}"
        return f"{minutes:02d}:{sec:02d}"

    def _timelapse_saved_z_enabled(self):
        return bool(getattr(self, "timelapse_z_motion_enabled", False))

    def _position_saved_z_value(self, position):
        try:
            target_z = float(position.z)
        except (TypeError, ValueError):
            return None
        if math.isnan(target_z):
            return None
        return target_z

    def _position_has_real_saved_z(self, position):
        target_z = self._position_saved_z_value(position)
        if target_z is None:
            return False
        if getattr(position, "z_is_real", False):
            return True
        try:
            dummy_z = float(getattr(self, "dummy_z_position", 0.0))
            if abs(target_z - dummy_z) <= 1e-9:
                return False
        except Exception:
            pass
        return True

    def _z_plan_message(self, label, positions):
        positions = list(positions)
        if not self._timelapse_saved_z_enabled():
            return f"{label}. Saved Z auto-move is off; acquisitions will move XY only."
        real_z_count = sum(1 for position in positions if self._position_has_real_saved_z(position))
        return f"{label}. Using saved Z for {real_z_count}/{len(positions)} site(s)."

    def _validate_timelapse_z_plan(self, positions):
        positions = list(positions)
        if not self._timelapse_saved_z_enabled():
            return True
        if not getattr(self, "micro_z_connected", False):
            self.log("Connect Z before running a site sequence; saved Z movement is always enabled.")
            return False
        missing = [position.name for position in positions if not self._position_has_real_saved_z(position)]
        if missing:
            self.log(
                "Saved Z movement is enabled, but these site(s) do not have a real saved Z: "
                + ", ".join(missing)
                + ". Connect Z and update those sites before running."
            )
            return False
        range_errors = []
        for position in positions:
            target_z = self._position_saved_z_value(position)
            if target_z is None:
                continue
            try:
                range_error = self._micro_z_validate_target_range(target_z)
            except Exception as exc:
                range_error = str(exc)
            if range_error:
                range_errors.append(f"{position.name}: {range_error}")
        if range_errors:
            self.log("Saved Z safety check failed: " + "; ".join(range_errors))
            return False
        return True

    def _timelapse_site_z_target(self, position):
        if not self._timelapse_saved_z_enabled():
            return None, "Z auto-move disabled"
        target_z = self._position_saved_z_value(position)
        if target_z is None or not self._position_has_real_saved_z(position):
            return None, "no saved Z"
        try:
            range_error = self._micro_z_validate_target_range(target_z)
        except Exception as exc:
            range_error = str(exc)
        if range_error:
            return None, f"saved Z rejected: {range_error}"
        if not getattr(self, "micro_z_connected", False) or getattr(self, "z_last_value", None) is None:
            return None, "Z skipped: Micro-Manager Z not connected"
        if str(getattr(self, "z_last_status", "")).lower() != "ok":
            return None, f"Z skipped: {self.z_last_status}"
        return target_z, "pending"

    def run_stage_site_acquisition(self, position, cycle_index=None):
        with self.stage_lock:
            if not self.tango or not self.tango.connected:
                raise RuntimeError("Connect the Tango stage before running a site acquisition.")
            self.apply_stage_motion_settings()
            self.log(f"Moving to {position.name} ...")
            self.tango.move_absolute_xy(position.x, position.y)
            self.tango.wait_for_xy_stop(60000)
            self.update_stage_position_display()
            self._set_var_async(self.current_site_var, position.name)

        if self.timelapse_stop_event.is_set():
            raise TimelapseStopped("Timelapse stopped before acquisition.")

        confirmed_z = None
        z_status = "no Z"
        target_z, z_status = self._timelapse_site_z_target(position)
        if target_z is not None:
            self._log_async(f"Micro-Manager Z targeting {target_z:.3f} um for {position.name}...")
            confirmed_z, z_status = self._move_z_to_position(target_z, label=f"{position.name} cycle {cycle_index or '-'}")
            if z_status != "ok":
                raise RuntimeError(f"Could not move Z for {position.name}: {z_status}")
        elif self._timelapse_saved_z_enabled():
            raise RuntimeError(f"Could not move Z for {position.name}: {z_status}")
        elif z_status not in ("no Z", "no saved Z", "Z auto-move disabled"):
            self._log_async(f"{z_status} for {position.name}; starting Hera acquisition without Z move.")

        if self.timelapse_stop_event.is_set():
            raise TimelapseStopped("Timelapse stopped before acquisition.")

        dwell = float(self.stage_dwell_var.get())
        if dwell > 0:
            self.log(f"Settling at {position.name} for {dwell:.1f} seconds after XY/Z move.")
            time.sleep(dwell)

        self.log(f"Starting Hera acquisition at {position.name}.")
        if cycle_index is None:
            export_tag = self._sanitize_export_tag(f"{position.name}_{time.strftime('%Y%m%d_%H%M%S')}")
        else:
            export_tag = self._sanitize_export_tag(f"{position.name}_{cycle_index:03d}")
        site_roi = self._get_position_roi(position) or self.timelapse_roi
        if site_roi:
            self.log(f"Using ROI for {position.name}: {self._format_roi(site_roi)}.")
        else:
            self.log(f"No ROI saved for {position.name}; acquiring full frame.")
        self._arm_and_start_acquisition(export_tag=export_tag, forced_roi=site_roi)
        export_path = self._await_timelapse_acquisition_completion()
        return export_path, target_z, confirmed_z, z_status
