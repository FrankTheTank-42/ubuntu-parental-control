#!/usr/bin/python3
"""Small UID-authenticated Unix-socket API for the browser native host."""

from __future__ import annotations

import json
import os
import socket
import struct
import threading
from pathlib import Path
from typing import Any

from user_rules import EffectiveRulePublisher, UserRuleError


MAX_REQUEST_BYTES = 16_384


class ControlServer:
    def __init__(self, path: Path, publisher: EffectiveRulePublisher) -> None:
        self.path = path
        self.publisher = publisher
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        self.path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise RuntimeError(f"Control-Socket darf kein symbolischer Link sein: {self.path}")
        self.path.unlink(missing_ok=True)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(self.path))
        os.chmod(self.path, 0o666)
        listener.listen(16)
        listener.settimeout(0.25)
        self._socket = listener
        self._thread = threading.Thread(
            target=self._serve,
            name="ubuntu-parental-control-api",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._socket is not None:
            self._socket.close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self.path.unlink(missing_ok=True)

    def _serve(self) -> None:
        assert self._socket is not None
        while not self._stop.is_set():
            try:
                connection, _address = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    return
                continue
            with connection:
                connection.settimeout(1)
                self._handle_connection(connection)

    @staticmethod
    def _peer_uid(connection: socket.socket) -> int:
        size = struct.calcsize("3i")
        _pid, uid, _gid = struct.unpack(
            "3i",
            connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, size),
        )
        return uid

    def _handle_connection(self, connection: socket.socket) -> None:
        request_id: object = None
        try:
            payload = bytearray()
            while b"\n" not in payload:
                chunk = connection.recv(min(4096, MAX_REQUEST_BYTES + 1 - len(payload)))
                if not chunk:
                    break
                payload.extend(chunk)
                if len(payload) > MAX_REQUEST_BYTES:
                    raise UserRuleError("Anfrage ist zu groß")
            raw = bytes(payload).split(b"\n", 1)[0]
            request = json.loads(raw.decode("utf-8"))
            if not isinstance(request, dict):
                raise UserRuleError("Anfrage muss ein JSON-Objekt sein")
            request_id = request.get("id")
            uid = self._peer_uid(connection)
            result = self.dispatch(uid, request)
            response = {"id": request_id, "ok": True, "result": result}
        except (OSError, UnicodeError, json.JSONDecodeError, UserRuleError, ValueError) as exc:
            response = {"id": request_id, "ok": False, "error": str(exc)}
        try:
            connection.sendall(
                json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                + b"\n"
            )
        except OSError:
            pass

    def dispatch(self, uid: int, request: dict[str, Any]) -> dict[str, object]:
        command = request.get("command")
        if command == "publication":
            return self.publisher.publication_status()
        if command == "status":
            return self.publisher.status(uid, request.get("nonce"))
        if command == "base_rules":
            if uid in self.publisher.config["restricted_users"]:
                raise UserRuleError("Basisregeln sind nur im Elternkonto verfügbar")
            return {
                "rules": self.publisher.base_snapshot(),
                "user_domains": self.publisher.user_domain_snapshot(),
            }
        if command == "add_domain":
            return self.publisher.add_domain(
                uid,
                request.get("block_id"),
                request.get("domain"),
            )
        raise UserRuleError("Unbekannter oder nicht erlaubter Befehl")
