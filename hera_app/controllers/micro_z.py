import os
import threading
import time

from hera_app.safety import HardwareSafetyError, ZMotionCancelled, finite_float


class MicroManagerZController:
    """Direct MMCore controller for Nikon Ti Z through Micro-Manager."""

    DEFAULT_MM_PATH = r"C:\Program Files\Micro-Manager-2.0"
    DEFAULT_CONFIG_PATH = os.path.join(DEFAULT_MM_PATH, "NikonTi_Z.cfg")
    DEFAULT_DEVICE = "TIZDrive"
    POSITION_STABLE_SECONDS = 0.5
    POSITION_STABLE_READS = 4
    POSITION_STABLE_SPAN_UM = 0.025

    def __init__(self, mm_path=None, config_path=None, device_label=None):
        self.mm_path = mm_path or self.DEFAULT_MM_PATH
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.device_label = device_label or self.DEFAULT_DEVICE
        self.core = None
        self.connected = False
        self.lock = threading.RLock()
        self._move_lock = threading.Lock()
        self._stop_requested = threading.Event()
        self._stop_state_lock = threading.Lock()
        self._stop_generation = 0
        self._stop_unconfirmed = False
        self._stop_command_supported = None
        self.last_move_confirmation = None
        self.last_stop_confirmation = None

    def connect(self):
        with self.lock:
            if self.connected:
                return
            if not os.path.isdir(self.mm_path):
                raise RuntimeError(f"Micro-Manager folder not found: {self.mm_path}")
            if not os.path.isfile(self.config_path):
                raise RuntimeError(f"Micro-Manager config not found: {self.config_path}")
            try:
                import pymmcore
            except Exception as exc:
                raise RuntimeError("pymmcore is not installed. Install pycromanager/pymmcore first.") from exc

            core = pymmcore.CMMCore()
            core.setDeviceAdapterSearchPaths([self.mm_path])
            core.loadSystemConfiguration(self.config_path)
            try:
                core.setAutoShutter(False)
            except Exception:
                pass
            focus_device = self.device_label.strip()
            if not focus_device:
                try:
                    focus_device = core.getFocusDevice()
                except Exception:
                    focus_device = ""
            if not focus_device:
                focus_device = self.DEFAULT_DEVICE
            self.core = core
            self.device_label = focus_device
            self.connected = True
            self._stop_command_supported = None
            self.last_move_confirmation = None
            self.last_stop_confirmation = None

    def disconnect(self):
        with self.lock:
            core = self.core
            self.core = None
            self.connected = False
            if core is not None:
                try:
                    core.unloadAllDevices()
                except Exception:
                    pass

    def _require_core(self):
        if not self.connected or self.core is None:
            self.connect()
        return self.core

    def get_z(self):
        with self.lock:
            core = self._require_core()
            return finite_float(core.getPosition(self.device_label), "Z readback")

    def _is_nikon_ti_focus(self, core):
        try:
            return (core.getDeviceLibrary(self.device_label) == "NikonTI"
                    and core.getDeviceName(self.device_label) == "TIZDrive")
        except Exception:
            return False

    def _stable_position_sample(self, state, value, now):
        if state is None or max(state[1], value) - min(state[0], value) > self.POSITION_STABLE_SPAN_UM + 1e-8:
            return (value, value, now, 1), False
        state = (min(state[0], value), max(state[1], value), state[2], state[3] + 1)
        stable = state[3] >= self.POSITION_STABLE_READS and now - state[2] >= self.POSITION_STABLE_SECONDS
        return state, stable

    def move_abs(self, target_z, settle_sec=0.2, tolerance_um=0.5, timeout_sec=15.0,
                 cancel_check=None, skip_if_within_tolerance=False):
        target_z = finite_float(target_z, "Target Z")
        tolerance_um = finite_float(tolerance_um, "Z tolerance")
        timeout_sec = finite_float(timeout_sec, "Z move timeout")
        settle_sec = finite_float(settle_sec, "Z settle time")
        if tolerance_um <= 0 or timeout_sec <= 0 or settle_sec < 0:
            raise HardwareSafetyError("Z tolerance/timeout must be positive; settle time cannot be negative.")
        if not self._move_lock.acquire(blocking=False):
            raise HardwareSafetyError("Another Z move is still active.")
        with self._stop_state_lock:
            generation = self._stop_generation
            self._stop_requested.clear()
        commanded = False
        self.last_move_confirmation = None
        try:
            with self.lock:
                core = self._require_core()
                nikon_ti = self._is_nikon_ti_focus(core)
                if self._stop_unconfirmed:
                    raise HardwareSafetyError("Previous Z stop is unconfirmed. Confirm Stop Z before another move.")
                current = finite_float(core.getPosition(self.device_label), "Z readback")
                if generation != self._stop_generation or (cancel_check and cancel_check()):
                    raise ZMotionCancelled("Z move cancelled before sending movement.")
                if not skip_if_within_tolerance or abs(current - target_z) > tolerance_um:
                    commanded = True
                    core.setPosition(self.device_label, target_z)
            deadline = time.monotonic() + timeout_sec
            stable_since = None
            stable_reads = 0
            position_state = None
            while True:
                if self._stop_requested.is_set() or (cancel_check and cancel_check()):
                    raise ZMotionCancelled("Z move cancelled by Stop Z.")
                # Release the driver lock between polls so Stop can run during a move.
                with self.lock:
                    if self.core is not core or not self.connected:
                        raise HardwareSafetyError("Z disconnected during movement.")
                    busy = bool(core.deviceBusy(self.device_label))
                    current = finite_float(core.getPosition(self.device_label), "Z readback")
                now = time.monotonic()
                if self._stop_requested.is_set() or (cancel_check and cancel_check()):
                    raise ZMotionCancelled("Z move cancelled by Stop Z.")
                if nikon_ti and abs(current - target_z) <= tolerance_um:
                    position_state, position_stable = self._stable_position_sample(position_state, current, now)
                else:
                    position_state, position_stable = None, False
                if not busy and abs(current - target_z) <= tolerance_um:
                    stable_reads += 1
                    if stable_since is None:
                        stable_since = now
                    if stable_reads >= 2 and now - stable_since >= settle_sec:
                        self.last_move_confirmation = "driver_idle"
                        return current
                else:
                    stable_reads = 0
                    stable_since = None
                # Some NikonTI versions keep Busy asserted after encoder arrival.
                if nikon_ti and busy and position_stable and now - position_state[2] >= settle_sec:
                    self.last_move_confirmation = "NikonTI stable position (Busy still true)"
                    return current
                if now >= deadline:
                    raise HardwareSafetyError(
                        f"Z arrival timeout: target={target_z:.3f} um, actual={current:.3f} um, "
                        f"delta={current - target_z:+.3f} um, tolerance={tolerance_um:.3f} um, busy={busy}."
                    )
                self._stop_requested.wait(min(0.05, max(0.0, deadline - now)))
        except ZMotionCancelled:
            if commanded and not self._stop_requested.is_set():
                self.stop()
            raise
        except Exception as exc:
            if commanded:
                try:
                    self.stop()
                except Exception as stop_exc:
                    raise HardwareSafetyError(f"{exc}; Z stop could not be confirmed: {stop_exc}") from exc
            if isinstance(exc, HardwareSafetyError):
                raise
            raise HardwareSafetyError(f"Z move failed: {exc}") from exc
        finally:
            self._move_lock.release()

    def move_rel(self, dz, settle_sec=0.2):
        dz = finite_float(dz, "Z step")
        return self.move_abs(self.get_z() + dz, settle_sec=settle_sec)

    def stop(self):
        with self._stop_state_lock:
            self._stop_generation += 1
            self._stop_requested.set()
        self.last_stop_confirmation = None
        try:
            with self.lock:
                self._stop_unconfirmed = True
                if not self.connected or self.core is None:
                    raise HardwareSafetyError("Cannot stop Z: device is not connected.")
                core = self.core
                nikon_ti = self._is_nikon_ti_focus(core)
                if self._stop_command_supported is not False:
                    try:
                        core.stop(self.device_label)
                        self._stop_command_supported = True
                    except Exception as exc:
                        text = str(exc).lower()
                        if nikon_ti and "unsupported device command" in text and "(11)" in text:
                            self._stop_command_supported = False
                        else:
                            raise
            deadline = time.monotonic() + 2.0
            position_state = None
            while True:
                with self.lock:
                    if self.core is not core:
                        raise HardwareSafetyError("Z connection changed while stopping.")
                    busy = bool(core.deviceBusy(self.device_label))
                    value = finite_float(core.getPosition(self.device_label), "Stopped Z readback")
                    if self._stop_command_supported is False:
                        position_state, stationary = self._stable_position_sample(position_state, value, time.monotonic())
                    else:
                        stationary = not busy
                    if stationary:
                        self._stop_unconfirmed = False
                        self.last_stop_confirmation = (
                            "NikonTI position stationary (hardware Stop unsupported)"
                            if self._stop_command_supported is False else "driver_idle"
                        )
                        return value
                if time.monotonic() >= deadline:
                    raise HardwareSafetyError(
                        "Z stationary state could not be confirmed; "
                        + ("hardware Stop is unsupported." if self._stop_command_supported is False
                           else "device still reports busy after Stop.")
                    )
                time.sleep(0.05)
        except Exception as exc:
            self._stop_unconfirmed = True
            if isinstance(exc, HardwareSafetyError):
                raise
            raise HardwareSafetyError(f"Stop Z could not be confirmed: {exc}") from exc
