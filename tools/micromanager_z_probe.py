"""Probe Nikon Ti Z control through Micro-Manager MMCore.

Default behavior is read-only. Pass --move-um with a small value to test an
absolute Z move relative to the current position.
"""

from __future__ import annotations

import argparse
import os
import sys
import time


DEFAULT_MM_PATH = r"C:\Program Files\Micro-Manager-2.0"
DEFAULT_CONFIG = os.path.join(DEFAULT_MM_PATH, "NikonTi_Z.cfg")
DEFAULT_DEVICE = "TIZDrive"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe Nikon Ti Z through Micro-Manager.")
    parser.add_argument(
        "--mm-path",
        default=DEFAULT_MM_PATH,
        help=f"Micro-Manager install folder. Default: {DEFAULT_MM_PATH}",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help=f"Micro-Manager config file. Default: {DEFAULT_CONFIG}",
    )
    parser.add_argument(
        "--device",
        default="",
        help=f"Focus/Z device label. Default: config focus device, fallback {DEFAULT_DEVICE}.",
    )
    parser.add_argument(
        "--move-um",
        type=float,
        default=None,
        help="Optional relative test move in micrometers. Omit for read-only probe.",
    )
    parser.add_argument(
        "--max-step-um",
        type=float,
        default=5.0,
        help="Safety limit for --move-um unless --allow-large-move is set.",
    )
    parser.add_argument(
        "--allow-large-move",
        action="store_true",
        help="Allow --move-um larger than --max-step-um.",
    )
    parser.add_argument(
        "--settle-sec",
        type=float,
        default=0.2,
        help="Extra wait after move before reading back position.",
    )
    return parser.parse_args()


def fail(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 2


def main() -> int:
    args = parse_args()
    if not os.path.isdir(args.mm_path):
        return fail(f"Micro-Manager folder not found: {args.mm_path}")
    if not os.path.isfile(args.config):
        return fail(f"Micro-Manager config not found: {args.config}")
    if args.move_um is not None and not args.allow_large_move:
        if abs(args.move_um) > abs(args.max_step_um):
            return fail(
                f"Refusing move {args.move_um:g} um; limit is {args.max_step_um:g} um. "
                "Use --allow-large-move only if you are certain."
            )

    try:
        import pymmcore
    except Exception as exc:
        return fail(f"pymmcore is not installed or failed to import: {exc}")

    core = pymmcore.CMMCore()
    try:
        print(f"MMCore: {core.getVersionInfo()}")
        print(f"Micro-Manager path: {args.mm_path}")
        print(f"Config: {args.config}")
        core.setDeviceAdapterSearchPaths([args.mm_path])
        core.loadSystemConfiguration(args.config)

        focus_device = args.device.strip()
        if not focus_device:
            try:
                focus_device = core.getFocusDevice()
            except Exception:
                focus_device = ""
        if not focus_device:
            focus_device = DEFAULT_DEVICE

        print(f"Focus/Z device: {focus_device}")
        start_z = float(core.getPosition(focus_device))
        print(f"Current Z: {start_z:.6f} um")

        if args.move_um is None:
            print("Read-only probe completed. No Z move was requested.")
            return 0

        target_z = start_z + float(args.move_um)
        print(f"Moving Z by {args.move_um:.6f} um to {target_z:.6f} um...")
        core.setPosition(focus_device, target_z)
        core.waitForDevice(focus_device)
        if args.settle_sec > 0:
            time.sleep(args.settle_sec)
        end_z = float(core.getPosition(focus_device))
        print(f"New Z: {end_z:.6f} um")
        print(f"Delta: {end_z - start_z:.6f} um")
        return 0
    finally:
        try:
            core.unloadAllDevices()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
