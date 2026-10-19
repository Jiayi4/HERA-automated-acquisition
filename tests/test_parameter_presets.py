"""Preset persistence and Control Bar UI tests; no SDK connection or hardware moves."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hera_app.app import HeraTriggerApp
from hera_app.mixins.acquisition import AcquisitionMixin
from hera_app.mixins.theme import ThemeMixin
from hera_app.mixins.ui_builder import UIBuilderMixin
from hera_app.parameter_presets import (
    DEFAULT_PRESETS, PRESET_FIELDS, load_parameter_presets,
    save_parameter_presets, validate_preset,
)


CHOICES = {
    "scan_mode": HeraTriggerApp.SCAN_MODES,
    "spectral_sampling": HeraTriggerApp.SPECTRAL_SAMPLING,
    "averages": (1, 2, 3),
    "binning": HeraTriggerApp.BINNING_OPTIONS,
    "data_type": HeraTriggerApp.DATA_TYPES,
}


class PresetStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "local" / "presets.json"

    def test_builtin_defaults_are_independent_and_do_not_create_file(self):
        presets = load_parameter_presets(self.path, CHOICES)
        self.assertEqual(presets["Fluo"]["bands"], 200)
        self.assertEqual(presets["BF"]["scan_mode"], "Extra High")
        self.assertEqual(presets["BF"]["binning"], "4x")
        self.assertFalse(self.path.exists())
        presets["Fluo"]["bands"] = 500
        self.assertEqual(load_parameter_presets(self.path, CHOICES)["Fluo"]["bands"], 200)

    def test_roundtrip_custom_and_overwritten_builtin(self):
        presets = load_parameter_presets(self.path, CHOICES)
        presets["Fluo"]["bands"] = 250
        presets["New settings"] = dict(presets["BF"], spectral_sampling="Uniform nu", data_type="DoublePrecision")
        save_parameter_presets(self.path, presets, CHOICES)
        self.assertEqual(load_parameter_presets(self.path, CHOICES), presets)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_rejects_invalid_values_before_any_file_change(self):
        presets = load_parameter_presets(self.path, CHOICES)
        save_parameter_presets(self.path, presets, CHOICES)
        original = self.path.read_bytes()
        for field, invalid in (("bands", -1), ("bands", True), ("bands", 1.5),
                               ("averages", 0), ("averages", 4), ("averages", "2"),
                               ("binning", "3x"), ("scan_mode", []), ("data_type", None)):
            with self.subTest(field=field, invalid=invalid):
                bad = copy.deepcopy(presets)
                bad["Fluo"][field] = invalid
                with self.assertRaises(ValueError):
                    save_parameter_presets(self.path, bad, CHOICES)
                self.assertEqual(self.path.read_bytes(), original)
        with self.assertRaises(ValueError):
            validate_preset(dict(presets["Fluo"], hdr_enabled=True), CHOICES)

    def test_atomic_replace_failure_preserves_file_and_cleans_temp(self):
        presets = load_parameter_presets(self.path, CHOICES)
        save_parameter_presets(self.path, presets, CHOICES)
        original = self.path.read_bytes()
        presets["BF"]["bands"] = 1400
        with patch("hera_app.parameter_presets.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                save_parameter_presets(self.path, presets, CHOICES)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_invalid_schema_and_names_are_rejected(self):
        self.path.parent.mkdir()
        for payload in ([], {"version": True, "presets": {}}, {"version": 2, "presets": {}},
                        {"version": 1, "presets": {"": DEFAULT_PRESETS["Fluo"]}},
                        {"version": 1, "presets": {"Broken": {"bands": 200}}}):
            with self.subTest(payload=payload):
                self.path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_parameter_presets(self.path, CHOICES)


class PresetHost(tk.Tk, UIBuilderMixin, ThemeMixin):
    SCAN_MODES = HeraTriggerApp.SCAN_MODES
    SPECTRAL_SAMPLING = HeraTriggerApp.SPECTRAL_SAMPLING
    BINNING_OPTIONS = HeraTriggerApp.BINNING_OPTIONS
    DATA_TYPES = HeraTriggerApp.DATA_TYPES
    STATE_LABELS = HeraTriggerApp.STATE_LABELS
    _acquisition_busy_reason = AcquisitionMixin._acquisition_busy_reason

    def __init__(self, path):
        super().__init__()
        self.withdraw()
        self.parameter_preset_path = path
        self.controller = Mock(connected=True)
        self.timelapse_thread = None
        self.parameter_apply_lock = threading.Lock()
        self.app_state = "Ready"
        self.log = Mock()
        self.apply_parameters_async = Mock()
        self.start_flatfield_acquisition = Mock()
        self.import_flatfield_reference = Mock()
        self.clear_flatfield = Mock()
        self._build_views_and_log = Mock()
        self._safe_after = self.after
        self.theme_mode = "dark"
        self._configure_theme()
        self.param_vars = {"exposure": tk.DoubleVar(value=6), "hdr_enabled": tk.BooleanVar(value=True)}
        self.flatfield_status_var = tk.StringVar(value="Ready")
        self.columnconfigure(0, weight=1)
        self._build_center_workspace(self)


class PresetUITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "presets.json"
        self.app = PresetHost(self.path)
        self.addCleanup(self.app.destroy)

    def values(self):
        return {field: self.app.param_vars[field].get() for field in PRESET_FIELDS}

    def test_load_stages_all_six_values_without_camera_calls_or_auto_apply(self):
        self.assertEqual(self.app.param_vars["averages"].get(), 1)
        self.app._install_auto_apply_traces()
        self.app._auto_apply_parameters_job = self.app.after(0, self.app.apply_parameters_async)
        for name in ("BF", "Fluo"):
            self.app.parameter_preset_var.set(name)
            self.app.load_parameter_preset()
            self.app.update()
            self.assertEqual(self.values(), DEFAULT_PRESETS[name])
            self.assertIsNone(self.app._auto_apply_parameters_job)
        self.assertEqual(self.app.param_vars["exposure"].get(), 6)
        self.assertTrue(self.app.param_vars["hdr_enabled"].get())
        self.app.apply_parameters_async.assert_not_called()
        self.assertEqual(self.app.controller.mock_calls, [])
        set_button = next(w for w in self.app._walk_widgets(self.app)
                          if w.winfo_class() == "Button" and w.cget("text") == "Set")
        set_button.invoke()
        self.app.apply_parameters_async.assert_called_once_with()

    def test_load_blocked_during_acquisition_processing_timelapse_and_parameter_apply(self):
        original = self.values()
        for state in ("Acquiring", "ComputingHypercube", "Saving"):
            self.app.app_state = self.app.STATE_LABELS[state]
            self.app.load_parameter_preset()
            self.assertEqual(self.values(), original)
        self.app.app_state = "Ready"
        self.app.timelapse_thread = Mock(is_alive=Mock(return_value=True))
        self.app.load_parameter_preset()
        self.assertEqual(self.values(), original)
        self.app.app_state = "Paused"
        self.app.load_parameter_preset()
        self.assertEqual(self.values(), original)
        self.app.app_state = "Ready"
        self.app.timelapse_thread = None
        with self.app.parameter_apply_lock:
            self.app.load_parameter_preset()
        self.assertEqual(self.values(), original)

    def test_save_new_name_reload_and_overwrite_confirmation(self):
        self.app.parameter_preset_var.set("BF")
        self.app.load_parameter_preset()
        self.app.param_vars["bands"].set(1200)
        with patch("hera_app.mixins.ui_builder.simpledialog.askstring", return_value="My BF"), \
                patch("hera_app.mixins.ui_builder.messagebox.askyesno") as confirm:
            self.app.save_parameter_preset()
            confirm.assert_not_called()
        self.assertEqual(self.app.parameter_preset_var.get(), "My BF")
        self.assertIn("My BF", self.app.parameter_presets)
        other = PresetHost(self.path)
        try:
            other.parameter_preset_var.set("My BF")
            other.load_parameter_preset()
            self.assertEqual(other.param_vars["bands"].get(), 1200)
        finally:
            other.destroy()
        with patch("hera_app.mixins.ui_builder.simpledialog.askstring", return_value="BF"), \
                patch("hera_app.mixins.ui_builder.messagebox.askyesno", return_value=False):
            self.app.save_parameter_preset()
        self.assertEqual(load_parameter_presets(self.path, CHOICES)["BF"]["bands"], 1500)
        with patch("hera_app.mixins.ui_builder.simpledialog.askstring", return_value="BF"), \
                patch("hera_app.mixins.ui_builder.messagebox.askyesno", return_value=True):
            self.app.save_parameter_preset()
        self.assertEqual(load_parameter_presets(self.path, CHOICES)["BF"]["bands"], 1200)
        self.app.apply_parameters_async.assert_not_called()

    def test_cancellation_and_corrupted_file_do_not_overwrite(self):
        with patch("hera_app.mixins.ui_builder.simpledialog.askstring", return_value=None):
            self.app.save_parameter_preset()
        self.assertFalse(self.path.exists())
        self.path.write_text("broken JSON", encoding="utf-8")
        with patch("hera_app.mixins.ui_builder.simpledialog.askstring", return_value="BF"), \
                patch("hera_app.mixins.ui_builder.messagebox.showerror") as error:
            self.app.save_parameter_preset()
            error.assert_called_once()
        self.assertEqual(self.path.read_text(encoding="utf-8"), "broken JSON")
        other = PresetHost(self.path)
        try:
            self.assertEqual(other.parameter_presets, DEFAULT_PRESETS)
            other.log.assert_called_once()
        finally:
            other.destroy()

    def test_layout_both_themes_at_minimum_center_width(self):
        self.app.deiconify()
        for mode in ("dark", "light"):
            self.app.theme_mode = mode
            self.app._configure_theme()
            self.app._apply_theme_recursive(self.app)
            for width in (650, 820, 1050):
                with self.subTest(theme=mode, width=width):
                    self.app.geometry(f"{width}x260")
                    self.app.update()
                    control_bar = self.app.winfo_children()[0]
                    rows = sorted(control_bar.winfo_children(), key=lambda w: w.winfo_y())
                    self.assertEqual(len(rows), 3)
                    for previous, current in zip(rows, rows[1:]):
                        self.assertLessEqual(previous.winfo_y() + previous.winfo_height(), current.winfo_y())
                    for row in rows:
                        for cell in row.winfo_children():
                            self.assertGreaterEqual(cell.winfo_x(), 0)
                            self.assertLessEqual(cell.winfo_x() + cell.winfo_width(), row.winfo_width())


if __name__ == "__main__":
    unittest.main()
