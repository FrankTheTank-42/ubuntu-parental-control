#!/usr/bin/python3
"""Native Messaging bridge for live snapshots and restricted rule additions."""

from __future__ import annotations

import json
import select
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, BinaryIO


DEFAULT_SNAPSHOT = Path("/run/ubuntu-parental-control/live-snapshot.json")
DEFAULT_SOCKET = Path("/run/ubuntu-parental-control/control.sock")
DEFAULT_ADMIN_HELPER = Path("/usr/lib/ubuntu-parental-control/admin_helper.py")
MAX_MESSAGE_BYTES = 1_000_000
PUBLICATION_WAIT_SECONDS = 15


def configured_path(option: str, default: Path) -> Path:
    # Browsers append their extension origin/ID to argv. Only explicit named
    # test options are interpreted; all browser-provided arguments are ignored.
    try:
        index = sys.argv.index(option)
    except ValueError:
        return default
    if index + 1 >= len(sys.argv):
        raise SystemExit(f"{option} benötigt einen Pfad")
    return Path(sys.argv[index + 1])


def read_native_message(stream: BinaryIO) -> dict[str, Any] | None:
    header = stream.read(4)
    if not header:
        return None
    if len(header) != 4:
        raise ValueError("unvollständiger Native-Messaging-Header")
    length = struct.unpack("@I", header)[0]
    if length > MAX_MESSAGE_BYTES:
        raise ValueError("Native-Messaging-Nachricht ist zu groß")
    payload = stream.read(length)
    if len(payload) != length:
        raise ValueError("unvollständige Native-Messaging-Nachricht")
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Native-Messaging-Nachricht muss ein Objekt sein")
    return value


def write_native_message(stream: BinaryIO, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("Native-Messaging-Antwort ist zu groß")
    stream.write(struct.pack("@I", len(payload)))
    stream.write(payload)
    stream.flush()


def request_control(path: Path, request: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(payload) > 16_384:
        raise ValueError("Verwaltungsanfrage ist zu groß")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(3)
        connection.connect(str(path))
        connection.sendall(payload)
        response = bytearray()
        while b"\n" not in response:
            chunk = connection.recv(min(MAX_MESSAGE_BYTES + 1 - len(response), 4096))
            if not chunk:
                break
            response.extend(chunk)
            if len(response) > MAX_MESSAGE_BYTES:
                raise ValueError("Verwaltungsantwort ist zu groß")
    value = json.loads(bytes(response).split(b"\n", 1)[0].decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Verwaltungsantwort muss ein Objekt sein")
    return value


def current_publication(socket_path: Path) -> dict[str, Any]:
    response = request_control(
        socket_path,
        {"id": "native-publication", "command": "publication"},
    )
    result = response.get("result") if response.get("ok") else None
    if not isinstance(result, dict):
        raise ValueError("Aktueller Veröffentlichungsstand ist nicht verfügbar")
    serial = result.get("serial")
    if not isinstance(serial, int) or isinstance(serial, bool) or serial < 1:
        raise ValueError("Aktueller Veröffentlichungsstand ist nicht verfügbar")
    for field in ("base_revision", "user_revision"):
        if not isinstance(result.get(field), str):
            raise ValueError("Aktueller Veröffentlichungsstand ist unvollständig")
    return result


def wait_for_publication(
    snapshot_path: Path,
    socket_path: Path,
    previous_serial: int,
    expected_field: str,
    expected_revision: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + PUBLICATION_WAIT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            publication = current_publication(socket_path)
            if (
                publication["serial"] > previous_serial
                and publication.get(expected_field) == expected_revision
            ):
                return load_snapshot(snapshot_path)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(0.1)
    detail = f": {last_error}" if last_error else ""
    raise ValueError(
        "Regel wurde gespeichert, aber der Daemon hat keinen neuen Live-Snapshot veröffentlicht"
        + detail
    )


def request_admin(
    request: dict[str, Any],
    snapshot_path: Path = DEFAULT_SNAPSHOT,
    socket_path: Path = DEFAULT_SOCKET,
) -> dict[str, Any]:
    if request.get("command") == "admin_apply":
        admin_request = {"command": "apply_rules", "rules": request.get("rules")}
    elif request.get("command") == "admin_remove_user_domain":
        admin_request = {
            "command": "remove_user_domain",
            "uid": request.get("uid"),
            "block_id": request.get("block_id"),
            "domain": request.get("domain"),
        }
    else:
        raise ValueError("Unbekannte Administrator-Anfrage")
    payload = json.dumps(
        admin_request,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("Administrator-Anfrage ist zu groß")
    previous_publication = current_publication(socket_path)
    completed = subprocess.run(
        ["/usr/bin/pkexec", str(DEFAULT_ADMIN_HELPER)],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
        check=False,
    )
    try:
        response = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(detail or "Administrator-Anmeldung wurde abgebrochen") from exc
    if not isinstance(response, dict):
        raise ValueError("Administrator-Antwort muss ein Objekt sein")
    if response.get("ok") is True:
        result = response.get("result")
        if not isinstance(result, dict):
            raise ValueError("Administrator-Antwort enthält kein Ergebnis")
        expected_field = (
            "base_revision" if request.get("command") == "admin_apply" else "user_revision"
        )
        expected_revision = result.get(expected_field)
        if not isinstance(expected_revision, str):
            raise ValueError("Administrator-Antwort enthält keine Änderungsrevision")
        response = {
            **response,
            "result": {
                **result,
                "managed": wait_for_publication(
                    snapshot_path,
                    socket_path,
                    previous_publication["serial"],
                    expected_field,
                    expected_revision,
                ),
            },
        }
    return response


def snapshot_signature(path: Path) -> tuple[int, int, int] | None:
    try:
        info = path.stat()
    except OSError:
        return None
    return (info.st_ino, info.st_size, info.st_mtime_ns)


def load_snapshot(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Live-Snapshot ist keine reguläre Datei")
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("Live-Snapshot muss ein Objekt sein")
    return value


def main() -> int:
    snapshot_path = configured_path("--snapshot", DEFAULT_SNAPSHOT)
    socket_path = configured_path("--socket", DEFAULT_SOCKET)
    input_stream = sys.stdin.buffer
    output_stream = sys.stdout.buffer
    last_signature: tuple[int, int, int] | None = None

    write_native_message(output_stream, {"event": "native_status", "connected": True})
    while True:
        signature = snapshot_signature(snapshot_path)
        if signature is not None and signature != last_signature:
            try:
                write_native_message(
                    output_stream,
                    {"event": "snapshot", "managed": load_snapshot(snapshot_path)},
                )
                last_signature = signature
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
                write_native_message(
                    output_stream,
                    {"event": "native_error", "error": f"Live-Snapshot abgelehnt: {exc}"},
                )

        readable, _writable, _errors = select.select([input_stream], [], [], 0.5)
        if not readable:
            continue
        request: dict[str, Any] | None = None
        try:
            request = read_native_message(input_stream)
            if request is None:
                return 0
            if request.get("command") in ("admin_apply", "admin_remove_user_domain"):
                response = {
                    "id": request.get("id"),
                    **request_admin(request, snapshot_path, socket_path),
                }
                if response.get("ok") is True:
                    last_signature = snapshot_signature(snapshot_path)
            else:
                response = request_control(socket_path, request)
        except (
            OSError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
            subprocess.SubprocessError,
        ) as exc:
            response = {
                "id": request.get("id") if request else None,
                "ok": False,
                "error": str(exc),
            }
        write_native_message(output_stream, response)
        time.sleep(0)


if __name__ == "__main__":
    raise SystemExit(main())
