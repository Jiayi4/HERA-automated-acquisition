"""Validation and faults that must not silently skip a scan site."""

import math


class HardwareSafetyError(RuntimeError):
    pass


class ZMotionCancelled(HardwareSafetyError):
    pass


def finite_float(value, label):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise HardwareSafetyError(f"{label} must be a finite number.") from exc
    if not math.isfinite(result):
        raise HardwareSafetyError(f"{label} must be a finite number.")
    return result
