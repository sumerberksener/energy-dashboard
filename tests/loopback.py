"""A throw-away server on 127.0.0.1 for the offline network tests.

Nothing here touches the internet.

    LoopbackServer()            accepts connections, reads the request, never answers
                                (the failure mode of a stalled upstream: the TCP
                                connection is up and no byte ever comes back)
    LoopbackServer(reply=b"..") answers every request with these raw bytes, then closes

`requests` keeps the head of every request it received, so a test can compare
the headers two clients send.
"""
from __future__ import annotations

import socket
import threading


class LoopbackServer:
    def __init__(self, reply: bytes | None = None) -> None:
        self.reply = reply
        self.accepted = 0
        self.requests: list[tuple[str, dict[str, str]]] = []  # (request line, lowercased headers)
        self._conns: list[socket.socket] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(16)
        self._listener.settimeout(0.2)
        self.port: int = self._listener.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._listener.accept()
            except (socket.timeout, OSError):
                continue
            with self._lock:
                self.accepted += 1
                self._conns.append(conn)
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        try:
            buf = b""
            while b"\r\n\r\n" not in buf and not self._stop.is_set():
                chunk = conn.recv(65536)
                if not chunk:
                    return
                buf += chunk
            head, _, rest = buf.partition(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            headers = {k.strip().lower(): v.strip()
                       for k, _, v in (line.partition(":") for line in lines[1:])}
            length = int(headers.get("content-length", "0"))
            while len(rest) < length and not self._stop.is_set():  # drain a POST body
                chunk = conn.recv(65536)
                if not chunk:
                    return
                rest += chunk
            with self._lock:
                self.requests.append((lines[0], headers))
            if self.reply is None:
                self._stop.wait()  # stay silent until the test tears the server down
                return
            conn.sendall(self.reply)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            conns = list(self._conns)
        for c in conns:
            for op in (lambda: c.shutdown(socket.SHUT_RDWR), c.close):
                try:
                    op()
                except OSError:
                    pass
        try:
            self._listener.close()
        except OSError:
            pass


def http_reply(body: bytes, content_type: str, status: str = "200 OK",
               extra_headers: dict[str, str] | None = None) -> bytes:
    """A complete raw HTTP/1.1 response, for LoopbackServer(reply=...)."""
    head = (f"HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n")
    for k, v in (extra_headers or {}).items():
        head += f"{k}: {v}\r\n"
    return head.encode("latin-1") + b"\r\n" + body
