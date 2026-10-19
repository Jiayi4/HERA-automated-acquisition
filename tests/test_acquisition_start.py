"""Exercise acquisition preparation with a fake SDK, never a connected camera."""

from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hera_app.mixins.acquisition import AcquisitionMixin


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class AcquisitionStartHost(AcquisitionMixin):
    SCAN_MODES = {"Low": 0, "Medium": 1, "High": 2, "Extra High": 3}
    TRIGGER_MODES = {"Internal": 0, "StepScanExtLoHi": 2}

    def __init__(self, mode="Medium", roi=None, helper=False, hdr=False, trigger="Internal"):
        self.controller = Mock(connected=True)
        self.controller.is_acquiring.return_value = False
        self.controller.is_live_capturing.return_value = False
        self.controller.is_hdr_supported.return_value = True
        self.controller.get_hdr.return_value = hdr
        self.hera_service_client = None
        self.helper_recovery_error = None
        self.processing_lock = threading.Lock()
        self.acquisition_start_lock = threading.Lock()
        self.parameter_apply_lock = threading.Lock()
        self.acquisition_done_event = threading.Event()
        self.param_vars = {
            "scan_mode": Value(mode), "trigger_mode": Value(trigger),
            "averages": Value(2), "stabilization": Value(0),
        }
        self.hdr_enabled_var = Value(hdr)
        self.hdr_status_var = Mock()
        self.check_license_status = Mock(return_value=True)
        self.hdr_mode_text = lambda value: "HDR" if value else "non-HDR"
        self.hdr_status_text = self.hdr_mode_text
        self._get_active_roi = lambda: roi
        self._apply_binning_roi_adjustment = lambda selected, _role: selected
        self.last_applied_roi = roi
        self._normalize_roi_tuple = lambda selected: selected
        self._format_roi = lambda selected: str(selected)
        self.log = Mock()
        self.update_state = Mock()
        self._start_single_acquisition_timer = Mock()
        self._stop_single_acquisition_timer = Mock()
        self._set_acquisition_inflight = Mock()
        self._release_current_sample_before_new_sample = Mock()
        self._cancel_pending_auto_apply_parameters = Mock()
        self._clear_saved_export_paths = Mock()
        self._start_busy_progress = Mock()
        self._set_run_progress = Mock()
        self._set_var_async = Mock()
        self._schedule_acquisition_heartbeat = Mock()
        self._schedule_acquisition_watchdog = Mock()
        self._log_large_acquisition_notice = Mock()
        self.apply_parameters = Mock(return_value=True)
        self._should_use_helper_acquisition = Mock(return_value=(helper, "test routing"))
        self._build_helper_request = Mock(return_value={"request_id": "fake-request"})
        self._start_helper_acquisition = Mock()
        self.save_pending_button = None


class AcquisitionStartTests(unittest.TestCase):
    def test_full_frame_sdk_start_in_all_spectral_modes(self):
        for mode, index in AcquisitionStartHost.SCAN_MODES.items():
            with self.subTest(mode=mode):
                host = AcquisitionStartHost(mode=mode)
                host._arm_and_start_acquisition(export_tag="test", auto_save=False)
                host.controller.start_hyperspectral_acquisition.assert_called_once_with(index, 0, 2, 0)
                host._log_large_acquisition_notice.assert_called_once_with(mode, index, False)
                self.assertIn(mode, host._start_busy_progress.call_args.args[0])
                self.assertIsNone(host.acquisition_requested_roi)
                self.assertFalse(host.acquisition_start_lock.locked())
                self.assertFalse(host.parameter_apply_lock.locked())

    def test_full_frame_flatfield_reaches_sdk_start(self):
        host = AcquisitionStartHost(mode="Extra High")
        host._arm_and_start_acquisition(acquisition_role="flatfield", auto_save=False)
        host.controller.start_hyperspectral_acquisition.assert_called_once_with(3, 0, 2, 0)
        host._release_current_sample_before_new_sample.assert_not_called()
        host._schedule_acquisition_watchdog.assert_called_once_with("flatfield")

    def test_non_helper_roi_start_keeps_selected_mode_and_roi(self):
        roi = (100, 200, 800, 600)
        host = AcquisitionStartHost(mode="Extra High", roi=roi)
        host._arm_and_start_acquisition()
        self.assertEqual(host.acquisition_requested_roi, roi)
        self.assertEqual(host.acquisition_camera_roi, roi)
        host.apply_parameters.assert_called_once_with(
            restart_live=False, apply_roi=True, hdr_enabled=False, reset_roi_before_set=False,
        )
        host.controller.start_hyperspectral_acquisition.assert_called_once_with(3, 0, 2, 0)

    def test_roi_helper_route_remains_separate(self):
        host = AcquisitionStartHost(mode="Extra High", roi=(100, 200, 800, 600), helper=True)
        host._arm_and_start_acquisition(export_tag="test")
        host._build_helper_request.assert_called_once_with("test", "sample", 3, 0, 2, 0)
        host._start_helper_acquisition.assert_called_once_with({"request_id": "fake-request"})
        host.apply_parameters.assert_not_called()
        host.controller.start_hyperspectral_acquisition.assert_not_called()

    def test_external_trigger_is_armed_with_same_selected_mode(self):
        host = AcquisitionStartHost(mode="High", trigger="StepScanExtLoHi")
        host._arm_and_start_acquisition()
        host.controller.start_hyperspectral_acquisition.assert_called_once_with(2, 2, 2, 0)
        host.update_state.assert_called_with("WaitingForTrigger")

    def test_hdr_readback_and_acquisition_values_are_preserved(self):
        host = AcquisitionStartHost(hdr=True)
        host._arm_and_start_acquisition()
        self.assertTrue(host.acquisition_pre_start_hdr)
        host.controller.set_hdr.assert_not_called()
        host.controller.start_hyperspectral_acquisition.assert_called_once_with(1, 0, 2, 0)

    def test_parameter_failure_does_not_start_sdk_or_leave_start_locks_held(self):
        host = AcquisitionStartHost()
        host.apply_parameters.return_value = False
        with self.assertRaisesRegex(RuntimeError, "Applying Hera parameters failed"):
            host._arm_and_start_acquisition()
        host.controller.start_hyperspectral_acquisition.assert_not_called()
        self.assertFalse(host.acquisition_start_lock.locked())
        self.assertFalse(host.parameter_apply_lock.locked())
        host._set_acquisition_inflight.assert_called_with(False)


if __name__ == "__main__":
    unittest.main()
