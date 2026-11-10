"""Sign-in helpers for provider CLIs.

The upstream macOS app drives the provider CLIs in a pseudo terminal so it can
follow a browser based OAuth flow: the CLI prints a URL, the app opens it and
waits for the CLI to confirm the login.

Claude Code uses a "paste the code back" flow, so the session also accepts
input from the user while the CLI is waiting.

This module implements the same flow with the Python standard library only.
"""

from __future__ import annotations

import os
import json
import re
import select
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field

from . import rust_bridge

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")

CLAUDE_LOGIN_ARGS = ["auth", "login", "--claudeai"]
MAX_LOGIN_OUTPUT_CHARS = 64 * 1024
MAX_CLAUDEPLATFORM_INPUT_BYTES = 16 * 1024
MAX_CLAUDEPLATFORM_OUTPUT_BYTES = 64 * 1024
CLAUDE_SUCCESS_MARKERS = (
    "Successfully logged in",
    "Login successful",
    "Logged in successfully",
)
PROMPT_MARKERS = (
    "Paste code here",
    "press ENTER to open in browser",
)


def terminal_command_argv(terminal: str, command: list[str]) -> list[str]:
    """Build argv for a terminal emulator without shell-splitting commands."""
    rust = rust_bridge.extension()
    if rust is not None:
        return list(rust.terminal_command_argv(terminal, command))
    terminal_name = os.path.basename(terminal)
    separator = "--" if terminal_name == "gnome-terminal" else "-e"
    return [terminal, separator, *command]


def browser_command_argv(binary: str, url: str) -> list[str]:
    """Build argv for a browser opener without invoking a shell."""
    rust = rust_bridge.extension()
    if rust is not None:
        return list(rust.browser_command_argv(binary, url))
    return [binary, "open", url] if os.path.basename(binary) == "gio" else [binary, url]


@dataclass
class LoginResult:
    success: bool = False
    output: str = ""
    auth_url: str | None = None
    message: str = ""
    timed_out: bool = False
    binary_missing: bool = False


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def open_in_browser(url: str) -> bool:
    """Open ``url`` in the default browser."""
    for opener in ("xdg-open", "gio", "sensible-browser"):
        binary = shutil.which(opener)
        if not binary:
            continue
        try:
            argv = browser_command_argv(binary, url)
            if opener == "gio":
                subprocess.run(
                    argv, check=False, capture_output=True, timeout=15
                )
            else:
                subprocess.run(argv, check=False, capture_output=True, timeout=15)
            return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


class ClaudePlatformLoginError(RuntimeError):
    """Sanitized one-shot login failure; never contains CLI output or input."""


def run_claudeplatform_login(
    binary: str, cookie: str, timeout: float = 60.0,
    cancelled: threading.Event | None = None,
) -> None:
    """Send one ephemeral candidate to the CLI over piped stdin and require its JSON success."""
    encoded = cookie.encode("utf-8", errors="strict")
    if not encoded or len(encoded) > MAX_CLAUDEPLATFORM_INPUT_BYTES or "\n" in cookie or "\r" in cookie:
        raise ClaudePlatformLoginError("input")
    argv = [binary, "config", "login", "--provider", "claudeplatform", "--stdin", "--json"]
    try:
        process = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            start_new_session=True, close_fds=True,
        )
    except OSError as exc:
        raise ClaudePlatformLoginError("process") from exc

    output = bytearray()
    overflow = threading.Event()

    def drain_stdout() -> None:
        assert process.stdout is not None
        while True:
            block = process.stdout.read(4096)
            if not block:
                return
            room = MAX_CLAUDEPLATFORM_OUTPUT_BYTES - len(output)
            if room > 0:
                output.extend(block[:room])
            if len(block) > room:
                overflow.set()

    reader = threading.Thread(target=drain_stdout, name="claudeplatform-login-output", daemon=True)
    reader.start()
    write_error: list[BaseException] = []

    def feed_stdin() -> None:
        try:
            assert process.stdin is not None
            process.stdin.write(encoded)
            process.stdin.close()
        except BaseException as exc:  # reported only as a sanitized process failure
            write_error.append(exc)

    writer = threading.Thread(target=feed_stdin, name="claudeplatform-login-input", daemon=True)
    writer.start()
    try:
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if cancelled is not None and cancelled.is_set():
                raise ClaudePlatformLoginError("cancelled")
            if time.monotonic() >= deadline:
                raise ClaudePlatformLoginError("timeout")
            time.sleep(0.02)
        writer.join(timeout=1)
        # The CLI is expected to exit; remove any accidental descendants that
        # inherited stdout so the bounded reader can always be joined.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        reader.join(timeout=2)
        if reader.is_alive() or writer.is_alive() or write_error or process.returncode != 0 or overflow.is_set():
            raise ClaudePlatformLoginError("rejected")
        payload = json.loads(bytes(output).decode("utf-8", errors="strict"))
        if payload != {"status": "authorized"}:
            raise ClaudePlatformLoginError("rejected")
    except ClaudePlatformLoginError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            process.wait()
        raise
    except (BrokenPipeError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            process.wait()
        raise ClaudePlatformLoginError("process") from exc
    finally:
        writer.join(timeout=1)
        reader.join(timeout=1)
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        if process.stdout is not None:
            process.stdout.close()


class ClaudeLoginSession:
    """Runs ``claude auth login --claudeai`` and follows the browser flow.

    The caller watches :attr:`url` and :attr:`status`, and can hand the
    authorisation code back with :meth:`submit`.
    """

    def __init__(
        self,
        binary: str = "claude",
        timeout: float = 300,
        controller=None,
    ) -> None:
        self.binary = binary
        self.timeout = timeout
        self.url: str | None = None
        self.status: str = "Starting…"
        self.output: str = ""
        self.result: LoginResult | None = None
        self.needs_code: bool = False

        self._master_fd: int | None = None
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._pending_input: list[str] = []
        self._done = threading.Event()
        self._thread: threading.Thread | None = None
        self._rust_session = None
        self._controller = controller
        self._rust_mode = False
        self._rust_discovery_failed = False
        self._rust_cancel_requested = threading.Event()

        rust = rust_bridge.extension()
        if rust is not None:
            self._rust_mode = True
            self._rust_discovery_failed = (
                controller is None
                or not callable(getattr(controller, "start_claude_login", None))
            )

    # -- lifecycle --------------------------------------------------------

    def start(self) -> bool:
        if self._rust_mode:
            if self._rust_discovery_failed:
                self.status = f"{self.binary} not found in PATH"
                self.result = LoginResult(binary_missing=True, message=self.status)
                self._done.set()
                return False
            self._thread = threading.Thread(
                target=self._run_rust, name="claude-login-rust", daemon=True
            )
            self._thread.start()
            return True

        if not shutil.which(self.binary):
            self.status = f"{self.binary} not found in PATH"
            self.result = LoginResult(binary_missing=True, message=self.status)
            self._done.set()
            return False

        self._thread = threading.Thread(target=self._run, name="claude-login", daemon=True)
        self._thread.start()
        return True

    def submit(self, text: str) -> None:
        """Send text (for example the authorisation code) to the CLI."""
        if self._rust_session is not None:
            try:
                self._rust_session.submit(text)
            except RuntimeError:
                self.status = "Could not submit the authorization code"
            return
        with self._lock:
            self._pending_input.append(text)

    def cancel(self) -> None:
        if self._rust_mode:
            self._rust_cancel_requested.set()
            if self._rust_session is not None:
                try:
                    self._rust_session.cancel()
                except RuntimeError:
                    pass
            return
        self._write(b"\x03")  # ctrl-c
        self._done.set()

    def wait(self, timeout: float | None = None) -> LoginResult | None:
        self._done.wait(timeout)
        return self.result

    # -- internals --------------------------------------------------------

    def _run_rust(self) -> None:
        try:
            if self._rust_cancel_requested.is_set():
                self.result = LoginResult(message="Login cancelled")
                return
            if self._rust_session is None:
                rust = rust_bridge.extension()
                if rust is None or self._controller is None:
                    self.result = LoginResult(message="Login service unavailable")
                    return
                package_dir = os.path.dirname(os.path.abspath(__file__))
                try:
                    executable = rust.discover_cli_executable(
                        self.binary, "CLAUDE_CLI", package_dir
                    )
                except (OSError, RuntimeError):
                    self._rust_discovery_failed = True
                    self.result = LoginResult(
                        binary_missing=True,
                        message=f"{self.binary} not found in PATH",
                    )
                    return
                self._rust_session = self._controller.start_claude_login(
                    str(executable), int(self.timeout)
                )
            self._rust_session.start()
            if self._rust_cancel_requested.is_set():
                self._rust_session.cancel()
            while True:
                self._consume_rust_events()
                status, needs_code = self._rust_session.snapshot()
                self.needs_code = bool(needs_code)
                self.status = {
                    "starting": "Starting…",
                    "waiting_for_authorization": "Open the link to authorise, then paste the code",
                    "waiting_for_code": "Paste the code from the browser",
                    "finishing": "Finishing sign-in…",
                    "succeeded": "Signed in to Claude",
                    "failed": "Login failed",
                    "timed_out": "Login timed out",
                    "cancelled": "Login cancelled",
                }.get(status, "Login in progress")
                if status in {"succeeded", "failed", "timed_out", "cancelled"}:
                    break
                time.sleep(0.05)

            self._consume_rust_events()
            completion, exit_code = self._rust_session.wait()
            success = completion == "succeeded"
            if success:
                message = "Signed in to Claude"
            elif completion == "timed_out":
                message = "Login timed out — try again"
            elif completion == "cancelled":
                message = "Login cancelled"
            elif self.url:
                message = "Login was not completed"
            else:
                message = f"Login failed (exit {exit_code})"
            self.result = LoginResult(
                success=success,
                output=self.output,
                auth_url=self.url,
                message=message,
                timed_out=completion == "timed_out",
            )
        except RuntimeError:
            # Rust errors contain only static operation identifiers and typed
            # categories. Keep the compatibility UI message similarly generic.
            self.result = LoginResult(message="Login process failed")
        finally:
            self._done.set()

    def _consume_rust_events(self) -> None:
        assert self._rust_session is not None
        for kind, value in self._rust_session.poll_events():
            if kind == "url":
                self.url = value
                self.status = "Open the link to authorise, then paste the code"
            elif kind == "prompt" and value == "paste_code":
                self.needs_code = True
                self.status = "Paste the code from the browser"
            elif kind == "output":
                self.output = (self.output + value)[-MAX_LOGIN_OUTPUT_CHARS:]

    def _write(self, data: str) -> None:
        with self._lock:
            fd = self._master_fd
        if fd is None:
            return
        try:
            os.write(fd, data.encode())
        except OSError:
            pass

    def _run(self) -> None:
        import pty

        try:
            master_fd, slave_fd = pty.openpty()
        except OSError as exc:
            self.result = LoginResult(message=f"Could not open a terminal: {exc}")
            self._done.set()
            return

        try:
            process = subprocess.Popen(
                [self.binary, *CLAUDE_LOGIN_ARGS],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                env=os.environ.copy(),
            )
        except FileNotFoundError:
            os.close(master_fd)
            os.close(slave_fd)
            self.result = LoginResult(binary_missing=True, message="claude not found")
            self._done.set()
            return

        os.close(slave_fd)
        with self._lock:
            self._master_fd = master_fd
        self._process = process

        output = ""
        deadline = time.monotonic() + self.timeout
        exit_status: int | None = None

        while True:
            if self._done.is_set():
                break
            if time.monotonic() > deadline:
                self.status = "Login timed out"
                break

            with self._lock:
                pending = list(self._pending_input)
                self._pending_input.clear()
            for text in pending:
                self._write(text + "\n")

            ready, _, _ = select.select([master_fd], [], [], 0.3)
            if ready:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                text = chunk.decode(errors="ignore")
                output += text
                clean = strip_ansi(text)

                if self.url is None:
                    match = URL_RE.search(clean)
                    if match:
                        self.url = match.group(0).rstrip(".,")
                        self.status = "Open the link to authorise, then paste the code"

                if any(marker in clean for marker in PROMPT_MARKERS):
                    self.needs_code = True
                    if "Paste code here" in clean:
                        self.status = "Paste the code from the browser"

                if any(marker in clean for marker in CLAUDE_SUCCESS_MARKERS):
                    exit_status = 0
                    break
            elif process.poll() is not None:
                exit_status = process.returncode
                break

        clean_output = strip_ansi(output)
        self.output = clean_output

        if process.poll() is None:
            try:
                process.send_signal(signal.SIGTERM)
                process.wait(timeout=3)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        elif exit_status is None:
            exit_status = process.returncode

        success = exit_status == 0 or any(
            marker in clean_output for marker in CLAUDE_SUCCESS_MARKERS
        )
        if success:
            message = "Signed in to Claude"
        elif self.status == "Login timed out":
            message = "Login timed out — try again"
        elif self.url and not success:
            message = "Login was not completed"
        else:
            message = f"Login failed (exit {exit_status})"

        self.result = LoginResult(
            success=success,
            output=clean_output,
            auth_url=self.url,
            message=message,
            timed_out=message.startswith("Login timed out"),
        )
        with self._lock:
            self._master_fd = None
        try:
            os.close(master_fd)
        except OSError:
            pass
        self._done.set()


def claude_auth_status() -> dict:
    """Return the parsed ``claude auth status`` payload."""
    rust = rust_bridge.extension()
    if rust is not None:
        package_dir = os.path.dirname(os.path.abspath(__file__))
        try:
            executable = rust.discover_cli_executable(
                "claude", "CLAUDE_CLI", package_dir
            )
            service = rust.CliService(executable, None)
            import json

            data = json.loads(service.claude_auth_status(30))
        except (OSError, RuntimeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    binary = shutil.which("claude")
    if not binary:
        return {}
    try:
        proc = subprocess.run(
            [binary, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    import json

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
