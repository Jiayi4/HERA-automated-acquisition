import os
import re
import time
from pathlib import Path


class ExportMixin:
    def _sanitize_export_tag(self, text):
        keep = []
        for ch in text:
            if ch.isalnum() or ch in {"-", "_"}:
                keep.append(ch)
            elif ch in {" ", "."}:
                keep.append("_")
        sanitized = "".join(keep).strip("_")
        return sanitized or "measurement"

    def _unique_position_name(self, requested_name, ignore_index=None):
        base_name = requested_name.strip() or "Site"
        existing = {
            pos.name
            for index, pos in enumerate(self.positions)
            if ignore_index is None or index != ignore_index
        }
        if base_name not in existing:
            return base_name

        suffix = 2
        while True:
            candidate = f"{base_name}_{suffix}"
            if candidate not in existing:
                return candidate
            suffix += 1

    def _wait_for_export_files(self, output_base_path, timeout_sec=15):
        hdr_path = output_base_path + ".hdr"
        data_candidates = [output_base_path, output_base_path + ".raw", output_base_path + ".img", output_base_path + ".dat"]
        deadline = time.time() + timeout_sec
        last_sizes = None
        stable_count = 0

        while time.time() < deadline:
            hdr_exists = os.path.exists(hdr_path)
            present_data_files = [path for path in data_candidates if os.path.exists(path)]
            if hdr_exists and present_data_files:
                sizes = [os.path.getsize(hdr_path)] + [os.path.getsize(path) for path in present_data_files]
                if sizes == last_sizes:
                    stable_count += 1
                else:
                    stable_count = 0
                    last_sizes = sizes
                if stable_count >= 3:
                    return hdr_path
            time.sleep(0.25)

        raise RuntimeError(f"Timed out waiting for exported files for {output_base_path}")

    def _find_envi_data_file(self, output_base_path):
        for candidate in (output_base_path, output_base_path + ".raw", output_base_path + ".img", output_base_path + ".dat"):
            if os.path.exists(candidate):
                return candidate
        raise RuntimeError(f"Could not find ENVI data file for {output_base_path}")

    def _read_envi_header_value(self, header_text, key, default=None):
        match = re.search(rf"(?im)^\s*{re.escape(key)}\s*=\s*(.+?)\s*$", header_text)
        if not match:
            return default
        return match.group(1).strip()

    def _replace_envi_header_value(self, header_text, key, value):
        line = f"{key} = {value}"
        pattern = rf"(?im)^\s*{re.escape(key)}\s*=.*$"
        if re.search(pattern, header_text):
            return re.sub(pattern, line, header_text)
        return header_text.rstrip() + "\n" + line + "\n"

    def _crop_exported_envi_to_roi(self, source_base_path, target_base_path, roi, description=None):
        source_hdr_path = source_base_path + ".hdr"
        source_data_path = self._find_envi_data_file(source_base_path)
        target_hdr_path = target_base_path + ".hdr"
        target_data_path = target_base_path

        header_text = Path(source_hdr_path).read_text(encoding="utf-8", errors="replace")
        samples = int(self._read_envi_header_value(header_text, "samples"))
        lines = int(self._read_envi_header_value(header_text, "lines"))
        bands = int(self._read_envi_header_value(header_text, "bands"))
        data_type = int(self._read_envi_header_value(header_text, "data type"))
        interleave = (self._read_envi_header_value(header_text, "interleave", "bsq") or "bsq").lower()
        header_offset = int(self._read_envi_header_value(header_text, "header offset", "0"))
        if interleave != "bsq":
            raise RuntimeError(f"ROI export crop only supports ENVI bsq interleave, not {interleave}.")
        bytes_per_sample = {4: 4, 5: 8}.get(data_type)
        if not bytes_per_sample:
            raise RuntimeError(f"ROI export crop does not support ENVI data type {data_type}.")

        roi_x, roi_y, roi_w, roi_h = roi
        roi_x = max(0, min(int(roi_x), samples - 1))
        roi_y = max(0, min(int(roi_y), lines - 1))
        roi_w = max(1, min(int(roi_w), samples - roi_x))
        roi_h = max(1, min(int(roi_h), lines - roi_y))
        row_bytes = roi_w * bytes_per_sample
        source_row_bytes = samples * bytes_per_sample
        source_band_bytes = samples * lines * bytes_per_sample

        with open(source_data_path, "rb") as source_file, open(target_data_path, "wb") as target_file:
            for band_index in range(bands):
                band_offset = header_offset + band_index * source_band_bytes
                for row in range(roi_y, roi_y + roi_h):
                    source_file.seek(band_offset + row * source_row_bytes + roi_x * bytes_per_sample)
                    target_file.write(source_file.read(row_bytes))

        cropped_header = header_text
        if description:
            safe_description = description.replace("}", ")")
            cropped_header = self._replace_envi_header_value(cropped_header, "description", f"{{{safe_description}}}")
        cropped_header = self._replace_envi_header_value(cropped_header, "samples", str(roi_w))
        cropped_header = self._replace_envi_header_value(cropped_header, "lines", str(roi_h))
        cropped_header = self._replace_envi_header_value(cropped_header, "header offset", "0")
        Path(target_hdr_path).write_text(cropped_header, encoding="utf-8")
        return target_hdr_path

    def _remove_export_files(self, output_base_path):
        for candidate in (
            output_base_path,
            output_base_path + ".hdr",
            output_base_path + ".raw",
            output_base_path + ".img",
            output_base_path + ".dat",
        ):
            try:
                if os.path.exists(candidate):
                    os.remove(candidate)
            except Exception as exc:
                self._log_async(f"Could not remove temporary export file {candidate}: {exc}")
