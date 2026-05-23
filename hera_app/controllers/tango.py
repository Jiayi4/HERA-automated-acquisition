import ctypes
import os


class TangoController:
    OK_STATUS = 0
    INTERFACE_RS232 = 1
    INTERFACE_OPTIONS = {
        "RS232 / COM": 1,
        "USB": 2,
        "PCI": 3,
    }
    AXIS_XY_FLAGS = 3

    def __init__(self, dll_path=None):
        base = os.path.abspath(os.path.dirname(__file__))
        self.dll_path = dll_path or os.path.join(base, "Tango_DLL.dll")
        self.dll = None
        self.lsid = 0
        self.connected = False
        self.load_dll()

    def load_dll(self):
        if not os.path.exists(self.dll_path):
            raise FileNotFoundError(f"Tango DLL not found: {self.dll_path}")
        self.dll = ctypes.WinDLL(self.dll_path)
        self._define_functions()

    def _define_function(self, name, restype=ctypes.c_int, argtypes=None):
        try:
            func = getattr(self.dll, name)
        except AttributeError as exc:
            raise AttributeError(f"Tango DLL function not found: {name}") from exc
        func.restype = restype
        if argtypes is not None:
            func.argtypes = argtypes
        return func

    def _define_functions(self):
        bool_ptr = ctypes.POINTER(ctypes.c_int)
        double_ptr = ctypes.POINTER(ctypes.c_double)
        int_ptr = ctypes.POINTER(ctypes.c_int)

        self.LSX_CreateLSID = self._define_function("LSX_CreateLSID", ctypes.c_int, [int_ptr])
        self.LSX_FreeLSID = self._define_function("LSX_FreeLSID", ctypes.c_int, [ctypes.c_int])
        self.LSX_ConnectSimple = self._define_function(
            "LSX_ConnectSimple",
            ctypes.c_int,
            [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_int],
        )
        self.LSX_Disconnect = self._define_function("LSX_Disconnect", ctypes.c_int, [ctypes.c_int])
        self.LSX_GetTangoVersion = self._define_function(
            "LSX_GetTangoVersion",
            ctypes.c_int,
            [ctypes.c_int, ctypes.c_char_p, ctypes.c_int],
        )
        self.LSX_GetError = self._define_function("LSX_GetError", ctypes.c_int, [ctypes.c_int, int_ptr])
        self.LSX_GetErrorString = self._define_function(
            "LSX_GetErrorString",
            ctypes.c_int,
            [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int],
        )
        self.LSX_GetPos = self._define_function(
            "LSX_GetPos",
            ctypes.c_int,
            [ctypes.c_int, double_ptr, double_ptr, double_ptr, double_ptr],
        )
        self.LSX_GetVel = self._define_function(
            "LSX_GetVel",
            ctypes.c_int,
            [ctypes.c_int, double_ptr, double_ptr, double_ptr, double_ptr],
        )
        self.LSX_GetSecVel = self._define_function(
            "LSX_GetSecVel",
            ctypes.c_int,
            [ctypes.c_int, double_ptr, double_ptr, double_ptr, double_ptr],
        )
        self.LSX_GetAccel = self._define_function(
            "LSX_GetAccel",
            ctypes.c_int,
            [ctypes.c_int, double_ptr, double_ptr, double_ptr, double_ptr],
        )
        self.LSX_SetVel = self._define_function(
            "LSX_SetVel",
            ctypes.c_int,
            [ctypes.c_int, ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double],
        )
        self.LSX_SetSecVel = self._define_function(
            "LSX_SetSecVel",
            ctypes.c_int,
            [ctypes.c_int, ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double],
        )
        self.LSX_SetAccel = self._define_function(
            "LSX_SetAccel",
            ctypes.c_int,
            [ctypes.c_int, ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double],
        )
        self.LSX_MoveAbs = self._define_function(
            "LSX_MoveAbs",
            ctypes.c_int,
            [ctypes.c_int, ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_int],
        )
        self.LSX_WaitForAxisStop = self._define_function(
            "LSX_WaitForAxisStop",
            ctypes.c_int,
            [ctypes.c_int, ctypes.c_int, ctypes.c_int, bool_ptr],
        )
        self.LSX_StopAxes = self._define_function("LSX_StopAxes", ctypes.c_int, [ctypes.c_int])
        self.LSX_Calibrate = self._define_function("LSX_Calibrate", ctypes.c_int, [ctypes.c_int])
        self.LSX_RMeasure = self._define_function("LSX_RMeasure", ctypes.c_int, [ctypes.c_int])

    def check_status(self, status, action):
        if status != self.OK_STATUS:
            raise RuntimeError(f"{action} failed with Tango error code {status}: {self.get_error_string(status)}")

    def get_error_string(self, error_code):
        if not self.dll:
            return "Unknown Tango error"
        buffer = ctypes.create_string_buffer(512)
        lsid = ctypes.c_int(self.lsid if self.lsid else 0)
        try:
            lookup_status = self.LSX_GetErrorString(lsid, ctypes.c_int(error_code), buffer, ctypes.c_int(511))
            if lookup_status == self.OK_STATUS:
                text = buffer.value.decode("ascii", errors="ignore").strip()
                if text:
                    return text
        except Exception:
            pass
        return "Unknown Tango error"

    def connect(self, interface_type, com_port, baud_rate, show_protocol=False):
        if self.connected:
            return
        lsid_ptr = ctypes.c_int()
        self.check_status(self.LSX_CreateLSID(ctypes.byref(lsid_ptr)), "Create LSID")
        self.lsid = lsid_ptr.value
        try:
            self.check_status(
                self.LSX_ConnectSimple(
                    ctypes.c_int(self.lsid),
                    ctypes.c_int(interface_type),
                    com_port.encode("ascii"),
                    ctypes.c_int(baud_rate),
                    ctypes.c_int(1 if show_protocol else 0),
                ),
                "Connect stage",
            )
        except Exception:
            self.LSX_FreeLSID(ctypes.c_int(self.lsid))
            self.lsid = 0
            raise
        self.connected = True

    def disconnect(self):
        if self.lsid:
            try:
                self.LSX_Disconnect(ctypes.c_int(self.lsid))
            finally:
                self.LSX_FreeLSID(ctypes.c_int(self.lsid))
                self.lsid = 0
                self.connected = False

    def get_version(self):
        self._require_connected()
        buffer = ctypes.create_string_buffer(256)
        self.check_status(self.LSX_GetTangoVersion(ctypes.c_int(self.lsid), buffer, ctypes.c_int(255)), "Get controller version")
        return buffer.value.decode("ascii", errors="ignore").strip()

    def get_position(self):
        self._require_connected()
        x = ctypes.c_double()
        y = ctypes.c_double()
        z = ctypes.c_double()
        a = ctypes.c_double()
        self.check_status(self.LSX_GetPos(ctypes.c_int(self.lsid), ctypes.byref(x), ctypes.byref(y), ctypes.byref(z), ctypes.byref(a)), "Get position")
        return x.value, y.value, z.value, a.value

    def _get_motion_values(self, func, action):
        x = ctypes.c_double()
        y = ctypes.c_double()
        z = ctypes.c_double()
        a = ctypes.c_double()
        self.check_status(func(ctypes.c_int(self.lsid), ctypes.byref(x), ctypes.byref(y), ctypes.byref(z), ctypes.byref(a)), action)
        return x.value, y.value, z.value, a.value

    def get_velocity(self):
        self._require_connected()
        return self._get_motion_values(self.LSX_GetVel, "Get velocity")

    def get_secure_velocity(self):
        self._require_connected()
        return self._get_motion_values(self.LSX_GetSecVel, "Get secure velocity")

    def get_acceleration(self):
        self._require_connected()
        return self._get_motion_values(self.LSX_GetAccel, "Get acceleration")

    def apply_motion_settings(self, speed_xy, accel_xy, secure_vel_xy, speed_z=None, accel_z=None, secure_vel_z=None):
        self._require_connected()
        cur_vel = self.get_velocity()
        cur_accel = self.get_acceleration()
        cur_sec_vel = self.get_secure_velocity()
        speed_z = speed_xy if speed_z is None else speed_z
        accel_z = accel_xy if accel_z is None else accel_z
        secure_vel_z = secure_vel_xy if secure_vel_z is None else secure_vel_z
        self.check_status(
            self.LSX_SetVel(ctypes.c_int(self.lsid), speed_xy, speed_xy, speed_z, cur_vel[3]),
            "Set velocity",
        )
        self.check_status(
            self.LSX_SetAccel(ctypes.c_int(self.lsid), accel_xy, accel_xy, accel_z, cur_accel[3]),
            "Set acceleration",
        )
        self.check_status(
            self.LSX_SetSecVel(ctypes.c_int(self.lsid), secure_vel_xy, secure_vel_xy, secure_vel_z, cur_sec_vel[3]),
            "Set secure velocity",
        )

    def move_absolute_xy(self, x, y):
        self._require_connected()
        _, _, z, a = self.get_position()
        self.check_status(
            self.LSX_MoveAbs(ctypes.c_int(self.lsid), x, y, z, a, ctypes.c_int(0)),
            "Move absolute XY",
        )

    def move_absolute_a(self, a):
        self._require_connected()
        x, y, z, _ = self.get_position()
        self.check_status(
            self.LSX_MoveAbs(ctypes.c_int(self.lsid), x, y, z, a, ctypes.c_int(0)),
            "Move absolute A",
        )

    def wait_for_xy_stop(self, timeout_ms):
        self._require_connected()
        timed_out = ctypes.c_int(0)
        self.check_status(
            self.LSX_WaitForAxisStop(
                ctypes.c_int(self.lsid),
                ctypes.c_int(self.AXIS_XY_FLAGS),
                ctypes.c_int(timeout_ms),
                ctypes.byref(timed_out),
            ),
            "Wait for XY stop",
        )
        if timed_out.value != 0:
            raise RuntimeError("XY motion timed out")

    def stop_axes(self):
        if self.connected:
            self.LSX_StopAxes(ctypes.c_int(self.lsid))

    def calibrate(self):
        self._require_connected()
        self.check_status(self.LSX_Calibrate(ctypes.c_int(self.lsid)), "Calibrate stage")

    def range_measure(self):
        self._require_connected()
        self.check_status(self.LSX_RMeasure(ctypes.c_int(self.lsid)), "Range measure")

    def _require_connected(self):
        if not self.connected or not self.lsid:
            raise RuntimeError("Tango stage is not connected.")
