"""Fault injection only: never connect real hardware or load device adapters."""

import io
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hera_app.controllers.micro_z import MicroManagerZController
from hera_app.controllers.tango import TangoController
from hera_app.helpers.hera_service_client import HeraServiceClient
from hera_app.mixins.acquisition import AcquisitionMixin
from hera_app.mixins.device import DeviceMixin
from hera_app.mixins.micro_z_mixin import MicroManagerZMixin
from hera_app.mixins.stage import StageMixin
from hera_app.mixins.timelapse import TimelapseMixin, TimelapseStopped
from hera_app.safety import HardwareSafetyError, ZMotionCancelled, finite_float


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class FakeZCore:
    def __init__(self, arrival=None, busy=False):
        self.z = 100.0
        self.arrival = arrival
        self.busy = busy
        self.moves = []
        self.stop_count = 0
        self.poll_count = 0
        self.polled = threading.Event()

    def getPosition(self, _label):
        return self.z

    def setPosition(self, _label, target):
        self.moves.append(target)
        self.z = target if self.arrival is None else self.arrival

    def deviceBusy(self, _label):
        self.poll_count += 1
        self.polled.set()
        return self.busy

    def stop(self, _label):
        self.stop_count += 1
        self.busy = False


class FakeNikonCore(FakeZCore):
    def getDeviceLibrary(self, _label):
        return "NikonTI"

    def getDeviceName(self, _label):
        return "TIZDrive"


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def read(self):
        return self.now

    def wait(self, seconds):
        self.now += seconds
        return False


def z_controller(core):
    controller = MicroManagerZController()
    controller.core = core
    controller.connected = True
    return controller


class ZHost(MicroManagerZMixin):
    def __init__(self, controller):
        self.micro_z = controller
        self.micro_z_connected = True
        self.micro_z_request_lock = threading.Lock()
        self.micro_z_stop_generation = 0
        self.micro_z_min_var = Value("0")
        self.micro_z_max_var = Value("11000")
        self.micro_z_max_jump_var = Value("50")
        self.micro_z_tolerance_var = Value("0.5")
        self._safe_after = Mock()
        self._log_async = Mock()
        self._refresh_run_action_controls = Mock()

    def _get_micro_z_controller(self):
        return self.micro_z


class NumericSafetyTests(unittest.TestCase):
    def test_reject_nonfinite_values(self):
        for value in ("nan", "inf", "-inf", float("nan"), float("inf"), "", None):
            with self.subTest(value=value), self.assertRaises(HardwareSafetyError):
                finite_float(value, "Coordinate")

    def test_z_invalid_target_never_reaches_driver(self):
        core = FakeZCore()
        controller = z_controller(core)
        for value in (float("nan"), float("inf"), -float("inf")):
            with self.assertRaises(HardwareSafetyError):
                controller.move_abs(value)
        self.assertEqual(core.moves, [])
        self.assertEqual(core.poll_count, 0)

    def test_z_range_jump_and_settings_are_finite(self):
        host = ZHost(z_controller(FakeZCore()))
        self.assertIsNotNone(host._micro_z_validate_move_safety(float("nan"), 100))
        self.assertIsNotNone(host._micro_z_validate_move_safety(100, float("nan")))
        for name in ("micro_z_min_var", "micro_z_max_var", "micro_z_max_jump_var"):
            with self.subTest(name=name):
                var = getattr(host, name)
                old, var.value = var.value, "nan"
                with self.assertRaises(RuntimeError):
                    host._micro_z_validate_move_safety(110, 100)
                var.value = old
        self.assertIsNotNone(host._micro_z_validate_move_safety(11001, 100))
        self.assertIsNotNone(host._micro_z_validate_move_safety(151, 100))
        self.assertIsNone(host._micro_z_validate_move_safety(110, 100))

    def test_xy_invalid_values_rejected_before_any_dll_call(self):
        controller = object.__new__(TangoController)
        controller._require_connected = Mock()
        for x, y in ((float("nan"), 0), (0, float("inf"))):
            with self.assertRaises(HardwareSafetyError):
                controller.move_absolute_xy(x, y)
        with self.assertRaises(HardwareSafetyError):
            controller.apply_motion_settings(float("nan"), 1, 50)
        controller._require_connected.assert_not_called()
        with self.assertRaises(RuntimeError):
            StageMixin._parse_stage_float(None, Value("nan"), "Target X")


class ZArrivalAndStopTests(unittest.TestCase):
    def test_success_requires_two_idle_in_tolerance_reads(self):
        core = FakeZCore()
        self.assertEqual(z_controller(core).move_abs(110, settle_sec=0, timeout_sec=0.2), 110)
        self.assertGreaterEqual(core.poll_count, 2)
        self.assertEqual(core.moves, [110])

    def test_already_in_tolerance_still_confirmed_without_moving(self):
        core = FakeZCore()
        self.assertEqual(z_controller(core).move_abs(
            100.1, settle_sec=0, timeout_sec=0.2, skip_if_within_tolerance=True,
        ), 100)
        self.assertGreaterEqual(core.poll_count, 2)
        self.assertEqual(core.moves, [])

    def test_manual_sub_tolerance_step_is_not_skipped(self):
        core = FakeZCore()
        controller = z_controller(core)
        self.assertEqual(controller.move_abs(100.1, settle_sec=0, timeout_sec=0.2), 100.1)
        self.assertEqual(core.moves, [100.1])

    def test_busy_device_never_counts_as_arrived(self):
        core = FakeZCore(busy=True)
        with self.assertRaisesRegex(HardwareSafetyError, "arrival timeout"):
            z_controller(core).move_abs(110, settle_sec=0, timeout_sec=0.01)
        self.assertEqual(core.stop_count, 1)

    def test_unstable_arrival_resets_consecutive_confirmation(self):
        core = FakeZCore()
        core.getPosition = Mock(side_effect=[100, 110, 120, 110, 110])
        self.assertEqual(z_controller(core).move_abs(110, settle_sec=0, timeout_sec=0.5), 110)
        self.assertEqual(core.poll_count, 4)

    def test_wrong_readback_times_out_and_stops_instead_of_success(self):
        core = FakeZCore(arrival=150)
        with self.assertRaisesRegex(HardwareSafetyError, "arrival timeout"):
            z_controller(core).move_abs(110, settle_sec=0, timeout_sec=0.01)
        self.assertEqual(core.stop_count, 1)

    def test_nonfinite_readback_cannot_be_success(self):
        core = FakeZCore(arrival=float("nan"))
        with self.assertRaisesRegex(HardwareSafetyError, "finite"):
            z_controller(core).move_abs(110, settle_sec=0, timeout_sec=0.2)
        self.assertEqual(core.stop_count, 1)

    def test_stop_interrupts_busy_move_without_wait_for_device(self):
        core = FakeZCore(busy=True)
        controller = z_controller(core)
        errors = []

        def move():
            try:
                controller.move_abs(110, settle_sec=0, timeout_sec=1)
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=move)
        thread.start()
        try:
            self.assertTrue(core.polled.wait(0.5))
            self.assertEqual(controller.stop(), 110)
        finally:
            core.busy = False
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(core.stop_count, 1)
        self.assertIsInstance(errors[0], ZMotionCancelled)

    def test_ui_stop_does_not_wait_for_request_lock(self):
        core = FakeZCore()
        host = ZHost(z_controller(core))
        with host.micro_z_request_lock:
            host._micro_z_stop()
            for _ in range(100):
                if core.stop_count:
                    break
                threading.Event().wait(0.005)
            self.assertEqual(core.stop_count, 1)
        self.assertEqual(host.micro_z_stop_generation, 1)

    def test_pending_generation_cancelled_before_movement(self):
        core = FakeZCore()
        host = ZHost(z_controller(core))
        host.micro_z_stop_generation = 1
        with self.assertRaises(ZMotionCancelled):
            host._checked_micro_z_move(110, 0)
        self.assertEqual(core.moves, [])

    def test_driver_cancellation_check_before_setposition(self):
        core = FakeZCore()
        with self.assertRaises(ZMotionCancelled):
            z_controller(core).move_abs(110, cancel_check=lambda: True)
        self.assertEqual(core.moves, [])

    def test_unconfirmed_stop_blocks_new_movement(self):
        core = FakeZCore()
        core.stop = Mock(side_effect=RuntimeError("USB failed"))
        controller = z_controller(core)
        with self.assertRaisesRegex(HardwareSafetyError, "USB failed"):
            controller.stop()
        with self.assertRaises(HardwareSafetyError):
            controller.move_abs(110)
        self.assertEqual(core.moves, [])
        self.assertTrue(controller._stop_unconfirmed)

    def test_mixin_rejects_wrong_arrival_even_if_backend_claims_success(self):
        backend = Mock(get_z=Mock(return_value=100), move_abs=Mock(return_value=150))
        host = ZHost(backend)
        confirmed, status = host._move_z_to_position(110)
        self.assertIsNone(confirmed)
        self.assertIn("arrival rejected", status)


class NikonTICompatibilityTests(unittest.TestCase):
    def run_with_clock(self, controller, operation):
        clock = FakeClock()
        with patch("hera_app.controllers.micro_z.time.monotonic", side_effect=clock.read), \
                patch("hera_app.controllers.micro_z.time.sleep", side_effect=clock.wait), \
                patch.object(controller._stop_requested, "wait", side_effect=clock.wait):
            return operation(), clock.now

    def unsupported_stop(self, _label):
        raise RuntimeError('Error in device "TIZDrive": Unsupported device command (11)')

    def test_busy_stuck_at_measured_arrival_uses_half_second_stability(self):
        core = FakeNikonCore(arrival=110 - 0.025, busy=True)
        controller = z_controller(core)
        value, elapsed = self.run_with_clock(controller, lambda: controller.move_abs(110))
        self.assertAlmostEqual(value, 109.975)
        self.assertGreaterEqual(elapsed, 0.5)
        self.assertGreaterEqual(core.poll_count, controller.POSITION_STABLE_READS)
        self.assertEqual(controller.last_move_confirmation, "NikonTI stable position (Busy still true)")
        self.assertEqual(core.stop_count, 0)

    def test_wrong_target_is_not_accepted_even_when_nikon_position_stable(self):
        core = FakeNikonCore(arrival=150, busy=True)
        controller = z_controller(core)
        with self.assertRaisesRegex(HardwareSafetyError, "arrival timeout"):
            self.run_with_clock(controller, lambda: controller.move_abs(110, timeout_sec=0.7))

    def test_busy_compatibility_is_not_enabled_by_label_alone(self):
        core = FakeNikonCore(busy=True)
        core.getDeviceLibrary = lambda _: "DifferentAdapter"
        controller = z_controller(core)
        with self.assertRaisesRegex(HardwareSafetyError, "arrival timeout"):
            self.run_with_clock(controller, lambda: controller.move_abs(110, timeout_sec=0.7))

    def test_drift_within_tolerance_is_not_mistaken_for_stationary_arrival(self):
        core = FakeNikonCore(busy=True)
        controller = z_controller(core)
        values = iter([100, 109.6, 109.65, 109.7, 109.75, 109.8, 109.85, 109.9,
                       109.95, 110, 110.05, 110.1, 110.15, 110.2, 110.25, 110.3, 110.35])
        core.getPosition = lambda _: next(values, 110.4)
        with self.assertRaisesRegex(HardwareSafetyError, "arrival timeout"):
            self.run_with_clock(controller, lambda: controller.move_abs(110, timeout_sec=0.6))

    def test_unsupported_stop_only_recovers_after_stationary_readings(self):
        core = FakeNikonCore(busy=True)
        core.stop = Mock(side_effect=self.unsupported_stop)
        controller = z_controller(core)
        controller._stop_unconfirmed = True
        value, elapsed = self.run_with_clock(controller, controller.stop)
        self.assertEqual(value, 100)
        self.assertGreaterEqual(elapsed, 0.5)
        self.assertFalse(controller._stop_unconfirmed)
        self.assertFalse(controller._stop_command_supported)
        self.assertEqual(controller.last_stop_confirmation, "NikonTI position stationary (hardware Stop unsupported)")
        self.run_with_clock(controller, controller.stop)
        core.stop.assert_called_once()  # Do not repeat a known unsupported braking command.

    def test_unsupported_stop_does_not_hide_continued_motion(self):
        core = FakeNikonCore(busy=True)
        core.stop = Mock(side_effect=self.unsupported_stop)
        counter = iter(range(1000))
        core.getPosition = lambda _: 100 + next(counter) * 0.05
        controller = z_controller(core)
        with self.assertRaisesRegex(HardwareSafetyError, "stationary state could not be confirmed"):
            self.run_with_clock(controller, controller.stop)
        self.assertTrue(controller._stop_unconfirmed)

    def test_usb_error_does_not_enable_stop_fallback(self):
        core = FakeNikonCore()
        core.stop = Mock(side_effect=RuntimeError("USB disconnected"))
        controller = z_controller(core)
        with self.assertRaisesRegex(HardwareSafetyError, "USB disconnected"):
            self.run_with_clock(controller, controller.stop)
        self.assertTrue(controller._stop_unconfirmed)
        self.assertIsNone(controller.last_stop_confirmation)

    def test_invalid_readback_never_clears_latch_for_unsupported_stop(self):
        core = FakeNikonCore()
        core.stop = Mock(side_effect=self.unsupported_stop)
        core.z = float("nan")
        controller = z_controller(core)
        with self.assertRaisesRegex(HardwareSafetyError, "finite"):
            self.run_with_clock(controller, controller.stop)
        self.assertTrue(controller._stop_unconfirmed)

    def test_existing_latch_rejects_move_without_repeating_stop(self):
        core = FakeNikonCore()
        controller = z_controller(core)
        controller._stop_unconfirmed = True
        with self.assertRaisesRegex(HardwareSafetyError, "Previous Z stop"):
            controller.move_abs(110)
        self.assertEqual(core.moves, [])
        self.assertEqual(core.stop_count, 0)


class FakeProcess:
    def __init__(self, messages, reply=None, stubborn=False):
        self.returncode = None
        self.killed = False
        self.stubborn = stubborn
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.stdin = Mock()
        self.sent = threading.Event()

        def write(line):
            request = json.loads(line)
            self.sent.set()
            if reply:
                reply(request, messages)
        self.stdin.write.side_effect = write

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        if not self.stubborn:
            self.returncode = -9

    def wait(self, timeout):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake-helper", timeout)
        return self.returncode


class HelperSessionTests(unittest.TestCase):
    def client(self, reply=None, stubborn=False):
        client = HeraServiceClient()
        process = FakeProcess(client._messages, reply, stubborn)
        client.process = process
        return client, process

    def test_normal_rpc_and_stale_packets(self):
        def reply(request, messages):
            messages.put({"event": "result", "id": "old-request", "ok": True, "result": "stale"})
            messages.put({"event": "progress", "id": request["id"], "percent": 50})
            messages.put({"event": "result", "id": request["id"], "ok": True, "result": "fresh"})
        client, process = self.client(reply)
        progress = Mock()
        self.assertEqual(client.request("acquire", event_callback=progress), "fresh")
        progress.assert_called_once()
        self.assertFalse(process.killed)
        client.kill()

    def test_timeout_confirms_exit_before_raising(self):
        client, process = self.client()
        with self.assertRaisesRegex(RuntimeError, "Timed out"):
            client.request("acquire", timeout_sec=0.01)
        self.assertTrue(process.killed)
        self.assertIsNotNone(process.poll())
        self.assertIsNone(client.process)
        self.assertFalse(client.recovery_required)

    def test_unconfirmed_exit_keeps_process_and_blocks_restart(self):
        client, process = self.client(stubborn=True)
        with self.assertRaisesRegex(HardwareSafetyError, "exit unconfirmed"):
            client.request("acquire", timeout_sec=0.01)
        self.assertIs(client.process, process)
        self.assertTrue(client.recovery_required)
        with patch("hera_app.helpers.hera_service_client.subprocess.Popen") as spawn:
            with self.assertRaises(HardwareSafetyError):
                client.start()
            spawn.assert_not_called()

    def test_old_reader_and_cleanup_cannot_touch_new_session(self):
        client, old = self.client()
        old_messages = client._messages
        old.stdout = io.StringIO('{"event":"result","id":"expired","ok":true}\n')
        new_messages = queue.Queue()
        new = FakeProcess(new_messages)
        client.process, client._messages = new, new_messages
        client._read_stdout(old, old_messages)
        self.assertEqual(old_messages.get_nowait()["id"], "expired")
        self.assertTrue(new_messages.empty())
        client.kill(expected_process=old)
        self.assertFalse(new.killed)
        client.kill()

    def test_late_result_after_abort_is_discarded(self):
        client, old = self.client()
        errors = []

        def request():
            try:
                client.request("acquire", timeout_sec=1)
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=request)
        thread.start()
        self.assertTrue(old.sent.wait(0.5))
        client.kill()
        new_messages = queue.Queue()
        new = FakeProcess(new_messages)
        client.process, client._messages = new, new_messages
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(errors)
        self.assertFalse(new.killed)
        client.kill()

    def test_real_ipc_lifecycle_using_synthetic_child_only(self):
        script = "\n".join((
            "import json, sys, time",
            "print(json.dumps({'event':'ready','ok':True}), flush=True)",
            "for line in sys.stdin:",
            "    request = json.loads(line)",
            "    if request['command'] == 'hang': time.sleep(5)",
            "    print(json.dumps({'event':'result','id':request['id'],'ok':True,'result':request.get('value')}), flush=True)",
            "    if request['command'] == 'shutdown': break",
        ))
        real_popen = subprocess.Popen
        client = HeraServiceClient()
        self.addCleanup(client.kill)

        def spawn(_command, **kwargs):
            return real_popen([sys.executable, "-u", "-c", script], **kwargs)

        with patch("hera_app.helpers.hera_service_client.subprocess.Popen", side_effect=spawn):
            self.assertEqual(client.request("echo", value=123), 123)
            first = client.process
            with self.assertRaisesRegex(RuntimeError, "Timed out"):
                client.request("hang", timeout_sec=0.03)
            self.assertIsNotNone(first.poll())
            self.assertIsNone(client.process)
            self.assertEqual(client.request("echo", value=456), 456)
            second = client.process
            self.assertIsNot(first, second)
            client.shutdown()
            self.assertIsNotNone(second.poll())
            self.assertIsNone(client.process)


class AcquisitionHost(AcquisitionMixin):
    def __init__(self, client):
        self.controller = None
        self.hera_service_client = client
        self.helper_recovery_error = None
        self.helper_acquisition_request_id = "current"
        self.helper_acquisition_abort_expected = False
        self.hera_service_acquisition_inflight = True
        self.acquisition_done_event = threading.Event()
        self.acquisition_success = False
        self.last_acquisition_error = ""
        self.last_acquisition_exception = None
        self._get_hera_service_client = lambda: client
        self._log_async = Mock()
        self._log_helper_service_result = Mock()
        self._fail_run_progress = Mock()
        self._safe_after = Mock()
        self._set_acquisition_inflight = Mock()
        self._timelapse_thread_active = lambda: True
        self._finish_helper_acquisition_result = Mock()


class AcquisitionRecoveryTests(unittest.TestCase):
    def client(self):
        client = Mock()
        client.recovery_required = False
        client.request.side_effect = RuntimeError("Timed out waiting for helper response")
        return client

    def test_done_signal_waits_for_cleanup(self):
        client = self.client()
        host = AcquisitionHost(client)
        entered, release = threading.Event(), threading.Event()

        def cleanup():
            entered.set()
            if not release.wait(2):
                raise RuntimeError("test cleanup timed out")
        client.kill.side_effect = cleanup
        thread = threading.Thread(target=host._helper_service_acquisition_worker,
                                  args=({"request_id": "current", "auto_save": True},))
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertFalse(host.acquisition_done_event.is_set())
        finally:
            release.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(host.acquisition_done_event.is_set())
        self.assertIsNone(host.hera_service_client)

    def test_unconfirmed_cleanup_surfaces_safety_fault_and_blocks_reconnect(self):
        client = self.client()
        client.kill.side_effect = HardwareSafetyError("cannot reap process")
        host = AcquisitionHost(client)
        host._helper_service_acquisition_worker({"request_id": "current", "auto_save": False})
        self.assertIsInstance(host.helper_recovery_error, HardwareSafetyError)
        self.assertTrue(host.acquisition_done_event.is_set())
        self.assertIsInstance(host.last_acquisition_exception, HardwareSafetyError)
        self.assertIs(host.hera_service_client, client)
        host._safe_after.assert_called_once()  # Error UI only, no camera reconnect.
        with self.assertRaises(HardwareSafetyError):
            host._ensure_helper_recovered()
        client.kill.side_effect = None
        host._ensure_helper_recovered()
        self.assertIsNone(host.helper_recovery_error)

    def test_old_worker_does_not_clear_new_request_state(self):
        client = self.client()
        client.request.side_effect = None
        client.request.return_value = {"old": "result"}
        host = AcquisitionHost(client)
        host.helper_acquisition_request_id = "newer"
        host._helper_service_acquisition_worker({"request_id": "expired", "auto_save": True})
        self.assertEqual(host.helper_acquisition_request_id, "newer")
        self.assertTrue(host.hera_service_acquisition_inflight)
        self.assertFalse(host.acquisition_done_event.is_set())
        host._finish_helper_acquisition_result.assert_not_called()
        self.assertEqual(client.request.call_count, 1)  # No disconnect for an expired result.

    def test_main_connection_is_blocked_when_exit_unconfirmed(self):
        host = SimpleNamespace(helper_recovery_error=HardwareSafetyError("still alive"),
                               hera_service_client=None, log=Mock())
        with patch("hera_app.mixins.device.HeraController") as controller:
            DeviceMixin.connect_hera(host)
            controller.assert_not_called()

    def test_failed_abort_invalidates_request_but_retains_recovery_handle(self):
        client = self.client()
        client.kill.side_effect = HardwareSafetyError("cannot reap process")
        host = AcquisitionHost(client)
        host.log = Mock()
        host.update_state = Mock()
        host.abort_acquisition()
        self.assertIsNone(host.helper_acquisition_request_id)
        self.assertFalse(host.hera_service_acquisition_inflight)
        self.assertTrue(host.acquisition_done_event.is_set())
        self.assertIs(host.hera_service_client, client)
        self.assertIsInstance(host.last_acquisition_exception, HardwareSafetyError)

    def test_successful_worker_signals_done_only_after_result_finalization(self):
        client = self.client()
        client.request.side_effect = [{"cube": "result"}, {"connected": False}]
        host = AcquisitionHost(client)

        def finalize(*_args):
            self.assertFalse(host.acquisition_done_event.is_set())
            host.acquisition_success = True
        host._finish_helper_acquisition_result.side_effect = finalize
        host._helper_service_acquisition_worker({"request_id": "current", "auto_save": True})
        self.assertTrue(host.acquisition_done_event.is_set())
        self.assertTrue(host.acquisition_success)
        self.assertFalse(host.hera_service_acquisition_inflight)
        client.kill.assert_not_called()


class TimelapseSafetyTests(unittest.TestCase):
    def site_host(self):
        return SimpleNamespace(
            _ensure_helper_recovered=Mock(), stage_lock=threading.Lock(), tango=Mock(connected=True),
            apply_stage_motion_settings=Mock(return_value=True), log=Mock(), update_stage_position_display=Mock(),
            _set_var_async=Mock(), current_site_var=Mock(), timelapse_stop_event=threading.Event(),
            _timelapse_site_z_target=lambda _: (100, "pending"),
            _move_z_to_position=Mock(return_value=(100, "ok")), _log_async=Mock(),
            stage_dwell_var=Value(0), micro_z_stop_generation=0, _arm_and_start_acquisition=Mock(),
            _sanitize_export_tag=lambda value: value, _get_position_roi=lambda _: (10, 20, 100, 100),
            _format_roi=Mock(), timelapse_roi=None, _await_timelapse_acquisition_completion=lambda: "cube.hdr",
        )

    def test_safety_pause_retries_same_site_without_consuming_attempt_or_skip(self):
        position = SimpleNamespace(name="Site 2")
        host = SimpleNamespace(
            _timelapse_site_retry_count=lambda: 0,
            timelapse_stop_event=threading.Event(), timelapse_pause_event=threading.Event(),
            run_stage_site_acquisition=Mock(side_effect=[HardwareSafetyError("wrong Z"), ("cube.hdr", 100, 100, "ok")]),
            _log_async=Mock(), _current_stage_xy_strings=lambda: ("1", "2"),
            _record_trigger_log_entry=Mock(), _format_roi_short=lambda _: "full",
            _get_position_roi=lambda _: None, timelapse_roi=None,
        )

        def pause(*_args):
            host.timelapse_pause_event.set()
        host._pause_timelapse_for_safety = Mock(side_effect=pause)

        def resume():
            self.assertTrue(host.timelapse_pause_event.is_set())
            self.assertEqual(host.run_stage_site_acquisition.call_count, 1)
            host.timelapse_pause_event.clear()
        host._wait_while_paused = Mock(side_effect=resume)
        self.assertTrue(TimelapseMixin._run_site_with_retries(host, position, 1))
        host._pause_timelapse_for_safety.assert_called_once()
        self.assertEqual(host.run_stage_site_acquisition.call_args_list[0], host.run_stage_site_acquisition.call_args_list[1])
        self.assertEqual(host._record_trigger_log_entry.call_args.args[0]["Attempt"], 1)

    def test_helper_safety_fault_remains_typed_when_awaited(self):
        done = threading.Event()
        done.set()
        fault = HardwareSafetyError("helper exit unconfirmed")
        host = SimpleNamespace(
            _timelapse_acquisition_timeout_sec=lambda _: 1, acquisition_done_event=done,
            timelapse_stop_event=threading.Event(), acquisition_success=False,
            last_acquisition_exception=fault, last_acquisition_error=str(fault),
        )
        with self.assertRaises(HardwareSafetyError):
            TimelapseMixin._await_timelapse_acquisition_completion(host)

    def test_stop_z_during_dwell_prevents_acquisition(self):
        position = SimpleNamespace(name="Site 1", x=1, y=2)
        host = self.site_host()
        host.stage_dwell_var = Value(1)
        with patch("hera_app.mixins.timelapse.time.sleep", side_effect=lambda _: setattr(host, "micro_z_stop_generation", 1)):
            with self.assertRaisesRegex(HardwareSafetyError, "Stop Z"):
                TimelapseMixin.run_stage_site_acquisition(host, position)
        host._arm_and_start_acquisition.assert_not_called()

    def test_normal_site_keeps_xy_z_acquisition_order_and_roi(self):
        position = SimpleNamespace(name="Site 1", x=1, y=2)
        host = self.site_host()
        order = []
        host.tango.move_absolute_xy.side_effect = lambda *_: order.append("XY")
        host._move_z_to_position.side_effect = lambda *_args, **_kwargs: (order.append("Z") or (100, "ok"))
        host._arm_and_start_acquisition.side_effect = lambda **_: order.append("Acquire")
        self.assertEqual(TimelapseMixin.run_stage_site_acquisition(host, position, cycle_index=1),
                         ("cube.hdr", 100, 100, "ok"))
        self.assertEqual(order, ["XY", "Z", "Acquire"])
        self.assertEqual(host._arm_and_start_acquisition.call_args.kwargs["forced_roi"], (10, 20, 100, 100))

    def test_invalid_motion_settings_prevent_xy_and_acquisition(self):
        host = self.site_host()
        host.apply_stage_motion_settings.return_value = False
        with self.assertRaises(HardwareSafetyError):
            TimelapseMixin.run_stage_site_acquisition(host, SimpleNamespace(name="Site 1", x=1, y=2))
        host.tango.move_absolute_xy.assert_not_called()
        host._arm_and_start_acquisition.assert_not_called()

    def test_ordinary_failure_keeps_existing_retry_and_skip_behavior(self):
        position = SimpleNamespace(name="Site 1")
        host = SimpleNamespace(
            _timelapse_site_retry_count=lambda: 1, timelapse_stop_event=threading.Event(),
            run_stage_site_acquisition=Mock(side_effect=RuntimeError("ordinary acquisition failure")),
            _is_disk_full_error=lambda _: False, _log_async=Mock(), _safe_after=Mock(),
            _current_stage_xy_strings=lambda: ("1", "2"), _record_trigger_log_entry=Mock(),
            _format_roi_short=lambda _: "full", _get_position_roi=lambda _: None, timelapse_roi=None,
            _pause_timelapse_for_safety=Mock(),
        )
        with patch("hera_app.mixins.timelapse.time.sleep"):
            self.assertFalse(TimelapseMixin._run_site_with_retries(host, position, 1))
        self.assertEqual(host.run_stage_site_acquisition.call_count, 2)
        host._pause_timelapse_for_safety.assert_not_called()
        self.assertEqual(host._record_trigger_log_entry.call_args.args[0]["Status"], "failed")


if __name__ == "__main__":
    unittest.main()
