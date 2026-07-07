import os
import threading
import time


class MicroManagerZController:
    """Direct MMCore controller for Nikon Ti Z through Micro-Manager."""

    DEFAULT_MM_PATH = r"C:\Program Files\Micro-Manager-2.0"
    DEFAULT_CONFIG_PATH = os.path.join(DEFAULT_MM_PATH, "NikonTi_Z.cfg")
    DEFAULT_DEVICE = "TIZDrive"

    def __init__(self, mm_path=None, config_path=None, device_label=None):
        self.mm_path = mm_path or self.DEFAULT_MM_PATH
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.device_label = device_label or self.DEFAULT_DEVICE
        self.core = None
        self.connected = False
        self.lock = threading.RLock()

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
            return float(core.getPosition(self.device_label))

    def move_abs(self, target_z, settle_sec=0.2):
        with self.lock:
            core = self._require_core()
            core.setPosition(self.device_label, float(target_z))
            core.waitForDevice(self.device_label)
            if settle_sec > 0:
                time.sleep(float(settle_sec))
            return float(core.getPosition(self.device_label))

    def move_rel(self, dz, settle_sec=0.2):
        with self.lock:
            current_z = self.get_z()
            return self.move_abs(current_z + float(dz), settle_sec=settle_sec)

    def stop(self):
        with self.lock:
            core = self._require_core()
            try:
                core.stop(self.device_label)
            except Exception:
                try:
                    core.stop()
                except Exception:
                    pass
            return float(core.getPosition(self.device_label))
