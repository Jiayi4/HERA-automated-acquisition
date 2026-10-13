"""Hardware-free dialog smoke tests; --preview opens a synthetic scan for visual QA."""

import copy
import json
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
from types import SimpleNamespace
from queue import SimpleQueue

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hera_app.mixins.live_view import LiveViewMixin
from hera_app.mixins.theme import ThemeMixin
from hera_app.mixins.tissue_scan import TissueScanMixin
from hera_app.mixins.timelapse import TimelapseMixin


class MockScanApp(tk.Tk, TissueScanMixin, LiveViewMixin, ThemeMixin):
    def __init__(self, theme="dark"):
        super().__init__()
        self.theme_mode = theme
        self._configure_theme()
        self.title("Tissue Scan Preview Host (No Hardware)")
        self.geometry("330x70+0+0")
        tk.Label(self, text="Simulated coordinates. No hardware connected.").pack(pady=16)
        self.live_frame_lock = threading.Lock()
        self.live_display_frame_size = (1000, 600)
        self.live_frame_info = (1000, 600, 12, 16)
        self.latest_live_frame = (1000, 600, b"", None)
        self.live_display_rotation_degrees = 90
        self._live_crop_offset = (0, 0)
        self.roi = (0, 0, 1000, 600)
        self.live_cross_enabled_var = tk.BooleanVar(value=True)
        self.live_profile_status_var = tk.StringVar()
        self.live_cross_point = (500, 300)
        self.live_roi_selecting = False
        self.param_vars = {"binning": tk.StringVar(value="None")}
        self.timelapse_thread = None
        self.positions = []
        self.timelapse_sites_var = tk.StringVar(value="all")
        self.micro_z_connected = True
        self.stage_lock = threading.Lock()
        self.tango = SimpleNamespace(connected=True, get_position=lambda: (0, 0, 0, 0))
        self.logs = []
        self.moves = []
        self.callbacks = SimpleQueue()
        self.current_site_var = tk.StringVar(value="-")
        self.app_state_var = tk.StringVar(value="Ready")
        self.latest_stage_xy = None
        self.test_cycles = []

    def _apply_position_roi_to_ui(self, position):
        self.roi = position.roi

    def run_one_cycle(self, positions_override=None):
        self.test_cycles.append(list(positions_override))

    def _get_current_z_or_nan(self):
        return 1000.0

    def _safe_after(self, _delay, callback):
        self.callbacks.put(callback)

    def finish_capture(self):
        limit = time.monotonic() + 2
        while self.callbacks.empty() and time.monotonic() < limit:
            time.sleep(0.01)
        self.callbacks.get_nowait()()

    def _capture_current_roi_for_position(self):
        return self.roi

    def _acquisition_busy_reason(self, **_kwargs):
        return None

    def _micro_z_validate_target_range(self, value):
        return None if 0 <= value <= 11000 else "Z outside safe range"

    def _schedule_live_render(self, **_kwargs):
        pass

    def _render_live_profiles(self):
        pass

    def refresh_positions_tree(self):
        pass

    def log(self, message):
        self.logs.append(message)

    def _move_stage_to_saved_position_async(self, position):
        self.moves.append(position)

    def seed_scan(self):
        self.open_tissue_scan_dialog()
        self.tissue_scan_dialog.title("Tissue Scan UI Test")
        self.tissue_scan_state["landmarks"] = {
            "A": (100, 100, 0, 0), "B": (400, 100, -0.5, 0), "C": (100, 600, 0, -0.3)
        }
        self.tissue_scan_state["boundaries"] = {
            "Left": (0, 1, 1000), "Right": (3, 1, 1002),
            "Top": (1.5, 0, 1001), "Bottom": (1.5, 2, 1003)
        }
        self.tissue_scan_state["focus"] = [(1.5, 1, 1006)]
        self._refresh_tissue_records()


class TissueDialogTests(unittest.TestCase):
    def setUp(self):
        self.app = MockScanApp()
        self.app.withdraw()
        self.app.seed_scan()
        self.app.update()

    def tearDown(self):
        self.app._close_tissue_layout()
        self.app.update_idletasks()
        self.app.destroy()

    def test_preview_generation_preserves_roi_and_real_z(self):
        self.app.preview_tissue_grid()
        self.app.update()
        self.assertTrue(self.app.tissue_scan_plan["tiles"])
        self.assertTrue(self.app.tissue_scan_canvas.find_all())
        self.app.generate_tissue_sites()
        self.assertTrue(self.app.positions)
        self.assertTrue(all(position.roi == self.app.roi and position.z_is_real for position in self.app.positions))

    def test_changed_roi_and_margin_require_new_preview(self):
        self.app.preview_tissue_grid()
        self.app.tissue_scan_margin.set("8")
        with self.assertRaisesRegex(ValueError, "Preview"):
            self.app._require_current_tissue_plan()
        self.app.roi = (0, 0, 500, 600)
        with self.assertRaisesRegex(ValueError, "ROI"):
            self.app._check_tissue_context()

    def test_boundary_center_and_capture_busy_guards(self):
        self.app.reset_live_cross_center()
        self.app._check_tissue_center()
        self.app.live_cross_point = (490, 300)
        with self.assertRaisesRegex(ValueError, "Center"):
            self.app._check_tissue_center()
        self.app.preview_tissue_grid()
        self.app.tissue_scan_capture_busy = True
        with self.assertRaisesRegex(ValueError, "Capture"):
            self.app._require_current_tissue_plan()

    def test_close_disarms_landmark_and_reopen_retains_same_roi_calibration(self):
        self.app.tissue_scan_pick = "B"
        self.app._close_tissue_scan_dialog()
        self.assertIsNone(self.app.tissue_scan_pick)
        self.app.open_tissue_scan_dialog()
        self.assertEqual(len(self.app.tissue_scan_state["landmarks"]), 3)

    def test_downsampled_crop_pixels_are_mapped_to_actual_roi(self):
        self.app.roi = (685, 1055, 1508, 1916)
        self.app.live_frame_info = (3200, 3200, 12, 16)
        self.app.latest_live_frame = (800, 800, b"", None)
        self.app.live_display_frame_size = (378, 480)
        self.app._live_crop_offset = (685, 1055)
        self.app.tissue_scan_state["signature"] = self.app._tissue_signature()
        px, py = self.app._tissue_roi_pixel(685 + 100, 1055 + 120)
        raw_x = (171 + 100 + 0.5) * 4 - 685 - 0.5
        raw_y = (263 + 120 + 0.5) * 4 - 1055 - 0.5
        self.assertAlmostEqual(px, 1915 - raw_y)
        self.assertAlmostEqual(py, raw_x)

    def test_boundary_capture_reads_xyz_off_ui_thread(self):
        self.app.reset_live_cross_center()
        self.app.capture_tissue_boundary("Left")
        self.assertTrue(self.app.tissue_scan_capture_busy)
        self.app.finish_capture()
        self.assertFalse(self.app.tissue_scan_capture_busy)
        xyz = self.app.tissue_scan_state["boundaries"]["Left"]
        self.assertAlmostEqual(xyz[2], 1000)
        self.assertTrue(any("boundary Left" in entry for entry in self.app.logs))

    def test_capture_finishing_after_close_cannot_change_reopened_dialog(self):
        self.app.reset_live_cross_center()
        old = self.app.tissue_scan_state["boundaries"]["Left"]
        self.app.capture_tissue_boundary("Left")
        self.app._close_tissue_scan_dialog()
        self.app.open_tissue_scan_dialog()
        self.app.finish_capture()
        self.assertEqual(self.app.tissue_scan_state["boundaries"]["Left"], old)

    def test_all_buttons_fit_minimum_window_in_both_themes(self):
        self.app.deiconify()
        self.app.tissue_scan_dialog.geometry("730x580")
        for theme in ("dark", "light"):
            self.app.theme_mode = theme
            self.app._configure_theme()
            self.app._apply_theme_recursive(self.app.tissue_scan_dialog)
            for tab in range(3):
                self.app.tissue_scan_notebook.select(tab)
                self.app.update()
                dialog = self.app.tissue_scan_dialog

                def check(widget):
                    if widget.winfo_class() == "Button" and widget.winfo_ismapped():
                        x = widget.winfo_rootx() - dialog.winfo_rootx()
                        y = widget.winfo_rooty() - dialog.winfo_rooty()
                        self.assertGreaterEqual(x, 0, widget.cget("text"))
                        self.assertGreaterEqual(y, 0, widget.cget("text"))
                        self.assertLessEqual(x + widget.winfo_width(), dialog.winfo_width(), widget.cget("text"))
                        self.assertLessEqual(y + widget.winfo_height(), dialog.winfo_height(), widget.cget("text"))
                    for child in widget.winfo_children():
                        check(child)

                check(dialog)

    def test_layout_tracks_site_and_stage_without_reading_hardware(self):
        self.app.preview_tissue_grid()
        self.app.generate_tissue_sites()
        self.app.update()
        self.assertTrue(self.app.tissue_layout_canvas.find_withtag("planned"))
        position = self.app.positions[1]
        self.app.current_site_var.set(position.name)
        self.app.latest_stage_xy = (position.x, position.y)
        self.app.app_state_var.set("Acquiring")
        self.app.tango.get_position = lambda: self.fail("Layout must not query hardware")
        self.app._update_tissue_layout_overlay()
        canvas = self.app.tissue_layout_canvas
        self.assertEqual(len(canvas.find_withtag("tracking")), 3)
        self.assertIn(position.name, self.app.tissue_layout_status.get())
        self.assertIn("Acquiring", self.app.tissue_layout_status.get())
        unchanged = canvas.find_withtag("tracking")
        self.app._update_tissue_layout_overlay()
        self.assertEqual(unchanged, canvas.find_withtag("tracking"))

    def test_generated_layout_survives_preview_changes_and_dialog_close(self):
        self.app.preview_tissue_grid()
        self.app.generate_tissue_sites()
        count = len(self.app.tissue_layout_plan["tiles"])
        self.app.tissue_scan_plan["tiles"].clear()
        self.app._close_tissue_scan_dialog()
        self.assertEqual(len(self.app.tissue_layout_plan["tiles"]), count)
        self.app._draw_tissue_layout()
        self.assertTrue(self.app.tissue_layout_canvas.find_withtag("planned"))

    def test_layout_follows_saved_site_rename_and_coordinate_update(self):
        self.app.preview_tissue_grid()
        self.app.generate_tissue_sites()
        position = self.app.positions[0]
        position.name = "Renamed"
        position.x += 0.1
        self.app._draw_tissue_layout()
        record = self.app.tissue_layout_drawn_records[0]
        self.assertEqual(record["name"], "Renamed")
        self.assertAlmostEqual(record["x"], position.x)
        self.assertNotEqual(record["u"], self.app.tissue_layout_plan["tiles"][0]["u"])

    def test_layout_hides_current_roi_when_context_differs_or_stage_disconnects(self):
        self.app.preview_tissue_grid()
        self.app.generate_tissue_sites()
        self.app.update()
        position = self.app.positions[0]
        self.app.latest_stage_xy = (position.x, position.y)
        self.app.current_site_var.set(position.name)
        self.app.roi = (0, 0, 500, 600)
        self.app._update_tissue_layout_overlay()
        self.assertIn("differs", self.app.tissue_layout_status.get())
        self.assertEqual(len(self.app.tissue_layout_canvas.find_withtag("tracking")), 1)
        self.app.tango.connected = False
        self.app._update_tissue_layout_overlay()
        self.assertIn("unavailable", self.app.tissue_layout_status.get())

    def test_closing_layout_cancels_polling(self):
        self.app.open_tissue_layout()
        job = self.app.tissue_layout_job
        self.assertIn(job, self.app.tk.call("after", "info"))
        self.app._close_tissue_layout()
        self.assertNotIn(job, self.app.tk.call("after", "info"))

    def test_exported_layout_round_trips_without_loading_runnable_sites(self):
        self.app.preview_tissue_grid()
        original = self.app.tissue_scan_plan
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "plan.json")
            with patch("hera_app.mixins.tissue_scan.filedialog.asksaveasfilename", return_value=path):
                self.app.export_tissue_plan()
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertEqual(data["plan"]["tiles"][0]["name"], "R001-C001")
            self.assertEqual(data["plan"]["rows"], original["rows"])
            self.app.open_tissue_layout()
            with patch("hera_app.mixins.tissue_scan.filedialog.askopenfilename", return_value=path):
                self.app.load_tissue_layout_plan()
            self.assertEqual(self.app.positions, [])
            self.assertEqual(len(self.app.tissue_layout_drawn_records), len(original["tiles"]))
            self.assertTrue(self.app.tissue_layout_canvas.find_withtag("planned"))

    def test_generate_from_loaded_plan_restores_exact_coordinates_without_calibration(self):
        self.app.preview_tissue_grid()
        plan = copy.deepcopy(self.app.tissue_scan_plan)
        self.app.open_tissue_layout()
        self.app.tissue_layout_plan = plan
        self.app.tissue_scan_state = None
        self.app.live_display_frame_size = None
        with patch("hera_app.mixins.tissue_scan.messagebox.showinfo"):
            self.app.generate_sites_from_tissue_plan()
        self.assertEqual(len(self.app.positions), len(plan["tiles"]))
        for position, tile in zip(self.app.positions, plan["tiles"]):
            self.assertEqual((position.x, position.y, position.z), (tile["x"], tile["y"], tile["z"]))
            self.assertEqual(position.roi, tuple(plan["signature"]["roi"]))
            self.assertTrue(position.z_is_real)
        self.assertEqual(self.app.moves, [])

    def test_restore_declined_replacement_keeps_existing_sites(self):
        self.app.preview_tissue_grid()
        self.app.generate_tissue_sites()
        existing = self.app.positions
        with patch("hera_app.mixins.tissue_scan.messagebox.askyesno", return_value=False):
            self.app.generate_sites_from_tissue_plan()
        self.assertIs(self.app.positions, existing)

    def test_restore_rejects_busy_unsafe_and_duplicate_plans_without_partial_changes(self):
        self.app.preview_tissue_grid()
        self.app.generate_tissue_sites()
        existing = self.app.positions
        original = copy.deepcopy(self.app.tissue_layout_plan)
        cases = []
        invalid = copy.deepcopy(original)
        invalid["tiles"][-1]["z"] = 12000
        cases.append(invalid)
        invalid = copy.deepcopy(original)
        invalid["tiles"][-1]["z_is_real"] = False
        cases.append(invalid)
        invalid = copy.deepcopy(original)
        invalid["tiles"][-1]["name"] = invalid["tiles"][0]["name"]
        cases.append(invalid)
        for invalid in cases:
            self.app.tissue_layout_plan = invalid
            with patch("hera_app.mixins.tissue_scan.messagebox.showerror") as error:
                self.app.generate_sites_from_tissue_plan()
            self.assertTrue(error.called)
            self.assertIs(self.app.positions, existing)
        self.app.tissue_layout_plan = original
        with patch.object(self.app, "_acquisition_busy_reason", return_value="acquisition active"), \
                patch("hera_app.mixins.tissue_scan.messagebox.showerror") as error:
            self.app.generate_sites_from_tissue_plan()
        self.assertTrue(error.called)
        self.assertIs(self.app.positions, existing)

    def test_save_current_plan_restores_manual_focus_roi_and_deleted_sites(self):
        self.app.preview_tissue_grid()
        self.app.generate_tissue_sites()
        refined = self.app.positions[0]
        refined.z += 7
        refined.name = "Refined"
        refined.roi = (10, 20, 800, 500)
        del self.app.positions[1]
        count = len(self.app.positions)
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "refined_plan.json")
            with patch("hera_app.mixins.tissue_scan.filedialog.asksaveasfilename", return_value=path):
                self.app.save_tissue_layout_plan()
            self.app.positions = []
            with patch("hera_app.mixins.tissue_scan.filedialog.askopenfilename", return_value=path):
                self.app.load_tissue_layout_plan()
            with patch("hera_app.mixins.tissue_scan.messagebox.showinfo"):
                self.app.generate_sites_from_tissue_plan()
            self.assertEqual(len(self.app.positions), count)
            restored = self.app.positions[0]
            self.assertEqual((restored.name, restored.z, restored.roi), (refined.name, refined.z, refined.roi))

    def test_layout_restore_controls_fit_minimum_window_in_both_themes(self):
        self.app.deiconify()
        self.app.open_tissue_layout()
        window = self.app.tissue_layout_window
        window.geometry("480x380")
        for theme in ("dark", "light"):
            self.app.theme_mode = theme
            self.app._configure_theme()
            self.app._apply_theme_recursive(window)
            self.app.update()
            buttons = []

            def check(widget):
                if widget.winfo_class() == "Button" and widget.winfo_ismapped():
                    buttons.append(widget.cget("text"))
                    x = widget.winfo_rootx() - window.winfo_rootx()
                    y = widget.winfo_rooty() - window.winfo_rooty()
                    self.assertGreaterEqual(x, 0)
                    self.assertGreaterEqual(y, 0)
                    self.assertLessEqual(x + widget.winfo_width(), window.winfo_width())
                    self.assertLessEqual(y + widget.winfo_height(), window.winfo_height())
                for child in widget.winfo_children():
                    check(child)

            check(window)
            self.assertEqual(set(buttons), {"Load Plan", "Save Plan", "Generate Sites", "Go To", "Update Z", "Run 2x2 Test"})

    def test_layout_click_selects_without_moving_and_go_to_uses_saved_xyz(self):
        self.app.preview_tissue_grid()
        self.app.generate_tissue_sites()
        self.app.update()
        tile = self.app.tissue_layout_drawn_records[1]
        x, y = self.app._tissue_layout_point(tile["u"], tile["v"])
        self.app._select_tissue_layout_tile(SimpleNamespace(x=x, y=y))
        self.assertEqual(self.app.tissue_layout_selected_cell, (tile["row"], tile["column"]))
        self.assertEqual(self.app.moves, [])
        self.app.goto_tissue_layout_tile()
        self.assertIs(self.app.moves[-1], self.app.positions[1])

    def test_layout_update_z_preserves_xy_and_roi(self):
        self.app.preview_tissue_grid()
        self.app.generate_tissue_sites()
        position = self.app.positions[0]
        old = (position.x, position.y, position.roi)
        self.app.tango.get_position = lambda: (position.x, position.y, 0, 0)
        self.app._get_current_z_or_nan = lambda: 1020.5
        self.app.update_tissue_layout_z()
        self.assertTrue(self.app.tissue_layout_z_update_busy)
        self.app.finish_capture()
        self.assertFalse(self.app.tissue_layout_z_update_busy)
        self.assertEqual((position.x, position.y, position.roi), old)
        self.assertEqual(position.z, 1020.5)

    def test_layout_update_z_rejects_wrong_xy_and_busy_acquisition(self):
        self.app.preview_tissue_grid()
        self.app.generate_tissue_sites()
        old = self.app.positions[0].z
        self.app.tango.get_position = lambda: (100, 100, 0, 0)
        self.app.update_tissue_layout_z()
        with patch("hera_app.mixins.tissue_scan.messagebox.showerror") as error:
            self.app.finish_capture()
        self.assertTrue(error.called)
        self.assertEqual(self.app.positions[0].z, old)
        with patch.object(self.app, "_acquisition_busy_reason", return_value="acquisition active"), \
                patch("hera_app.mixins.tissue_scan.messagebox.showerror") as error:
            self.app.goto_tissue_layout_tile()
            self.app.update_tissue_layout_z()
            self.app.run_tissue_2x2_test()
        self.assertEqual(error.call_count, 3)
        self.assertEqual(self.app.moves, [])
        self.assertEqual(self.app.test_cycles, [])

    def test_layout_two_by_two_test_does_not_change_site_selection(self):
        self.app.preview_tissue_grid()
        self.app.generate_tissue_sites()
        self.app.timelapse_sites_var.set("all")
        self.app.run_tissue_2x2_test()
        self.assertEqual(len(self.app.test_cycles[-1]), 4)
        self.assertEqual(self.app.timelapse_sites_var.get(), "all")
        self.assertEqual({p.name for p in self.app.test_cycles[-1]}, {"R001-C001", "R001-C002", "R002-C001", "R002-C002"})

    def test_one_loop_override_uses_normal_validation_and_worker(self):
        self.app.preview_tissue_grid()
        self.app.generate_tissue_sites()
        chosen = self.app.positions[:4]

        def runner(export_ok=True):
            return SimpleNamespace(
                timelapse_thread=None, log=Mock(), _timelapse_selected_positions=Mock(return_value=self.app.positions),
                _validate_auto_save_export_options=Mock(return_value=export_ok),
                _validate_timelapse_z_plan=Mock(return_value=True), timelapse_stop_event=Mock(),
                timelapse_pause_event=Mock(), _begin_trigger_log_file=Mock(), total_run_time_var=Mock(),
                _get_active_roi=Mock(return_value=self.app.roi), pause_button=Mock(), timelapse_status_var=Mock(),
                update_state=Mock(), _begin_timelapse_run=Mock(return_value=42), _timelapse_worker=Mock(),
                _timelapse_site_selection_label=Mock(return_value="test"), _roi_plan_message=Mock(return_value="ROI"),
                _z_plan_message=Mock(return_value="Z"), _export_selection_text=Mock(return_value="raw"),
            )

        for override, expected in ((chosen, chosen), (None, self.app.positions)):
            host = runner()
            with patch("hera_app.mixins.timelapse.threading.Thread") as thread:
                TimelapseMixin.run_one_cycle(host, positions_override=override)
                thread.assert_called_once_with(target=host._timelapse_worker, args=(True, expected, 42), daemon=True)
                thread.return_value.start.assert_called_once()
            host._validate_auto_save_export_options.assert_called_once()
            host._validate_timelapse_z_plan.assert_called_once_with(expected)
            self.assertEqual(host._timelapse_selected_positions.call_count, int(override is None))

        host = runner(export_ok=False)
        with patch("hera_app.mixins.timelapse.threading.Thread") as thread:
            TimelapseMixin.run_one_cycle(host, positions_override=chosen)
            thread.assert_not_called()


if __name__ == "__main__":
    if "--preview" in sys.argv:
        app = MockScanApp("light" if "--light" in sys.argv else "dark")
        app.seed_scan()
        app.preview_tissue_grid()
        app.tissue_scan_dialog.geometry("790x650+360+40")
        app.tissue_scan_dialog.protocol("WM_DELETE_WINDOW", app.destroy)
        app.after(180000, app.destroy)
        app.mainloop()
    else:
        unittest.main()
