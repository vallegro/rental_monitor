from __future__ import annotations

from dataclasses import dataclass, field
import base64
import json
from pathlib import Path
import secrets
import shutil
import socket
import ssl
import subprocess
import time
from typing import Any, Callable
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


class ChromiumBrowserError(RuntimeError):
    """Raised when Chromium cannot render or return page content."""


@dataclass(frozen=True, slots=True)
class ChromiumTab:
    target_id: str
    web_socket_url: str


@dataclass(slots=True)
class ChromiumBrowser:
    """Chromium runner that can attach to a real local browser session via DevTools."""

    binary: str | None = None
    user_data_dir: str | Path | None = None
    remote_debugging_port: int = 9222
    headless: bool = False
    virtual_time_budget_ms: int = 10_000
    page_timeout_ms: int = 20_000
    startup_timeout_seconds: int = 20
    command_timeout_seconds: int = 30
    interactive_timeout_seconds: int = 300
    poll_interval_seconds: float = 2.0
    window_width: int = 1440
    window_height: int = 2400
    no_sandbox: bool = True
    user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
    )
    extra_args: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.remote_debugging_port <= 0:
            raise ValueError("remote_debugging_port must be positive")
        if self.virtual_time_budget_ms <= 0:
            raise ValueError("virtual_time_budget_ms must be positive")
        if self.command_timeout_seconds <= 0:
            raise ValueError("command_timeout_seconds must be positive")
        if self.page_timeout_ms <= 0:
            raise ValueError("page_timeout_ms must be positive")
        if self.startup_timeout_seconds <= 0:
            raise ValueError("startup_timeout_seconds must be positive")
        if self.interactive_timeout_seconds <= 0:
            raise ValueError("interactive_timeout_seconds must be positive")
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if self.window_width <= 0 or self.window_height <= 0:
            raise ValueError("window size must be positive")
        if self.binary is None:
            self.binary = self.detect_binary()
        if self.user_data_dir is None:
            self.user_data_dir = Path.home() / ".rental-monitor" / "chromium-profile"
        else:
            self.user_data_dir = Path(self.user_data_dir)

    @staticmethod
    def detect_binary() -> str:
        for candidate in ("google-chrome", "chromium", "chromium-browser"):
            binary = shutil.which(candidate)
            if binary:
                return binary
        raise ChromiumBrowserError("No Chromium-compatible browser binary was found")

    def launch(self, *, start_url: str = "about:blank") -> None:
        if self._is_debug_endpoint_ready():
            return

        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        command = [
            self.binary,
            f"--remote-debugging-port={self.remote_debugging_port}",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=Translate,OptimizationHints",
            "--hide-scrollbars",
            "--mute-audio",
            "--no-first-run",
            "--no-default-browser-check",
            f"--window-size={self.window_width},{self.window_height}",
            f"--user-agent={self.user_agent}",
            f"--user-data-dir={self.user_data_dir}",
        ]
        if self.headless:
            command.extend(
                [
                    "--headless=new",
                    f"--timeout={self.page_timeout_ms}",
                    f"--virtual-time-budget={self.virtual_time_budget_ms}",
                ]
            )
        if self.no_sandbox:
            command.extend(["--no-sandbox", "--disable-setuid-sandbox"])
        command.extend(self.extra_args)
        command.append(start_url)

        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + self.startup_timeout_seconds
        while time.monotonic() < deadline:
            if self._is_debug_endpoint_ready():
                return
            time.sleep(0.25)
        raise ChromiumBrowserError("Chromium DevTools endpoint did not become ready in time")

    def dump_dom(
        self,
        url: str,
        *,
        wait_until: Callable[[str], bool] | None = None,
        timeout_seconds: int | None = None,
        poll_interval_seconds: float | None = None,
    ) -> str:
        self.launch()
        tab = self.open_tab(url)
        timeout_value = timeout_seconds or self.interactive_timeout_seconds
        poll_interval = poll_interval_seconds or self.poll_interval_seconds
        deadline = time.monotonic() + timeout_value
        last_html = ""

        try:
            with _DevToolsConnection(tab.web_socket_url, timeout_seconds=self.command_timeout_seconds) as connection:
                connection.send_command("Runtime.enable")
                connection.send_command("Page.enable")

                while time.monotonic() < deadline:
                    ready_state = connection.evaluate("document.readyState")
                    html = connection.evaluate("document.documentElement.outerHTML")
                    if isinstance(html, str):
                        last_html = html
                    elif html is not None:
                        last_html = str(html)

                    if ready_state == "complete" and last_html and (wait_until is None or wait_until(last_html)):
                        return last_html

                    time.sleep(poll_interval)
        finally:
            self.close_tab(tab.target_id)

        if last_html:
            raise ChromiumBrowserError(
                "Chromium did not reach a ready page state before timing out. "
                "If a real browser window opened, complete any manual challenge and retry."
            )
        raise ChromiumBrowserError("Chromium did not return any page content")

    def open_tab(self, url: str) -> ChromiumTab:
        response = self._request_json(f"/json/new?{quote(url, safe='')}", method="PUT")
        if not isinstance(response, dict):
            raise ChromiumBrowserError("Chromium returned an invalid target response")
        target_id = str(response.get("id") or response.get("targetId") or "")
        web_socket_url = str(response.get("webSocketDebuggerUrl") or "")
        if not target_id or not web_socket_url:
            raise ChromiumBrowserError("Chromium did not return a debuggable page target")
        return ChromiumTab(target_id=target_id, web_socket_url=web_socket_url)

    def close_tab(self, target_id: str) -> None:
        if not target_id:
            return
        try:
            self._request_json(f"/json/close/{quote(target_id, safe='')}")
        except ChromiumBrowserError:
            pass

    def _is_debug_endpoint_ready(self) -> bool:
        try:
            response = self._request_json("/json/version")
        except ChromiumBrowserError:
            return False
        return isinstance(response, dict) and "Browser" in response

    def _request_json(self, path: str, *, method: str = "GET") -> Any:
        url = f"http://127.0.0.1:{self.remote_debugging_port}{path}"
        request = Request(url, method=method)
        try:
            with urlopen(request, timeout=self.command_timeout_seconds) as response:
                payload = response.read().decode("utf-8")
        except Exception as exc:
            raise ChromiumBrowserError(f"Failed to reach Chromium DevTools endpoint at {url}") from exc
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ChromiumBrowserError(f"Chromium DevTools endpoint returned invalid JSON for {url}") from exc


class _DevToolsConnection:
    def __init__(self, web_socket_url: str, *, timeout_seconds: int) -> None:
        self.web_socket_url = web_socket_url
        self.timeout_seconds = timeout_seconds
        self._socket: socket.socket | ssl.SSLSocket | None = None
        self._message_id = 0
        self._buffer = bytearray()

    def __enter__(self) -> "_DevToolsConnection":
        self._socket = self._connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._socket is not None:
            try:
                self._send_frame(b"", opcode=0x8)
            except OSError:
                pass
            self._socket.close()
            self._socket = None

    def send_command(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._message_id += 1
        message_id = self._message_id
        self._send_json({"id": message_id, "method": method, "params": params or {}})

        while True:
            message = self._read_json_message()
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise ChromiumBrowserError(f"Chromium DevTools error for {method}: {message['error']}")
            return message.get("result")

    def evaluate(self, expression: str) -> Any:
        result = self.send_command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        if not isinstance(result, dict):
            return None
        return result.get("result", {}).get("value")

    def _connect(self) -> socket.socket | ssl.SSLSocket:
        parsed = urlparse(self.web_socket_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        sock = socket.create_connection((host, port), timeout=self.timeout_seconds)
        sock.settimeout(self.timeout_seconds)
        if parsed.scheme == "wss":
            context = ssl.create_default_context()
            sock = context.wrap_socket(sock, server_hostname=host)

        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(handshake.encode("ascii"))
        response = self._read_http_headers(sock)
        if "101" not in response.splitlines()[0]:
            sock.close()
            raise ChromiumBrowserError("Failed to establish Chromium DevTools WebSocket connection")
        return sock

    def _read_http_headers(self, sock: socket.socket | ssl.SSLSocket) -> str:
        chunks = bytearray()
        while b"\r\n\r\n" not in chunks:
            data = sock.recv(4096)
            if not data:
                break
            chunks.extend(data)
        header_bytes, _, remainder = chunks.partition(b"\r\n\r\n")
        if remainder:
            self._buffer.extend(remainder)
        return (header_bytes + b"\r\n\r\n").decode("utf-8", errors="replace")

    def _send_json(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message).encode("utf-8")
        self._send_frame(payload, opcode=0x1)

    def _send_frame(self, payload: bytes, *, opcode: int) -> None:
        if self._socket is None:
            raise ChromiumBrowserError("Chromium DevTools socket is not connected")

        frame = bytearray()
        frame.append(0x80 | opcode)
        length = len(payload)
        mask_key = secrets.token_bytes(4)
        if length < 126:
            frame.append(0x80 | length)
        elif length <= 0xFFFF:
            frame.append(0x80 | 126)
            frame.extend(length.to_bytes(2, "big"))
        else:
            frame.append(0x80 | 127)
            frame.extend(length.to_bytes(8, "big"))
        frame.extend(mask_key)
        masked_payload = bytes(byte ^ mask_key[index % 4] for index, byte in enumerate(payload))
        frame.extend(masked_payload)
        self._socket.sendall(frame)

    def _read_json_message(self) -> dict[str, Any]:
        fragments: list[bytes] = []
        current_opcode: int | None = None
        while True:
            fin, opcode, payload = self._read_frame()
            if opcode == 0x1:
                fragments = [payload]
                current_opcode = opcode
                if fin:
                    return json.loads(payload.decode("utf-8"))
                continue
            if opcode == 0x0 and current_opcode == 0x1:
                fragments.append(payload)
                if fin:
                    return json.loads(b"".join(fragments).decode("utf-8"))
                continue
            if opcode == 0x8:
                raise ChromiumBrowserError("Chromium DevTools connection closed unexpectedly")
            if opcode == 0x9:
                self._send_frame(payload, opcode=0xA)

    def _read_frame(self) -> tuple[bool, int, bytes]:
        if self._socket is None:
            raise ChromiumBrowserError("Chromium DevTools socket is not connected")

        header = self._recv_exact(2)
        first_byte, second_byte = header[0], header[1]
        fin = (first_byte & 0x80) != 0
        opcode = first_byte & 0x0F
        masked = (second_byte & 0x80) != 0
        length = second_byte & 0x7F
        if length == 126:
            length = int.from_bytes(self._recv_exact(2), "big")
        elif length == 127:
            length = int.from_bytes(self._recv_exact(8), "big")
        mask_key = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length)
        if masked:
            payload = bytes(byte ^ mask_key[index % 4] for index, byte in enumerate(payload))
        return fin, opcode, payload

    def _recv_exact(self, length: int) -> bytes:
        if self._socket is None:
            raise ChromiumBrowserError("Chromium DevTools socket is not connected")
        chunks = bytearray()
        if self._buffer:
            take = min(length, len(self._buffer))
            chunks.extend(self._buffer[:take])
            del self._buffer[:take]
        while len(chunks) < length:
            data = self._socket.recv(length - len(chunks))
            if not data:
                raise ChromiumBrowserError("Chromium DevTools socket closed during read")
            chunks.extend(data)
        return bytes(chunks)
