"""Native Live View tests using synthetic pixels, never camera hardware."""

import ctypes
import struct
import sys
import tempfile
import threading
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hera_app.mixins import live_view
from hera_app.mixins.live_view import LiveViewMixin
from hera_app.mixins.roi import ROIMixin


class PixelHost(LiveViewMixin, ROIMixin):
    def __init__(self):
        self.live_max_preview_width = 0


class LiveHDRVerificationTests(unittest.TestCase):
    def setUp(self):
        self.host = PixelHost()
        self.host.live_hdr_verification = None
        self.host.live_pixel_format_name = "Mono16"
        self.host.hdr_mode_text = lambda flag, **kwargs: "Dynamic Range HDR" if flag else "Sensitivity 12-bit"
        self.host._log_async = Mock()
        self.requested = True

    def observe(self, flag, now):
        self.host._update_live_hdr_verification(flag, self.requested, now)
        return self.host._live_frame_mode_text(flag, self.requested, 16, 16, 32768)

    def messages(self):
        return [call.args[0] for call in self.host._log_async.call_args_list]

    def test_first_frame_disagreement_recovers_without_warning(self):
        self.assertIn("verifying", self.observe(False, 0.0))
        self.assertIn("verifying", self.observe(True, 0.1))
        self.observe(True, 0.3)
        self.assertIn("verified", self.observe(True, 0.7))
        self.assertFalse(any("warning" in m for m in self.messages()))
        self.assertEqual(sum("Live HDR verified" in m for m in self.messages()), 1)
        self.assertTrue(any("(recovered)" in m for m in self.messages()))
        self.observe(True, 1.0)
        self.assertEqual(sum("Live HDR verified" in m for m in self.messages()), 1)

    def test_confirmation_requires_both_count_and_stable_time(self):
        for t in (0.0, 0.05, 0.1):
            self.assertIn("verifying", self.observe(True, t))
        self.assertIn("verified", self.observe(True, 0.6))
        self.host.live_hdr_verification = None
        self.assertIn("verifying", self.observe(True, 10.0))
        self.assertIn("verifying", self.observe(True, 11.0))
        self.assertIn("verified", self.observe(True, 12.0))

    def test_persistent_mismatch_warns_once_and_later_recovers(self):
        for t in (0.0, 1.0, 4.9):
            self.assertIn("verifying", self.observe(False, t))
        self.assertIn("mismatch", self.observe(False, 5.0))
        self.observe(False, 6.0)
        self.assertEqual(sum("verification warning" in m for m in self.messages()), 1)
        self.assertTrue(any("persistent mismatch" in m and "frameHDR=False" in m for m in self.messages()))
        self.observe(True, 6.1)
        self.observe(True, 6.3)
        self.assertIn("verified", self.observe(True, 6.8))
        self.assertTrue(any("(recovered)" in m for m in self.messages()))
        self.assertFalse(self.host.live_hdr_verification["warned"])

    def test_unknown_flag_is_never_verified_or_assumed_off(self):
        self.requested = False
        self.observe(None, 0.0)
        self.assertIn("unverified", self.observe(None, 5.0))
        self.observe(None, 8.0)
        self.assertEqual(sum("verification warning" in m for m in self.messages()), 1)
        self.assertTrue(any("flag unavailable" in m and "frameHDR=None" in m for m in self.messages()))
        self.assertFalse(any("Live HDR verified" in m for m in self.messages()))

    def test_mismatch_after_verified_starts_a_new_verification_window(self):
        for t in (0.0, 0.2, 0.6):
            self.observe(True, t)
        self.assertIn("verifying", self.observe(False, 100.0))
        self.assertIn("verifying", self.observe(False, 104.9))
        self.assertIn("mismatch", self.observe(False, 105.0))
        self.assertEqual(sum("verification warning" in m for m in self.messages()), 1)

    def test_interleaved_frames_do_not_accumulate_as_stable_matches(self):
        self.observe(False, 0.0)
        self.observe(True, 1.0)
        self.observe(True, 1.1)
        self.observe(False, 1.2)
        self.observe(True, 3.0)
        self.observe(True, 3.1)
        self.assertIn("mismatch", self.observe(False, 5.0))
        self.assertFalse(any("Live HDR verified" in m for m in self.messages()))

    def test_off_request_and_changed_target_do_not_reuse_previous_confirmation(self):
        for t in (0.0, 0.2, 0.6):
            self.observe(True, t)
        self.requested = False
        self.assertIn("verifying", self.observe(True, 10.0))
        self.observe(False, 10.1)
        self.observe(False, 10.3)
        mode = self.observe(False, 10.8)
        self.assertIn("Sensitivity 12-bit (verified)", mode)
        self.assertEqual(sum("Live HDR verified" in m for m in self.messages()), 2)

    def test_start_resets_verification_before_sdk_can_deliver_frames(self):
        host = self.host
        host.controller = Mock()
        host.controller.connected = True
        host.controller.is_live_capturing.return_value = False
        host.controller.is_pixel_format_supported.return_value = True
        host.hdr_enabled_var = Mock(get=Mock(return_value=True))
        host.LIVE_PIXEL_FORMATS = {3: "Mono16"}
        host.live_watchdog_job = None
        host._safe_after = Mock()
        host._set_live_view_status = Mock()
        host.log = Mock()
        host.live_hdr_verification = {"phase": "verified"}

        def sdk_start(**kwargs):
            self.assertIsNone(host.live_hdr_verification)
            self.assertFalse(host.live_first_frame_logged)
            self.assertFalse(host.live_first_frame_rendered)
            self.assertTrue(host.live_hdr_requested)
            host.live_first_frame_logged = True

        host.controller.start_live_capture.side_effect = sdk_start
        host.start_live_view()
        self.assertTrue(host.live_first_frame_logged)
        host.controller.start_live_capture.assert_called_once_with(pixel_format=3)
        host.controller.set_hdr.assert_not_called()


@unittest.skipIf(live_view.np is None, "Native preview requires NumPy")
class LivePixelTests(unittest.TestCase):
    def setUp(self):
        self.host = PixelHost()

    def test_native_frame_preserves_pixel_skipped_by_old_preview(self):
        raw = bytearray(3200 * 3200 * 2)
        index = 3200 + 1
        struct.pack_into("<H", raw, index * 2, 4095)
        self.assertEqual(self.host._live_preview_scale(3200), 1)
        gray, w, h, mask = self.host._extract_live_preview_bytes(raw, 3200, 3200, 6400, 2, 12, 16, 2048, 1)
        self.assertEqual((w, h), (3200, 3200))
        self.assertEqual(gray[index], 255)
        self.assertEqual(mask[index], 1)
        with patch.object(live_view, "np", None):
            self.assertEqual(self.host._live_preview_scale(3200), 7)

    def test_decoder_matches_python_for_depth_padding_and_saturation(self):
        for bpp, depth, threshold, values in (
            (1, 8, 128, [0, 1, 127, 128, 255]),
            (2, 12, 2048, [0, 15, 2047, 2048, 4095]),
            (2, 12, 32768, [0, 4095, 8192, 32768, 65535]),
            (4, 20, 524288, [0, 4095, 524287, 524288, 1048575]),
        ):
            raw = b"".join(v.to_bytes(bpp, "little") for v in values) + b"\0\0\0"
            raw *= 3
            for scale in (1, 2):
                args = (raw, 5, 3, 5 * bpp + 3, bpp, depth, bpp * 8, threshold, scale)
                with self.subTest(bpp=bpp, threshold=threshold, scale=scale):
                    actual = self.host._extract_live_preview_bytes(*args)
                    with patch.object(live_view, "np", None):
                        expected = self.host._extract_live_preview_bytes(*args)
                    self.assertEqual(actual, expected)

    def test_shared_pixel_operations_match_python(self):
        gray, mask = bytes(range(35)), bytes(int(i % 3 == 0) for i in range(35))
        for rotation in (0, 90, 180, 270):
            self.host.live_display_rotation_degrees = rotation
            actual = self.host._orient_live_display_bytes(gray, 7, 5, mask)
            with patch.object(live_view, "np", None):
                expected = self.host._orient_live_display_bytes(gray, 7, 5, mask)
            self.assertEqual(actual, expected)
        actual = self.host._grayscale_to_rgb_bytes(gray, 7, 5, 19, 13, mask)
        normalized = self.host._normalize_grayscale_for_display(gray)
        with patch.object(live_view, "np", None):
            self.assertEqual(actual, self.host._grayscale_to_rgb_bytes(gray, 7, 5, 19, 13, mask))
            self.assertEqual(normalized, self.host._normalize_grayscale_for_display(gray))
        self.assertEqual(self.host._normalize_grayscale_for_display(b"\x08" * 8), (b"\x08" * 8, 8, 8))

    def test_viewport_matches_crop_of_full_scaled_image(self):
        gray = bytes(range(35))
        for ow, oh, bounds in ((19, 13, (3, 2, 14, 10)), (4, 3, (0, 0, 4, 3)), (7, 5, (1, 1, 6, 4))):
            full = self.host._resample_grayscale_nearest(gray, 7, 5, ow, oh)
            x0, y0, x1, y1 = bounds
            expected = b"".join(full[y * ow + x0:y * ow + x1] for y in range(y0, y1))
            self.assertEqual(self.host._sample_live_viewport(gray, 7, 5, ow, oh, bounds), expected)
            with patch.object(live_view, "np", None):
                self.assertEqual(self.host._sample_live_viewport(gray, 7, 5, ow, oh, bounds), expected)

    def callback_host(self):
        host = self.host
        host.is_closing = False
        host.live_accept_frames = True
        host.live_decode_lock = threading.Lock()
        host.live_frame_lock = threading.Lock()
        host.last_live_decode_time = 0
        host.live_render_interval_sec = 0.1
        host.latest_live_frame = None
        host.live_photo = None
        host.live_first_frame_logged = True
        host.live_pixel_format_name = "Mono12"
        host.live_hdr_requested = False
        host.last_live_decode_error = ""
        host._log_async = Mock()
        host._set_live_view_status = Mock()
        host._schedule_live_render = Mock()
        host.hdr_mode_text = lambda flag, **kwargs: "HDR" if flag else "Sensitivity"
        host.raw = ctypes.create_string_buffer(struct.pack("<6H", 0, 16, 32, 2048, 4095, 48))
        host.controller = Mock()
        host.controller.get_live_capture_is_hdr.return_value = False
        host.controller.get_live_capture_info.return_value = dict(
            data_ptr=ctypes.addressof(host.raw), width=3, height=2, bit_depth=12,
            bits_per_pixel=16, row_stride=6, saturation_threshold=2048)
        return host

    def test_throttled_busy_and_closed_callbacks_release_sdk_handles(self):
        host = self.callback_host()
        with patch.object(live_view.time, "monotonic", side_effect=[1.0, 1.01, 1.11]):
            host.on_live_capture_frame(1)
            first = host.latest_live_frame
            host.on_live_capture_frame(2)
            self.assertIs(host.latest_live_frame, first)
            host.on_live_capture_frame(3)
        self.assertEqual(host.controller.get_live_capture_info.call_count, 2)
        self.assertEqual(first[:2], (3, 2))
        host.live_decode_lock.acquire()
        host.on_live_capture_frame(4)
        self.assertTrue(host.live_decode_lock.locked())
        host.live_decode_lock.release()
        host.is_closing = True
        host.on_live_capture_frame(5)
        self.assertEqual(host.controller.release_live_capture_result.call_count, 5)
        self.assertFalse(host.live_decode_lock.locked())
        host._log_async.assert_not_called()

    def test_callback_checks_accepted_frames_without_extra_camera_configuration_calls(self):
        host = self.callback_host()
        host.live_hdr_requested = True
        host.live_pixel_format_name = "Mono16"
        host.controller.get_live_capture_is_hdr.side_effect = [False, True, True, True]
        with patch.object(live_view.time, "monotonic", side_effect=[1.0, 1.01, 1.11, 1.36, 1.71]):
            for handle in range(5):
                host.on_live_capture_frame(handle)
        self.assertEqual(host.controller.get_live_capture_is_hdr.call_count, 4)
        self.assertEqual(host.controller.release_live_capture_result.call_count, 5)
        host.controller.set_hdr.assert_not_called()
        host.controller.get_hdr.assert_not_called()
        self.assertTrue(host.latest_live_is_hdr)
        self.assertIn("(verified)", host.latest_live_mode_text)
        self.assertFalse(any("warning" in call.args[0] for call in host._log_async.call_args_list))

    def test_decoder_failure_releases_handle_and_decode_lock(self):
        host = self.callback_host()
        host.controller.get_live_capture_info.side_effect = RuntimeError("synthetic decode failure")
        host.on_live_capture_frame(1)
        self.assertFalse(host.live_decode_lock.locked())
        host.controller.release_live_capture_result.assert_called_once_with(1)
        self.assertIn("synthetic decode failure", host._log_async.call_args.args[0])

    def raw_frame(self, pixels, depth=16, threshold=32768):
        pixels = live_view.np.asarray(pixels)
        return dict(pixels=pixels, frame_width=pixels.shape[1], frame_height=pixels.shape[0],
                    bit_depth=depth, bits_per_pixel=pixels.dtype.itemsize * 8, saturation_threshold=threshold)

    def configure_mapping(self, auto=True, gamma=1.0):
        self.host.live_autocontrast_var = Mock(get=Mock(return_value=auto))
        self.host.live_gamma_var = Mock(get=Mock(return_value=gamma))

    def test_low_signal_hdr_retains_all_256_levels_before_final_display_conversion(self):
        np = live_view.np
        pixels = np.arange(500, 756, dtype="<u2").reshape(16, 16)
        raw = self.raw_frame(pixels)
        gray, _, _, _ = self.host._extract_live_preview_bytes(pixels.tobytes(), 16, 16, 32, 2, 16, 16, 32768, 1)
        self.configure_mapping()
        old = self.host._prepare_live_display_bytes(gray)
        new = self.host._prepare_live_display_bytes(gray, raw)
        self.assertEqual(len(set(old)), 2)
        self.assertEqual(new, bytes(range(256)))
        self.assertEqual(self.host.live_display_intensity_mapping, (500, 755, 500, 755, True, 1.0))

    def test_gamma_and_auto_off_operate_before_quantization(self):
        np = live_view.np
        pixels = np.array([[0, 1, 64, 256, 512, 1024, 2048, 4095]], dtype="<u2")
        original = pixels.copy()
        for auto in (False, True):
            for gamma in (0.5, 1.0, 2.0):
                self.configure_mapping(auto, gamma)
                raw = self.raw_frame(pixels, depth=12, threshold=2048)
                mapped = self.host._prepare_live_display_bytes(bytes(pixels.size), raw)
                expected = bytes(int(round((int(value) / 4095) ** (1 / gamma) * 255)) for value in pixels.flat)
                self.assertEqual(mapped, expected)
        np.testing.assert_array_equal(pixels, original)
        self.configure_mapping(False, 2.0)
        # Raw value 1 survives Gamma, although the old 12-bit -> 8-bit shift discards it.
        self.assertGreater(self.host._prepare_live_display_bytes(bytes(pixels.size), self.raw_frame(pixels, 12, 2048))[1], 0)

    def test_software_roi_is_cropped_before_raw_autocontrast(self):
        np = live_view.np
        pixels = np.arange(100, 164, dtype="<u2").reshape(8, 8)
        pixels[0, 0] = 65535
        self.configure_mapping()
        raw = self.raw_frame(pixels)
        roi = (2, 3, 4, 3)
        selected = pixels[3:6, 2:6]
        mapped = self.host._prepare_live_display_bytes(bytes(selected.size), raw, roi)
        lo, hi = int(selected.min()), int(selected.max())
        self.assertEqual(self.host.live_display_intensity_mapping[:4], (lo, hi, lo, hi))
        self.assertEqual(mapped, bytes(int(round((int(v) - lo) * 255 / (hi - lo))) for v in selected.flat))

    def test_camera_roi_is_not_cropped_twice_and_raw_padding_is_ignored(self):
        np = live_view.np
        values = np.arange(1000, 1015, dtype="<u2").reshape(3, 5)
        buffer = b"".join(row.tobytes() + b"\xff\xff" for row in values)
        view = self.host._live_raw_sample_view(buffer, 5, 3, 12, 2, 1)
        self.configure_mapping()
        mapped = self.host._prepare_live_display_bytes(bytes(15), self.raw_frame(view), (2, 1, 5, 3))
        self.assertEqual(self.host.live_display_intensity_mapping[:2], (1000, 1014))
        self.assertEqual(len(mapped), 15)
        self.assertFalse(view.flags.writeable)
        self.assertEqual(buffer[-2:], b"\xff\xff")

    def test_sampled_raw_crop_has_same_geometry_as_existing_byte_crop(self):
        np = live_view.np
        values = np.arange(30 * 40, dtype="<u2").reshape(30, 40)
        raw_view = self.host._live_raw_sample_view(values.tobytes(), 40, 30, 80, 2, 3)
        raw = self.raw_frame(raw_view)
        raw.update(frame_width=40, frame_height=30)
        roi = (5, 7, 19, 17)
        legacy_gray = (raw_view % 256).astype(np.uint8).tobytes()
        cropped, _, w, h, _, _ = self.host._crop_live_frame_bytes(
            legacy_gray, None, raw_view.shape[1], raw_view.shape[0], 40, 30, *roi)
        selected = self.host._live_raw_samples_for_roi(raw, roi)
        self.assertEqual(selected.shape, (h, w))
        self.assertEqual((selected % 256).astype(np.uint8).tobytes(), cropped)

    def test_saturation_uses_raw_sdk_threshold_not_display_brightness(self):
        np = live_view.np
        pixels = np.array([[100, 2047, 2048, 4095]], dtype="<u2")
        gray, w, h, mask = self.host._extract_live_preview_bytes(pixels.tobytes(), 4, 1, 8, 2, 12, 16, 2048, 1)
        self.assertEqual(mask, b"\x00\x00\x01\x01")
        self.configure_mapping(True, 2.0)
        mapped = self.host._prepare_live_display_bytes(gray, self.raw_frame(pixels, 12, 2048))
        rgb = self.host._grayscale_to_rgb_bytes(mapped, w, h, w, h, mask)
        self.assertEqual(rgb[-6:], b"\xff\x00\x00" * 2)
        self.assertNotEqual(rgb[3:6], b"\xff\x00\x00")

    def test_owned_raw_frame_survives_sdk_buffer_release_and_matches_frame_identity(self):
        host = self.callback_host()
        self.configure_mapping()
        host.on_live_capture_frame(1)
        raw = host.latest_live_raw_frame
        saved = raw["pixels"].tobytes()
        ctypes.memset(ctypes.addressof(host.raw), 255, ctypes.sizeof(host.raw))
        self.assertEqual(raw["pixels"].tobytes(), saved)
        self.assertIs(raw["frame"], host.latest_live_frame)
        self.assertFalse(raw["pixels"].flags.writeable)
        host.controller.release_live_capture_result.assert_called_once_with(1)

    def test_clearing_live_state_discards_raw_and_display_frame_together(self):
        host = self.callback_host()
        host.on_live_capture_frame(1)
        self.assertIsNotNone(host.latest_live_raw_frame)
        host.live_cross_enabled_var = Mock(get=Mock(return_value=False))
        host.live_profile_status_var = Mock()
        host.live_cursor_var = Mock()
        host._live_cursor_status_text = lambda text: text
        host.live_watchdog_job = None
        host._clear_live_view_frame_state()
        self.assertIsNone(host.latest_live_raw_frame)
        self.assertIsNone(host.latest_live_frame)
        self.assertIsNone(host.latest_live_profile)
        self.assertIsNone(host.live_display_intensity_mapping)
        self.assertIsNone(host.live_hdr_verification)
        self.assertIsNone(host.latest_live_is_hdr)

    def test_8bit_input_maps_without_changing_source_values(self):
        np = live_view.np
        pixels = np.array([[0, 17, 63, 128, 192, 255]], dtype="u1")
        self.configure_mapping(False, 1.0)
        result = self.host._prepare_live_display_bytes(bytes(pixels.size), self.raw_frame(pixels, 8, 255))
        self.assertEqual(result, pixels.tobytes())

    def test_constant_and_32bit_raw_frames_handle_auto_and_black(self):
        np = live_view.np
        self.configure_mapping()
        for value in (0, 1000, 65535):
            pixels = np.full((3, 4), value, dtype="<u2")
            result = self.host._prepare_live_display_bytes(bytes(12), self.raw_frame(pixels))
            self.assertEqual(set(result), {int(round(value * 255 / 65535))})
        pixels = np.tile(np.arange(6, dtype="<u4"), (70, 1))
        result = self.host._prepare_live_display_bytes(bytes(pixels.size), self.raw_frame(pixels, 32, 2 ** 31))
        self.assertEqual(result, bytes([0, 51, 102, 153, 204, 255]) * 70)

    def test_profile_uses_sensor_offset_only_for_camera_cropped_roi(self):
        host = self.host
        host.live_frame_lock = threading.Lock()
        host.live_horizontal_profile_canvas = host.live_vertical_profile_canvas = Mock()
        host._draw_horizontal_profile = Mock()
        host._draw_vertical_profile = Mock()
        host.live_cursor_image_xy = None
        host.live_view_crop_roi = (2, 3, 5, 4)
        host.live_cross_point = (4, 4)
        host.live_frame_info = (5, 4, 12, 16)
        host.latest_live_profile = (5, 4, bytes(range(20)), 128)
        host._render_live_profiles()
        self.assertEqual(host._draw_horizontal_profile.call_args.args[0], bytes(range(5, 10)))
        self.assertEqual(host._draw_vertical_profile.call_args.args[0], bytes([2, 7, 12, 17]))
        host.live_frame_info = (10, 10, 12, 16)
        host.latest_live_profile = (10, 10, bytes(range(100)), 128)
        host._render_live_profiles()
        self.assertEqual(host._draw_horizontal_profile.call_args.args[0], bytes(range(40, 50)))


class SyntheticLiveApp(tk.Tk, LiveViewMixin, ROIMixin):
    def __init__(self):
        super().__init__()
        self.title("Synthetic Live View - No Hardware")
        self.geometry("640x480+0+0")
        self.live_view_canvas = tk.Canvas(self, highlightthickness=0)
        self.live_view_canvas.pack(fill="both", expand=True)
        self.live_frame_lock = threading.Lock()
        self.live_zoom_factor = 1.0
        self.live_native_pixel_view = False
        self.live_zoom_label_var = tk.StringVar(self)
        self.live_pan_x = self.live_pan_y = 0
        self.live_view_crop_roi = None
        self.live_display_rotation_degrees = 90
        self.live_autocontrast_var = tk.BooleanVar(self, value=False)
        self.live_show_saturation_var = tk.BooleanVar(self, value=False)
        self.live_gamma_var = tk.DoubleVar(self, value=1)
        self.live_cross_enabled_var = tk.BooleanVar(self, value=False)
        self.live_cross_point = None
        self.live_first_frame_rendered = True
        self.theme = {"canvas": "#111111"}
        self.log = Mock()
        self._maybe_initialize_roi_fields_from_live_frame = Mock()
        self._draw_live_roi_overlay = Mock()
        self._draw_live_cross_overlay = Mock()
        self._render_live_profiles = Mock()
        self._schedule_live_render = Mock()
        self._set_live_view_status = Mock()
        self.param_vars = {}
        self._get_active_roi = lambda: self.live_view_crop_roi
        self._format_roi_short = lambda roi: str(roi)
        self.set_frame(800, 900)
        self.update()

    def set_frame(self, w, h):
        self.latest_live_frame = (w, h, bytes(i % 256 for i in range(w * h)), bytes(w * h))
        self.latest_live_raw_frame = None
        self.live_frame_info = (w, h, 12, 16)

    def set_raw_frame(self, pixels, depth=16, threshold=32768):
        h, w = pixels.shape
        raw_buffer = pixels.tobytes()
        gray, dw, dh, mask = self._extract_live_preview_bytes(raw_buffer, w, h, w * pixels.dtype.itemsize,
                                                            pixels.dtype.itemsize, depth, pixels.dtype.itemsize * 8,
                                                            threshold, 1)
        self.latest_live_frame = (dw, dh, gray, mask)
        self.latest_live_raw_frame = dict(frame=self.latest_live_frame,
            pixels=self._live_raw_sample_view(raw_buffer, w, h, w * pixels.dtype.itemsize, pixels.dtype.itemsize, 1),
            frame_width=w, frame_height=h, bit_depth=depth, bits_per_pixel=pixels.dtype.itemsize * 8,
            saturation_threshold=threshold)
        self.live_frame_info = (w, h, depth, pixels.dtype.itemsize * 8)


@unittest.skipIf(live_view.np is None, "Native preview requires NumPy")
class LiveRenderTests(unittest.TestCase):
    def setUp(self):
        self.app = SyntheticLiveApp()

    def tearDown(self):
        self.app.update_idletasks()
        self.app.destroy()

    def test_native_render_zoom_pan_and_pixel_mapping(self):
        app = self.app
        app._render_live_photo()
        app.show_live_native_resolution()
        app._render_live_photo()
        self.assertEqual(app.live_display_rect[2:], (900, 800))
        self.assertEqual(app.live_zoom_label_var.get(), "1:1")
        left, top, _, _ = app.live_display_rect
        x, y = 320, 240
        raw_x, raw_y, w, h = app._live_event_to_image_xy(SimpleNamespace(x=x, y=y))
        self.assertEqual((w, h), (800, 900))
        photo_item = app.live_view_canvas.find_all()[-1]
        photo_left, photo_top = app.live_view_canvas.coords(photo_item)
        expected = app.latest_live_frame[2][raw_y * 800 + raw_x]
        self.assertEqual(app.live_photo.get(int(x - photo_left), int(y - photo_top)), (expected,) * 3)
        app.live_pan_x, app.live_pan_y = 20, -30
        app.zoom_live_view(4)
        app._render_live_photo()
        self.assertLessEqual(app.live_photo.width(), 641)
        self.assertLessEqual(app.live_photo.height(), 481)
        self.assertGreater(app.live_display_rect[2], 640)
        app.fit_live_view()
        app._render_live_photo()
        self.assertFalse(app.live_native_pixel_view)
        self.assertEqual(app.live_zoom_label_var.get(), "Zoom 100%")
        app.log.assert_not_called()

    def test_camera_roi_not_cropped_twice_and_snapshot_native_size(self):
        app = self.app
        app.set_frame(300, 400)
        app.live_view_crop_roi = (100, 150, 300, 400)
        app._render_live_photo()
        app.show_live_native_resolution()
        app._render_live_photo()
        self.assertEqual(app.live_display_rect[2:], (400, 300))
        self.assertEqual(app._live_crop_offset, (100, 150))
        left, top, _, _ = app.live_display_rect
        point = app._live_event_to_image_xy(SimpleNamespace(x=left + 1, y=top + 2))
        self.assertEqual(point[:2], (102, 548))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "snap.png"
            with patch.object(live_view.filedialog, "asksaveasfilename", return_value=str(path)):
                app.snapshot_live_view()
            self.assertEqual(struct.unpack(">II", path.read_bytes()[16:24]), (400, 300))

    def test_full_frame_snapshot_crops_roi_at_native_resolution(self):
        app = self.app
        app.live_view_crop_roi = (100, 150, 300, 400)
        app._render_live_photo()
        app.show_live_native_resolution()
        app._render_live_photo()
        self.assertEqual(app.live_display_rect[2:], (400, 300))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "snap.png"
            with patch.object(live_view.filedialog, "asksaveasfilename", return_value=str(path)):
                app.snapshot_live_view()
            self.assertEqual(struct.unpack(">II", path.read_bytes()[16:24]), (400, 300))

    def test_render_auto_gamma_changes_and_snapshot_share_raw_mapping(self):
        app, np = self.app, live_view.np
        pixels = np.arange(500, 756, dtype="<u2").reshape(16, 16)
        app.set_raw_frame(pixels)
        app.live_autocontrast_var.set(True)
        app._render_live_photo()
        app.show_live_native_resolution()
        app._render_live_photo()
        self.assertEqual(app.live_display_rect[2:], (16, 16))
        self.assertEqual(app.live_display_intensity_mapping[:4], (500, 755, 500, 755))
        for gamma in (1.0, 2.0):
            app.live_gamma_var.set(gamma)
            app._render_live_photo()
            left, top = app.live_display_rect[:2]
            mapped = app._prepare_live_display_bytes(app.latest_live_frame[2], app.latest_live_raw_frame)
            oriented, w, h, _ = app._orient_live_display_bytes(mapped, 16, 16)
            self.assertEqual(app.live_photo.get(7, 9), (oriented[9 * w + 7],) * 3)
            point = app._live_event_to_image_xy(SimpleNamespace(x=left + 7, y=top + 9))
            self.assertEqual(point[:2], (9, 8))
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "raw_mapping.png"
                with patch.object(live_view.filedialog, "asksaveasfilename", return_value=str(path)):
                    app.snapshot_live_view()
                snapshot = tk.PhotoImage(file=str(path))
                self.assertEqual((snapshot.width(), snapshot.height()), (w, h))
                self.assertEqual(snapshot.get(7, 9), app.live_photo.get(7, 9))
        app.live_autocontrast_var.set(False)
        app.live_gamma_var.set(1.0)
        app._render_live_photo()
        self.assertEqual(app.live_display_intensity_mapping[2:4], (0, 65535))

    def test_stale_raw_frame_is_not_used_for_a_new_legacy_frame(self):
        app, np = self.app, live_view.np
        app.set_raw_frame(np.arange(256, dtype="<u2").reshape(16, 16))
        previous = app.latest_live_raw_frame
        app.set_frame(16, 16)
        app.latest_live_raw_frame = previous
        app.live_autocontrast_var.set(True)
        app._render_live_photo()
        self.assertIsNone(getattr(app, "live_display_intensity_mapping", None))
        app.log.assert_not_called()

    def test_raw_roi_render_and_snapshot_use_identical_mapping_and_geometry(self):
        app, np = self.app, live_view.np
        for camera_cropped in (False, True):
            full = np.arange(1000, 1000 + 8 * 10, dtype="<u2").reshape(8, 10)
            full[0, 0] = 65535
            roi = (2, 3, 5, 4)
            app.set_raw_frame(full[3:7, 2:7] if camera_cropped else full)
            app.live_view_crop_roi = roi
            app.live_autocontrast_var.set(True)
            app._render_live_photo()
            app.show_live_native_resolution()
            app._render_live_photo()
            self.assertEqual(app.live_display_rect[2:], (4, 5))
            self.assertEqual(app._live_crop_offset, (2, 3))
            self.assertEqual(app.live_display_intensity_mapping[:2], (1032, 1066))
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "raw_roi.png"
                with patch.object(live_view.filedialog, "asksaveasfilename", return_value=str(path)):
                    app.snapshot_live_view()
                snapshot = tk.PhotoImage(file=str(path))
                self.assertEqual((snapshot.width(), snapshot.height()), (4, 5))
                self.assertEqual(snapshot.get(1, 2), app.live_photo.get(1, 2))


if __name__ == "__main__":
    unittest.main()
