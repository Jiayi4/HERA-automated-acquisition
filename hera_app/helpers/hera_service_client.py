import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid

from hera_app.safety import HardwareSafetyError


class HeraServiceClient:
    def __init__(self, python_executable=None, project_root=None, log_func=None):
        self.python_executable = python_executable or sys.executable
        self.project_root = project_root or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        self.log_func = log_func
        self.process = None
        self._messages = queue.Queue()
        self._request_lock = threading.Lock()
        self._process_lock = threading.RLock()
        self._start_lock = threading.Lock()
        self.recovery_required = False
        self._reader_thread = None
        self._stderr_thread = None

    def _log(self, message):
        if callable(self.log_func):
            self.log_func(message)

    def start(self, timeout_sec=8.0):
        with self._start_lock:
            with self._process_lock:
                if self.recovery_required:
                    raise HardwareSafetyError("Previous Hera helper exit is unconfirmed. Recovery is required before restart.")
                if self.is_running():
                    return
                if self.process is not None:
                    self.kill()
                command = [self.python_executable, "-m", "hera_app.helpers.hera_service", "--ready"]
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                process = subprocess.Popen(
                    command, cwd=self.project_root, stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, bufsize=1, creationflags=creationflags,
                )
                messages = queue.Queue()
                self.process, self._messages = process, messages
                self._reader_thread = threading.Thread(target=self._read_stdout, args=(process, messages), daemon=True)
                self._reader_thread.start()
                self._stderr_thread = threading.Thread(target=self._read_stderr, args=(process,), daemon=True)
                self._stderr_thread.start()
            try:
                deadline = time.monotonic() + timeout_sec
                while time.monotonic() < deadline:
                    if self.process is not process:
                        raise RuntimeError("Hera helper startup was cancelled.")
                    if process.poll() is not None:
                        raise RuntimeError(f"Hera helper service exited early with code {process.returncode}.")
                    try:
                        message = messages.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if message.get("event") == "ready" and message.get("ok"):
                        return
                raise RuntimeError("Timed out waiting for Hera helper service to become ready.")
            except Exception:
                self.kill(expected_process=process)
                raise

    def _read_stdout(self, process, messages):
        try:
            for line in process.stdout:
                text = line.strip()
                if not text:
                    continue
                try:
                    message = json.loads(text)
                    if isinstance(message, dict):
                        messages.put(message)
                except json.JSONDecodeError:
                    messages.put({"event": "stdout", "text": text})
        except (OSError, ValueError):
            pass
        finally:
            messages.put({"event": "closed"})

    def _read_stderr(self, process):
        try:
            for line in process.stderr:
                text = line.strip()
                if text and self.process is process:
                    self._log(f"Hera helper stderr: {text}")
        except Exception:
            pass

    def is_running(self):
        return self.process is not None and self.process.poll() is None

    def request(self, command, timeout_sec=15.0, event_callback=None, **payload):
        with self._request_lock:
            self.start()
            process, messages = self.process, self._messages
            request_id = f"{command}_{uuid.uuid4().hex}"
            request = {**payload, "id": request_id, "command": command}
            try:
                process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
                process.stdin.flush()
                deadline = time.monotonic() + timeout_sec
                while time.monotonic() < deadline:
                    if self.process is not process or self.recovery_required:
                        raise RuntimeError("Hera helper request was cancelled; stale results are discarded.")
                    try:
                        message = messages.get(timeout=min(0.1, max(0.001, deadline - time.monotonic())))
                    except queue.Empty:
                        if process.poll() is not None:
                            raise RuntimeError(f"Hera helper service exited with code {process.returncode}.")
                        continue
                    if self.process is not process:
                        raise RuntimeError("Hera helper request was cancelled; stale results are discarded.")
                    if message.get("event") in {"ready", "closed"}:
                        continue
                    if message.get("event") == "stdout":
                        self._log(f"Hera helper output: {message.get('text')}")
                        continue
                    if message.get("id") != request_id:
                        continue
                    if message.get("event") in {"log", "progress"}:
                        if callable(event_callback):
                            event_callback(message)
                        elif message.get("event") == "log":
                            self._log(message.get("message", "Hera helper log message"))
                        continue
                    if not message.get("ok"):
                        raise RuntimeError(message.get("error") or "Hera helper service command failed.")
                    return message.get("result")
                raise RuntimeError(f"Timed out waiting for Hera helper service response to {command!r}.")
            except Exception:
                self.kill(expected_process=process)
                raise

    def shutdown(self, timeout_sec=8.0):
        if not self.is_running():
            self.kill()
            return None
        process = self.process
        try:
            result = self.request("shutdown", timeout_sec=timeout_sec)
            try:
                process.wait(timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                self.kill(expected_process=process)
            return result
        finally:
            self.kill(expected_process=process)

    def kill(self, expected_process=None):
        with self._process_lock:
            process = self.process
            if expected_process is not None and process is not expected_process:
                return
            if process is None:
                self.recovery_required = False
                return
            try:
                self.recovery_required = True
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=3)
                if process.poll() is None:
                    raise RuntimeError("process is still running")
            except Exception as exc:
                raise HardwareSafetyError(f"Hera helper exit unconfirmed; reconnect/retry blocked: {exc}") from exc
            self.process = None
            self.recovery_required = False
            for stream in (process.stdin, process.stdout, process.stderr):
                try:
                    stream.close()
                except Exception:
                    pass
