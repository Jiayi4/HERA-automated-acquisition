"""Local Control Bar presets, independent of camera/SDK state."""

import json
import os
import tempfile
from pathlib import Path


PRESET_FIELDS = (
    "scan_mode", "spectral_sampling", "bands", "averages", "binning", "data_type",
)
DEFAULT_PRESETS = {
    "Fluo": {
        "scan_mode": "Medium", "spectral_sampling": "Uniform lambda",
        "bands": 200, "averages": 2, "binning": "None", "data_type": "SinglePrecision",
    },
    "BF": {
        "scan_mode": "Extra High", "spectral_sampling": "Uniform lambda",
        "bands": 1500, "averages": 2, "binning": "4x", "data_type": "SinglePrecision",
    },
}
DEFAULT_PRESET_PATH = Path(__file__).resolve().parents[1] / "local" / "control_bar_presets.json"


def validate_preset_name(name):
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 64:
        raise ValueError("Preset name must contain 1 to 64 characters.")
    if any(ord(char) < 32 for char in name):
        raise ValueError("Preset name cannot contain control characters.")
    return name.strip()


def validate_preset(settings, choices):
    if not isinstance(settings, dict) or set(settings) != set(PRESET_FIELDS):
        raise ValueError("Preset must contain exactly the six Control Bar settings.")
    for field in ("bands", "averages"):
        if type(settings[field]) is not int:
            raise ValueError(f"{field} must be an integer.")
    if settings["bands"] < 0:
        raise ValueError("Bands must be zero (SDK default) or a positive integer.")
    for field, allowed in choices.items():
        if field != "averages" and not isinstance(settings[field], str):
            raise ValueError(f"{field} must be a supported option name.")
        if settings[field] not in allowed:
            raise ValueError(f"Unsupported {field}: {settings[field]!r}.")
    return {field: settings[field] for field in PRESET_FIELDS}


def load_parameter_presets(path, choices):
    presets = {name: dict(settings) for name, settings in DEFAULT_PRESETS.items()}
    try:
        with Path(path).open(encoding="utf-8") as source:
            payload = json.load(source)
    except FileNotFoundError:
        return presets
    if (not isinstance(payload, dict) or type(payload.get("version")) is not int
            or payload["version"] != 1 or not isinstance(payload.get("presets"), dict)):
        raise ValueError("Unsupported parameter preset file format.")
    for name, settings in payload["presets"].items():
        presets[validate_preset_name(name)] = validate_preset(settings, choices)
    return presets


def save_parameter_presets(path, presets, choices):
    validated = {
        validate_preset_name(name): validate_preset(settings, choices)
        for name, settings in presets.items()
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as target:
            temporary = Path(target.name)
            json.dump({"version": 1, "presets": validated}, target, indent=2, ensure_ascii=True)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
