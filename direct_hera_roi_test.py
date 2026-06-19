import argparse
import ctypes
import os
import threading
import time


SCAN_MODES = {"Low": 0, "Medium": 1, "High": 2, "Extra High": 3}
TRIGGER_MODES = {"Internal": 0, "DeferredStartExtLineHi": 1, "StepScanExtLoHi": 2}
BINNING_OPTIONS = {"None": 0, "2x": 1, "4x": 2, "8x": 3, "2x Sharp": 0x1000, "4x Sharp": 0x1001}
DATA_TYPES = {"SinglePrecision": 0, "DoublePrecision": 1}


class HeraDeviceInfo(ctypes.Structure):
    _fields_ = [
        ("Id", ctypes.c_char * 128),
        ("ProductName", ctypes.c_char * 128),
        ("SerialNumber", ctypes.c_char * 128),
        ("Vendor", ctypes.c_char * 128),
    ]


def default_dll_path():
    here = os.path.abspath(os.path.dirname(__file__))
    candidates = [
        os.path.join(here, "HeraAPI.dll"),
        os.path.join(os.path.dirname(here), "HeraAPI.dll"),
        os.path.join(os.getcwd(), "HeraAPI.dll"),
        r"C:\Program Files\Nireos\Hera SDK\HeraAPI\bin\HeraAPI.dll",
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return candidates[0]


def decode(value):
    return value.decode("utf-8", errors="ignore") if value else ""


def main():
    parser = argparse.ArgumentParser(description="Direct HERA SDK ROI acquisition test without the app wrapper.")
    parser.add_argument("--dll", default=default_dll_path(), help="Path to HeraAPI.dll")
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--roi", type=int, nargs=4, default=(1492, 486, 825, 869), metavar=("X", "Y", "W", "H"))
    parser.add_argument("--scan-mode", choices=SCAN_MODES.keys(), default="Medium")
    parser.add_argument("--trigger-mode", choices=TRIGGER_MODES.keys(), default="Internal")
    parser.add_argument("--averages", type=int, default=1)
    parser.add_argument("--stabilization-ms", type=int, default=0)
    parser.add_argument("--bands", type=int, default=1300)
    parser.add_argument("--binning", choices=BINNING_OPTIONS.keys(), default="4x")
    parser.add_argument("--data-type", choices=DATA_TYPES.keys(), default="SinglePrecision")
    parser.add_argument("--exposure-ms", type=float, default=None)
    parser.add_argument("--hdr", choices=("on", "off", "leave"), default="leave")
    parser.add_argument("--timeout-sec", type=float, default=1800.0, help="Maximum wait time for the acquisition callback.")
    parser.add_argument("--skip-acquisition", action="store_true", help="Only connect, call SetROI, and read back ROI.")
    parser.add_argument("--skip-compute", action="store_true", help="Acquire raw data but do not call GetHyperCubeEx.")
    args = parser.parse_args()

    print(f"DLL: {args.dll}")
    dll = ctypes.CDLL(args.dll)

    progress_cb_type = ctypes.CFUNCTYPE(None, ctypes.c_float)
    data_cb_type = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p)

    def fn(name, restype=ctypes.c_int, argtypes=None):
        func = getattr(dll, name)
        func.restype = restype
        if argtypes is not None:
            func.argtypes = argtypes
        return func

    get_last_error = fn("HeraAPI_GetLastErrorMessage", ctypes.c_char_p, [])
    enumerate_devices = fn("HeraAPI_EnumerateDevices", ctypes.c_int, [ctypes.POINTER(ctypes.c_size_t)])
    get_device_info = fn("HeraAPI_GetDeviceInfoByIndex", ctypes.c_int, [ctypes.c_size_t, ctypes.POINTER(HeraDeviceInfo)])
    create_device = fn("HeraAPI_CreateDevice", ctypes.c_int, [ctypes.POINTER(HeraDeviceInfo), ctypes.POINTER(ctypes.c_void_p)])
    release_device = fn("HeraAPI_ReleaseDevice", ctypes.c_int, [ctypes.c_void_p])
    connect = fn("HeraAPI_Connect", ctypes.c_int, [ctypes.c_void_p])
    disconnect = fn("HeraAPI_Disconnect", ctypes.c_int, [ctypes.c_void_p])
    set_roi = fn("HeraAPI_SetROI", ctypes.c_int, [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint])
    is_roi_writable = fn("HeraAPI_IsROIWritable", ctypes.c_int, [ctypes.c_void_p, ctypes.POINTER(ctypes.c_bool)])
    get_offset_x = fn("HeraAPI_GetOffsetX", ctypes.c_int, [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)])
    get_offset_y = fn("HeraAPI_GetOffsetY", ctypes.c_int, [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)])
    get_width = fn("HeraAPI_GetWidth", ctypes.c_int, [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)])
    get_height = fn("HeraAPI_GetHeight", ctypes.c_int, [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)])
    set_exposure = fn("HeraAPI_SetExposure", ctypes.c_int, [ctypes.c_void_p, ctypes.c_double])
    set_hdr = getattr(dll, "HeraAPI_SetHDR", None)
    get_hdr = getattr(dll, "HeraAPI_GetHDR", None)
    if set_hdr:
        set_hdr.restype = ctypes.c_int
        set_hdr.argtypes = [ctypes.c_void_p, ctypes.c_bool]
    if get_hdr:
        get_hdr.restype = ctypes.c_int
        get_hdr.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_bool)]
    register_callbacks = fn(
        "HeraAPI_RegisterHyperspectralDataAcqCallbacks",
        ctypes.c_int,
        [ctypes.c_void_p, progress_cb_type, data_cb_type],
    )
    unregister_callbacks = fn("HeraAPI_UnregisterHyperspectralDataAcqCallbacks", ctypes.c_int, [ctypes.c_void_p])
    start_acquisition = fn(
        "HeraAPI_StartHyperspectralDataAcquisitionEx",
        ctypes.c_int,
        [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int],
    )
    get_data_info = fn(
        "HeraAPI_GetHyperspectralDataInfo",
        ctypes.c_int,
        [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_void_p)],
    )
    get_cube = fn(
        "HeraAPI_GetHyperCubeEx",
        ctypes.c_int,
        [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_int, ctypes.c_uint, ctypes.c_int, ctypes.c_void_p],
    )
    get_cube_info = fn(
        "HeraAPI_GetHyperCubeInfo",
        ctypes.c_int,
        [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)],
    )
    release_data = fn("HeraAPI_ReleaseHyperspectralData", ctypes.c_int, [ctypes.c_void_p])
    release_cube = fn("HeraAPI_ReleaseHyperCube", ctypes.c_int, [ctypes.c_void_p])

    def last_error():
        return decode(get_last_error()) or "Unknown error"

    def report(action, status):
        print(f"{action}: status={status}, error={last_error()}")
        return status

    def check(action, status):
        report(action, status)
        if status != 0:
            raise RuntimeError(f"{action} failed")

    def read_roi(handle):
        x = ctypes.c_uint()
        y = ctypes.c_uint()
        w = ctypes.c_uint()
        h = ctypes.c_uint()
        check("GetOffsetX", get_offset_x(handle, ctypes.byref(x)))
        check("GetOffsetY", get_offset_y(handle, ctypes.byref(y)))
        check("GetWidth", get_width(handle, ctypes.byref(w)))
        check("GetHeight", get_height(handle, ctypes.byref(h)))
        return x.value, y.value, w.value, h.value

    device = ctypes.c_void_p()
    data_handle = ctypes.c_void_p()
    cube_handle = ctypes.c_void_p()
    callbacks_registered = False
    connected = False

    try:
        count = ctypes.c_size_t()
        check("EnumerateDevices", enumerate_devices(ctypes.byref(count)))
        print(f"Device count: {count.value}")
        if count.value == 0:
            raise RuntimeError("No HERA devices found.")
        if args.device_index >= count.value:
            raise RuntimeError(f"Device index {args.device_index} is out of range.")

        info = HeraDeviceInfo()
        check("GetDeviceInfoByIndex", get_device_info(ctypes.c_size_t(args.device_index), ctypes.byref(info)))
        print(
            "Device: "
            f"product={decode(info.ProductName)}, serial={decode(info.SerialNumber)}, "
            f"vendor={decode(info.Vendor)}, id={decode(info.Id)}"
        )

        check("CreateDevice", create_device(ctypes.byref(info), ctypes.byref(device)))
        check("Connect", connect(device))
        connected = True

        if args.exposure_ms is not None:
            check("SetExposure", set_exposure(device, ctypes.c_double(args.exposure_ms * 1000.0)))

        if args.hdr != "leave":
            if not set_hdr:
                raise RuntimeError("HeraAPI_SetHDR is not available in this DLL.")
            check("SetHDR", set_hdr(device, ctypes.c_bool(args.hdr == "on")))
        if get_hdr:
            hdr = ctypes.c_bool(False)
            check("GetHDR", get_hdr(device, ctypes.byref(hdr)))
            print(f"HDR readback: {hdr.value}")

        writable = ctypes.c_bool(False)
        check("IsROIWritable", is_roi_writable(device, ctypes.byref(writable)))
        print(f"ROI writable before SetROI: {writable.value}")
        print(f"ROI before SetROI: {read_roi(device)}")

        roi_x, roi_y, roi_w, roi_h = args.roi
        set_roi_status = report("SetROI", set_roi(device, ctypes.c_uint(roi_x), ctypes.c_uint(roi_y), ctypes.c_uint(roi_w), ctypes.c_uint(roi_h)))
        print(f"ROI after SetROI: {read_roi(device)}")
        if set_roi_status != 0:
            print("SetROI failed, so acquisition/computation was skipped.")
            return

        if args.skip_acquisition:
            return

        data_event = threading.Event()
        data_status_box = {"status": None, "message": ""}

        def progress_handler(progress):
            print(f"Acquisition progress: {float(progress):.1f}%")

        def data_handler(handle, data_status, message):
            data_handle.value = handle
            data_status_box["status"] = data_status
            data_status_box["message"] = decode(message)
            data_event.set()

        progress_cb = progress_cb_type(progress_handler)
        data_cb = data_cb_type(data_handler)
        check("RegisterHyperspectralDataAcqCallbacks", register_callbacks(device, progress_cb, data_cb))
        callbacks_registered = True

        scan_mode = SCAN_MODES[args.scan_mode]
        trigger_mode = TRIGGER_MODES[args.trigger_mode]
        t0 = time.perf_counter()
        check(
            "StartHyperspectralDataAcquisitionEx",
            start_acquisition(
                device,
                ctypes.c_int(scan_mode),
                ctypes.c_int(trigger_mode),
                ctypes.c_int(args.averages),
                ctypes.c_int(args.stabilization_ms),
            ),
        )
        print("Waiting for acquisition callback...")
        if not data_event.wait(timeout=max(1.0, args.timeout_sec)):
            raise TimeoutError(f"No acquisition callback received within {args.timeout_sec:.1f} s.")
        acquisition_elapsed = time.perf_counter() - t0
        print(
            f"Acquisition callback: elapsed={acquisition_elapsed:.2f}s, "
            f"data_status={data_status_box['status']}, message={data_status_box['message']!r}"
        )
        if data_status_box["status"] != 0:
            raise RuntimeError("Hyperspectral acquisition callback reported an error.")

        raw_w = ctypes.c_int()
        raw_h = ctypes.c_int()
        raw_ptr = ctypes.c_void_p()
        check("GetHyperspectralDataInfo", get_data_info(data_handle, ctypes.byref(raw_w), ctypes.byref(raw_h), ctypes.byref(raw_ptr)))
        print(f"Raw hyperspectral data info: width={raw_w.value}, height={raw_h.value}, ptr={raw_ptr.value}")
        print(f"ROI after acquisition: {read_roi(device)}")

        if args.skip_compute:
            return

        t1 = time.perf_counter()
        check(
            "GetHyperCubeEx",
            get_cube(
                device,
                data_handle,
                ctypes.byref(cube_handle),
                ctypes.c_int(DATA_TYPES[args.data_type]),
                ctypes.c_uint(args.bands),
                ctypes.c_int(BINNING_OPTIONS[args.binning]),
                None,
            ),
        )
        compute_elapsed = time.perf_counter() - t1
        cube_w = ctypes.c_int()
        cube_h = ctypes.c_int()
        cube_bands = ctypes.c_int()
        cube_type = ctypes.c_int()
        check("GetHyperCubeInfo", get_cube_info(cube_handle, ctypes.byref(cube_w), ctypes.byref(cube_h), ctypes.byref(cube_bands), ctypes.byref(cube_type)))
        print(
            f"Hypercube info: width={cube_w.value}, height={cube_h.value}, "
            f"bands={cube_bands.value}, dataType={cube_type.value}, compute_elapsed={compute_elapsed:.2f}s"
        )
    finally:
        if cube_handle.value:
            report("ReleaseHyperCube", release_cube(cube_handle))
        if data_handle.value:
            report("ReleaseHyperspectralData", release_data(data_handle))
        if callbacks_registered:
            report("UnregisterHyperspectralDataAcqCallbacks", unregister_callbacks(device))
        if connected:
            report("Disconnect", disconnect(device))
        if device.value:
            report("ReleaseDevice", release_device(device))


if __name__ == "__main__":
    main()
