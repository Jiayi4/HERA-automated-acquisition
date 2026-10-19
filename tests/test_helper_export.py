"""Compare helper exports with the previous per-pixel algorithm, without hardware."""

import array
import ctypes
import errno
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from hera_app.helpers import acquisition_helper as helper


class SyntheticCube:
    def __init__(self, bands, data_type):
        self.data_type = data_type
        self.shape = bands.shape
        self.buffers = [ctypes.create_string_buffer(band.tobytes()) for band in bands]
        self.calls = []

    def get_hypercube_band_pointer(self, _handle, index, data_type):
        assert data_type == self.data_type
        self.calls.append(index)
        pointer_type = ctypes.c_float if data_type == 0 else ctypes.c_double
        return 450.0 + index * 1.25, ctypes.cast(self.buffers[index], ctypes.POINTER(pointer_type))


def legacy_normalized_bytes(samples, flats, sample_roi, flat_roi):
    sx, sy, w, h = sample_roi
    fx, fy, _, _ = flat_roi
    rows = []
    for band in range(len(samples)):
        for row in range(h):
            def values():
                for x in range(w):
                    sample = float(samples[band, sy + row, sx + x])
                    flat = float(flats[band, fy + row, fx + x])
                    yield sample / flat if abs(flat) > 1e-12 else 0.0
            rows.append(array.array("f", values()).tobytes())
    return b"".join(rows)


@unittest.skipIf(helper.np is None, "Fast helper export requires NumPy")
class HelperExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def data(self, data_type, bands=3):
        np = helper.np
        rng = np.random.default_rng(917)
        dtype = "<f4" if data_type == 0 else "<f8"
        samples = rng.normal(size=(bands, 9, 11)).astype(dtype)
        flats = rng.uniform(-2, 2, size=(bands, 10, 13)).astype(dtype)
        flats[0, 2, 4:10] = [0, -0.0, 1e-13, 1e-12, 1.000001e-12, -1.000001e-12]
        flats[0, 3, 4:10] = [float("nan"), float("inf"), -float("inf"), 1, -1, 1e-11]
        samples[0, 2, 2:8] = [float("nan"), float("inf"), -float("inf"), -0.0, 0.0, 3.4e38]
        samples[0, 3, 2:8] = [-float("nan"), 1e-40, -1e-40, 1.0, -1.0, 0.0]
        if data_type == 1:
            samples[0, 4, 2:8] = [1e300, -1e300, 1e-300, -1e-300, 1.0, -1.0]
        path = self.root / "reference.bsq"
        path.write_bytes(flats.tobytes())
        info = dict(file_path=str(path), source_width=13, source_height=10, bands=bands,
                    data_type=data_type, wavelengths=[450 + i * 1.25 for i in range(bands)])
        alignment = dict(sample_source_width=11, sample_source_height=9, flatfield_source_width=13,
                         sample_roi=(2, 1, 6, 7), flatfield_roi=(4, 2, 6, 7))
        return samples, flats, info, alignment

    def write_normalized(self, cube, info, alignment, name="cube_nrm"):
        path = self.root / name
        events = Mock()
        helper.write_normalized_envi(cube, 123, info, alignment, str(path), "Test description",
                                     cube.shape[0], cube.data_type, emit_func=events, progress_product="nrm")
        return path, events

    def test_numpy_and_fallback_match_all_legacy_bytes_and_headers(self):
        for data_type in (0, 1):
            samples, flats, info, alignment = self.data(data_type)
            expected = legacy_normalized_bytes(samples, flats, alignment["sample_roi"], alignment["flatfield_roi"])
            with patch.object(helper, "EXPORT_CHUNK_BYTES", 6 * 40 * 3):
                cube = SyntheticCube(samples, data_type)
                actual, events = self.write_normalized(cube, info, alignment, "fast_nrm")
                with patch.object(helper, "np", None):
                    fallback, _ = self.write_normalized(SyntheticCube(samples, data_type), info, alignment, "slow_nrm")
            self.assertEqual(actual.read_bytes(), expected)
            self.assertEqual(fallback.read_bytes(), expected)
            self.assertEqual(cube.calls, [0, 1, 2])
            header = Path(str(actual) + ".hdr").read_text()
            self.assertEqual(header, Path(str(fallback) + ".hdr").read_text().replace("slow_nrm", "fast_nrm"))
            for field in ("samples = 6", "lines = 7", "bands = 3", "data type = 4",
                          "interleave = bsq", "byte order = 0", "file type = ENVI Standard",
                          "wavelength = {450.000000, 451.250000, 452.500000}"):
                self.assertIn(field, header)
            self.assertTrue(any(call.kwargs.get("percent") == 100 for call in events.call_args_list))
            self.assertTrue(any("block_rows=3" in call.kwargs.get("message", "") for call in events.call_args_list))

    def test_reference_export_preserves_exact_cropped_and_full_bytes(self):
        for data_type in (0, 1):
            _, flats, info, _ = self.data(data_type)
            for roi in (None, (4, 2, 6, 7), (0, 1, 13, 7)):
                with self.subTest(data_type=data_type, roi=roi), patch.object(helper, "EXPORT_CHUNK_BYTES", 300):
                    output = self.root / "cube_ref"
                    helper.write_file_backed_hypercube_envi(info, str(output), "Reference", roi, emit_func=Mock())
                    x, y, w, h = roi or (0, 0, 13, 10)
                    self.assertEqual(output.read_bytes(), flats[:, y:y + h, x:x + w].tobytes())
                    self.assertIn(f"data type = {4 if data_type == 0 else 5}", Path(str(output) + ".hdr").read_text())

    def test_reference_opened_once_and_sdk_sample_bytes_not_copied(self):
        samples, _, info, alignment = self.data(0)
        original_open = open
        with patch("builtins.open", wraps=original_open) as opened, \
                patch.object(helper.ctypes, "string_at", side_effect=AssertionError("Do not copy the full SDK band")):
            self.write_normalized(SyntheticCube(samples, 0), info, alignment)
        reference_opens = [call for call in opened.call_args_list if str(call.args[0]) == info["file_path"]]
        self.assertEqual(len(reference_opens), 1)

    def test_roi_reader_has_correct_offsets_and_bounded_block_reads(self):
        _, flats, _, _ = self.data(1)

        class CountingReader(io.BytesIO):
            def read(self, count):
                self.counts.append(count)
                return super().read(count)

        source = CountingReader(flats.tobytes())
        source.counts = []
        chunks = list(helper.iter_file_roi_chunks(source, 2, 13, 10, 1, (4, 2, 6, 7), 3))
        self.assertEqual([(offset, rows) for offset, rows, _ in chunks], [(0, 3), (3, 3), (6, 1)])
        self.assertEqual(b"".join(raw for _, _, raw in chunks), flats[2, 2:9, 4:10].tobytes())
        self.assertLessEqual(max(source.counts), 3 * 13 * 8)

    def test_truncated_reference_rejected_even_if_roi_is_complete(self):
        samples, _, info, alignment = self.data(0)
        path = Path(info["file_path"])
        path.write_bytes(path.read_bytes()[:-4])
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            self.write_normalized(SyntheticCube(samples, 0), info, alignment)
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            helper.write_file_backed_hypercube_envi(info, str(self.root / "cube_ref"), "Reference", (0, 0, 2, 2), emit_func=Mock())
        self.assertFalse((self.root / "cube_nrm").exists())
        self.assertFalse((self.root / "cube_ref").exists())
        self.assertEqual(list(self.root.glob("*.tmp_*")), [])

    def test_partial_write_failure_keeps_previous_exports_and_cleans_temps(self):
        samples, _, info, alignment = self.data(0)
        path = self.root / "cube_nrm"
        header = Path(str(path) + ".hdr")
        path.write_bytes(b"previous cube")
        header.write_bytes(b"previous header")
        original_reader = helper.iter_file_roi_chunks

        def fail_after_chunk(*args):
            yield next(original_reader(*args))
            raise OSError(errno.ENOSPC, "Synthetic disk full")

        with patch.object(helper, "iter_file_roi_chunks", side_effect=fail_after_chunk), \
                self.assertRaises(OSError) as error:
            self.write_normalized(SyntheticCube(samples, 0), info, alignment)
        self.assertEqual(error.exception.errno, errno.ENOSPC)
        self.assertEqual(path.read_bytes(), b"previous cube")
        self.assertEqual(header.read_bytes(), b"previous header")
        self.assertEqual(list(self.root.glob("*.tmp_*")), [])

    def test_native_raw_export_bytes_remain_unchanged(self):
        samples, _, _, _ = self.data(1)
        path = self.root / "cube_raw"
        helper.write_sdk_hypercube_envi(SyntheticCube(samples, 1), 123, str(path), "Raw", 11, 9, 3, 1, emit_func=Mock())
        self.assertEqual(path.read_bytes(), samples.tobytes())


if __name__ == "__main__":
    unittest.main()
