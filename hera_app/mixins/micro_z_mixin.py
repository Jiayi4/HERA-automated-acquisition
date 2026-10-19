import math
import threading

from hera_app.controllers import MicroManagerZController
from hera_app.safety import HardwareSafetyError, ZMotionCancelled, finite_float


class MicroManagerZMixin:
    def _get_micro_z_controller(self):
        mm_path = self.micro_z_mm_path_var.get().strip() or MicroManagerZController.DEFAULT_MM_PATH
        config_path = self.micro_z_config_var.get().strip() or MicroManagerZController.DEFAULT_CONFIG_PATH
        device_label = self.micro_z_device_var.get().strip() or MicroManagerZController.DEFAULT_DEVICE
        controller = getattr(self, "micro_z", None)
        if (
            controller is None
            or controller.mm_path != mm_path
            or controller.config_path != config_path
            or controller.device_label != device_label
        ):
            if controller is not None:
                try:
                    controller.disconnect()
                except Exception:
                    pass
            self.micro_z = MicroManagerZController(mm_path, config_path, device_label)
        return self.micro_z

    def _set_micro_z_value(self, z, status="ok"):
        self.z_last_value = finite_float(z, "Z readback")
        self.z_last_status = status
        self.micro_z_current_z_var.set(f"Z: {float(z):.3f} um")
        self.micro_z_status_var.set(f"Z: {float(z):.3f} um")
        if hasattr(self, "selected_z_var") and not self.selected_z_var.get().strip():
            self.selected_z_var.set(f"{float(z):.3f}")
        self.update_stage_position_display()

    def _set_micro_z_status(self, status):
        self.z_last_status = str(status)
        if self.z_last_value is None:
            self.micro_z_current_z_var.set(f"Z: {status}")
        self.micro_z_status_var.set(f"Z: {status}")

    def _micro_z_optional_float_setting(self, var_name, label):
        var = getattr(self, var_name, None)
        if var is None:
            return None
        text = str(var.get()).strip()
        if not text:
            return None
        try:
            return finite_float(text, label)
        except Exception:
            raise RuntimeError(f"{label} must be a number or blank.")

    def _micro_z_validate_target_range(self, target_z):
        try:
            target_z = finite_float(target_z, "Target Z")
        except HardwareSafetyError as exc:
            return str(exc)
        min_z = self._micro_z_optional_float_setting("micro_z_min_var", "Z min")
        max_z = self._micro_z_optional_float_setting("micro_z_max_var", "Z max")
        if min_z is not None and max_z is not None and min_z > max_z:
            return f"Z min ({min_z:.3f} um) must be <= Z max ({max_z:.3f} um)."
        if min_z is not None and target_z < min_z:
            return f"target Z {target_z:.3f} um is below Z min {min_z:.3f} um."
        if max_z is not None and target_z > max_z:
            return f"target Z {target_z:.3f} um is above Z max {max_z:.3f} um."
        return None

    def _micro_z_validate_move_safety(self, target_z, current_z=None):
        range_error = self._micro_z_validate_target_range(target_z)
        if range_error:
            return range_error
        if current_z is None:
            return None
        try:
            current_z = finite_float(current_z, "Current Z")
        except HardwareSafetyError as exc:
            return str(exc)
        max_jump = self._micro_z_optional_float_setting("micro_z_max_jump_var", "Max Z jump")
        if max_jump is None:
            return None
        if max_jump <= 0:
            return "Max Z jump must be greater than 0 um or blank."
        jump = abs(float(target_z) - float(current_z))
        if jump > max_jump:
            return (
                f"Z jump {jump:.3f} um exceeds Max Jump {max_jump:.3f} um "
                f"(current {float(current_z):.3f} um, target {float(target_z):.3f} um)."
            )
        return None

    def _log_micro_z_motion_result(self, label, target_z, confirmed_z):
        delta = float(confirmed_z) - float(target_z)
        confirmation = getattr(getattr(self, "micro_z", None), "last_move_confirmation", None)
        note = f" Arrival: {confirmation}." if isinstance(confirmation, str) else ""
        self._log_async(
            f"{label}: target Z={float(target_z):.3f} um, "
            f"confirmed Z={float(confirmed_z):.3f} um, delta={delta:+.3f} um.{note}"
        )

    def toggle_micro_z_connection(self):
        if getattr(self, "micro_z_connected", False):
            self.disconnect_micro_z_async()
        else:
            self.connect_micro_z_async()

    def connect_micro_z_async(self):
        if self.micro_z_request_lock.locked():
            self.log("Z connect ignored because another Z request is active.")
            return
        self._refresh_run_action_controls()
        self._set_micro_z_status("connecting")

        def worker():
            with self.micro_z_request_lock:
                try:
                    z_controller = self._get_micro_z_controller()
                    z_controller.connect()
                    self.micro_z_connected = True
                    z = z_controller.get_z()
                    self._safe_after(0, lambda z=z: self._set_micro_z_value(z))
                    self._log_async(f"Micro-Manager Z connected on {z_controller.device_label}: {z:.3f} um.")
                    self._safe_after(0, self.start_micro_z_polling)
                except Exception as exc:
                    self.micro_z_connected = False
                    self._log_async(f"Micro-Manager Z connect failed: {exc}")
                    self._safe_after(0, lambda exc=exc: self._set_micro_z_status(f"connect failed: {exc}"))
                finally:
                    self._safe_after(0, self._refresh_run_action_controls)

        threading.Thread(target=worker, daemon=True).start()

    def disconnect_micro_z_async(self):
        if self.micro_z_request_lock.locked():
            self.log("Z disconnect ignored because another Z request is active.")
            return
        self._refresh_run_action_controls()
        self._set_micro_z_status("disconnecting")

        def worker():
            with self.micro_z_request_lock:
                try:
                    if self.micro_z is not None:
                        self.micro_z.disconnect()
                    self.micro_z_connected = False
                    self.z_last_value = None
                    self.z_last_status = "disconnected"
                    self._safe_after(0, lambda: self.micro_z_current_z_var.set("Z: disconnected"))
                    self._safe_after(0, lambda: self.micro_z_status_var.set("Z: disconnected"))
                    self._log_async("Micro-Manager Z disconnected.")
                except Exception as exc:
                    self._log_async(f"Micro-Manager Z disconnect failed: {exc}")
                finally:
                    self._safe_after(0, self._refresh_run_action_controls)

        threading.Thread(target=worker, daemon=True).start()

    def _micro_z_get(self):
        if self.micro_z_request_lock.locked():
            self._log_async("Z read ignored because another Z request is active.")
            return
        self._refresh_run_action_controls()
        self._set_var_async(self.micro_z_status_var, "Z: reading")

        def worker():
            with self.micro_z_request_lock:
                try:
                    z = self._get_micro_z_controller().get_z()
                    self.micro_z_connected = True
                    self._safe_after(0, lambda z=z: self._set_micro_z_value(z))
                    self._log_async(f"Micro-Manager Z read: {z:.3f} um.")
                except Exception as exc:
                    self.micro_z_connected = False
                    self._log_async(f"Micro-Manager Z read failed: {exc}")
                    self._safe_after(0, lambda exc=exc: self._set_micro_z_status(f"read failed: {exc}"))
                finally:
                    self._safe_after(0, self._refresh_run_action_controls)

        threading.Thread(target=worker, daemon=True).start()

    def _micro_z_move_abs_from_target(self):
        try:
            target_z = float(self.micro_z_target_var.get())
            safety_error = self._micro_z_validate_target_range(target_z)
            if safety_error:
                raise RuntimeError(safety_error)
        except Exception as exc:
            self.log(f"Go To Z ignored: enter a valid and safe target Z. ({exc})")
            return
        self._micro_z_move_abs(target_z)

    def _micro_z_move_abs(self, target_z):
        if self.micro_z_request_lock.locked():
            self._log_async("Z move ignored because another Z request is active.")
            return
        self._refresh_run_action_controls()
        self._set_var_async(self.micro_z_status_var, f"Z: moving to {target_z:.3f}")
        generation = getattr(self, "micro_z_stop_generation", 0)

        def worker():
            with self.micro_z_request_lock:
                try:
                    z = self._checked_micro_z_move(target_z, generation)
                    self.micro_z_connected = True
                    self._safe_after(0, lambda z=z: self._set_micro_z_value(z))
                    self._log_micro_z_motion_result("Manual Z move", target_z, z)
                except Exception as exc:
                    self._log_async(f"Micro-Manager Z move to {target_z:.3f} um failed: {exc}")
                    self._safe_after(0, lambda exc=exc: self._set_micro_z_status(f"move failed: {exc}"))
                finally:
                    self._safe_after(0, self._refresh_run_action_controls)

        threading.Thread(target=worker, daemon=True).start()

    def _micro_z_move_rel(self, dz):
        if self.micro_z_request_lock.locked():
            self._log_async("Z jog ignored because another Z request is active.")
            return
        self._refresh_run_action_controls()
        self._set_var_async(self.micro_z_status_var, f"Z: moving {dz:+.3f}")
        generation = getattr(self, "micro_z_stop_generation", 0)

        def worker():
            with self.micro_z_request_lock:
                try:
                    z_controller = self._get_micro_z_controller()
                    current_z = finite_float(z_controller.get_z(), "Current Z")
                    target_z = current_z + finite_float(dz, "Z step")
                    z = self._checked_micro_z_move(target_z, generation)
                    self.micro_z_connected = True
                    self._safe_after(0, lambda z=z: self._set_micro_z_value(z))
                    self._log_micro_z_motion_result(f"Manual Z jog {dz:+.3f} um", target_z, z)
                except Exception as exc:
                    self._log_async(f"Micro-Manager Z jog {dz:+.3f} um failed: {exc}")
                    self._safe_after(0, lambda exc=exc: self._set_micro_z_status(f"jog failed: {exc}"))
                finally:
                    self._safe_after(0, self._refresh_run_action_controls)

        threading.Thread(target=worker, daemon=True).start()

    def _micro_z_move_step(self, sign):
        try:
            step = abs(finite_float(self.micro_z_step_var.get(), "Z step"))
            if step <= 0:
                raise RuntimeError("step must be greater than zero")
        except Exception as exc:
            self.log(f"Z jog ignored: enter a valid step. ({exc})")
            return
        self._micro_z_move_rel(float(sign) * step)

    def _micro_z_stop(self):
        self.micro_z_stop_generation = getattr(self, "micro_z_stop_generation", 0) + 1
        controller = getattr(self, "micro_z", None)

        def worker():
            try:
                if controller is None:
                    raise HardwareSafetyError("Z is not connected.")
                # Stop must not wait behind a move holding the UI request lock.
                z = controller.stop()
                observed_only = controller.last_stop_confirmation == "NikonTI position stationary (hardware Stop unsupported)"
                status = "stationary" if observed_only else "stopped"
                self._safe_after(0, lambda z=z, status=status: self._set_micro_z_value(z, status=status))
                if observed_only:
                    self._log_async(
                        f"Micro-Manager Z stationary: {z:.3f} um by stable position readback. "
                        "NikonTI hardware Stop is unsupported; pending acquisition was cancelled, "
                        "but no hardware braking command was available."
                    )
                else:
                    self._log_async(f"Micro-Manager Z stop confirmed: {z:.3f} um.")
            except Exception as exc:
                self._log_async(f"Micro-Manager Z stop failed: {exc}")
                self._safe_after(0, lambda exc=exc: self._set_micro_z_status(f"stop unconfirmed: {exc}"))
            finally:
                self._safe_after(0, self._refresh_run_action_controls)

        threading.Thread(target=worker, daemon=True).start()

    def _checked_micro_z_move(self, target_z, generation, skip_if_within_tolerance=False):
        target_z = finite_float(target_z, "Target Z")
        tolerance = finite_float(self.micro_z_tolerance_var.get(), "Z tolerance")
        if tolerance <= 0:
            raise HardwareSafetyError("Z tolerance must be greater than zero.")
        controller = self._get_micro_z_controller()
        current_z = finite_float(controller.get_z(), "Current Z")
        safety_error = self._micro_z_validate_move_safety(target_z, current_z)
        if safety_error:
            raise HardwareSafetyError(safety_error)
        if generation != getattr(self, "micro_z_stop_generation", 0):
            raise ZMotionCancelled("Z move cancelled by Stop Z before sending movement.")
        confirmed_z = finite_float(controller.move_abs(
            target_z, tolerance_um=tolerance,
            cancel_check=lambda: generation != getattr(self, "micro_z_stop_generation", 0),
            skip_if_within_tolerance=skip_if_within_tolerance,
        ), "Confirmed Z")
        if generation != getattr(self, "micro_z_stop_generation", 0):
            raise ZMotionCancelled("Z move cancelled by Stop Z.")
        range_error = self._micro_z_validate_target_range(confirmed_z)
        if range_error or abs(confirmed_z - target_z) > tolerance:
            raise HardwareSafetyError(
                f"Z arrival rejected: target={target_z:.3f} um, actual={confirmed_z:.3f} um, "
                f"delta={confirmed_z - target_z:+.3f} um, tolerance={tolerance:.3f} um. "
                + (range_error or "")
            )
        return confirmed_z

    def _read_micro_z_for_save(self):
        if not getattr(self, "micro_z_connected", False):
            return math.nan
        try:
            with self.micro_z_request_lock:
                z = self._get_micro_z_controller().get_z()
            self._safe_after(0, lambda z=z: self._set_micro_z_value(z))
            return z
        except Exception as exc:
            self.log(f"Could not read Micro-Manager Z while saving site: {exc}")
            return math.nan

    def _move_z_to_position(self, target_z, label="Micro-Manager Z move"):
        """Move Nikon Ti Z to target_z. Blocks until confirmed; worker-thread only."""
        if not getattr(self, "micro_z_connected", False):
            return None, "Z not connected"
        generation = getattr(self, "micro_z_stop_generation", 0)
        with self.micro_z_request_lock:
            try:
                confirmed_z = self._checked_micro_z_move(target_z, generation, skip_if_within_tolerance=True)
                self._safe_after(0, lambda z=confirmed_z: self._set_micro_z_value(z))
                self._log_micro_z_motion_result(label, target_z, confirmed_z)
                return confirmed_z, "ok"
            except Exception as exc:
                try:
                    target_text = f"{float(target_z):.3f}"
                except Exception:
                    target_text = str(target_z)
                self._log_async(f"Micro-Manager Z move to {target_text} um failed: {exc}")
                return None, str(exc)

    def _poll_micro_z_position(self):
        if self.is_closing:
            self.micro_z_poll_job = None
            return
        if getattr(self, "micro_z_connected", False) and not self.micro_z_poll_inflight:
            if self.micro_z_request_lock.acquire(blocking=False):
                self.micro_z_poll_inflight = True

                def worker():
                    try:
                        z = self._get_micro_z_controller().get_z()
                        self._safe_after(0, lambda z=z: self._set_micro_z_value(z))
                    except Exception as exc:
                        self.micro_z_connected = False
                        self._safe_after(0, lambda exc=exc: self._set_micro_z_status(f"poll failed: {exc}"))
                    finally:
                        self.micro_z_poll_inflight = False
                        self.micro_z_request_lock.release()

                threading.Thread(target=worker, daemon=True).start()
        self.micro_z_poll_job = self._safe_after(self.micro_z_poll_interval_ms, self._poll_micro_z_position)

    def start_micro_z_polling(self):
        if self.micro_z_poll_job:
            return
        self._poll_micro_z_position()
