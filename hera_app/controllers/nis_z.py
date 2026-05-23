import re
import time
import uuid
from pathlib import Path


class NISZBridgeController:
    """Shared-folder client for the stable NIS-Z-Bridge sync workflow."""

    DEFAULT_SHARED_ROOT = r"\\sti-nas1.rcp.epfl.ch\bios\bios-raw\backups\visible\cell\Jiayi_bios-raw\Z control shared"

    def __init__(self, shared_root=None):
        self.shared_root = Path(shared_root or self.DEFAULT_SHARED_ROOT)
        self.commands_dir = self.shared_root / "commands"
        self.responses_dir = self.shared_root / "responses"
        self.last_command_path = None
        self.last_response_path = None

    def _decode_response_bytes(self, raw):
        if len(raw) > 1 and raw[1] == 0:
            response = raw.decode("utf-16-le", errors="replace")
        else:
            response = raw.decode("ascii", errors="replace")
        return response.replace("\x00", "").strip()

    def _send_and_wait(self, command_text, timeout_sec=90):
        command_text = command_text.strip()
        valid = (
            command_text in {"GET_Z", "STOP"}
            or command_text.startswith("MOVE_REL ")
            or command_text.startswith("MOVE_ABS ")
        )
        if not valid:
            raise RuntimeError(f"Unsupported NIS Z command: {command_text!r}")

        self.commands_dir.mkdir(parents=True, exist_ok=True)
        self.responses_dir.mkdir(parents=True, exist_ok=True)

        command_id = f"hera_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        command_path = self.commands_dir / f"{command_id}.txt"
        response_path = self.responses_dir / f"{command_id}.txt"
        tmp_path = command_path.with_suffix(command_path.suffix + ".tmp")
        self.last_command_path = command_path
        self.last_response_path = response_path

        tmp_path.write_text(command_text + "\n", encoding="ascii", newline="\n")
        tmp_path.replace(command_path)

        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if response_path.exists():
                try:
                    raw = response_path.read_bytes()
                except PermissionError:
                    time.sleep(0.25)
                    continue
                except OSError:
                    time.sleep(0.25)
                    continue

                response = self._decode_response_bytes(raw)
                try:
                    response_path.unlink()
                except OSError:
                    pass
                return response
            time.sleep(0.25)

        try:
            command_path.unlink()
        except OSError:
            pass
        raise RuntimeError(
            f"Timed out waiting for shared response {response_path}. "
            f"The command was written to {command_path}. "
            "On the NIS PC, make sure nis_z_sync_shared_to_local.py is running and that F4 runs the NIS macro."
        )

    def _parse_z(self, response):
        match = re.match(r"^OK\s+([-+]?\d+\.\d+)\s*$", response)
        if match:
            return float(match.group(1))
        if response.startswith("OK"):
            raise RuntimeError(f"NIS Z bridge returned malformed OK response: {response!r}")
        raise RuntimeError(f"NIS Z bridge error: {response}")

    def get_z(self, timeout_sec=90):
        return self._parse_z(self._send_and_wait("GET_Z", timeout_sec))

    def move_rel(self, dz, timeout_sec=90):
        return self._parse_z(self._send_and_wait(f"MOVE_REL {dz:.6f}", timeout_sec))

    def move_abs(self, z, z_min=None, z_max=None, timeout_sec=90):
        if z_min is None or z_max is None:
            command = f"MOVE_ABS {z:.6f}"
        else:
            command = f"MOVE_ABS {z:.6f} {z_min:.6f} {z_max:.6f}"
        return self._parse_z(self._send_and_wait(command, timeout_sec))

    def stop(self, timeout_sec=30):
        return self._parse_z(self._send_and_wait("STOP", timeout_sec))
