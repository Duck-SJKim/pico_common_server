from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .broker import InputJob, PicoBroker


def make_server(host: str, port: int, broker: PicoBroker) -> ThreadingHTTPServer:
    """PicoBroker를 공유하는 로컬 HTTP 서버 인스턴스를 만듭니다."""

    class Handler(PicoRequestHandler):
        shared_broker = broker

    return ThreadingHTTPServer((host, int(port)), Handler)


class PicoRequestHandler(BaseHTTPRequestHandler):
    """Manager/RagPilot이 호출하는 Pico 공통 서버 HTTP API입니다."""

    shared_broker: PicoBroker
    server_version = "PicoCommonServer/0.1"

    def do_GET(self) -> None:
        """상태 조회처럼 본문이 없는 API를 처리합니다."""

        path = urlparse(self.path).path
        try:
            if path in {"/", "/status"}:
                self._send_json(self.shared_broker.status())
                return
            if path == "/ports":
                self._send_json({"ok": True, "ports": self.shared_broker.connection.available_ports()})
                return
            self._send_json({"ok": False, "error": "없는 API입니다."}, status=404)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)

    def do_POST(self) -> None:
        """연결, 입력 요청처럼 JSON 본문이 있는 API를 처리합니다."""

        path = urlparse(self.path).path
        try:
            body = self._read_json()
            if path == "/auto-connect":
                port = self.shared_broker.connection.auto_connect(
                    baudrate=int(body.get("baudrate", 115200)),
                    preferred_port=str(body.get("preferred_port", "") or ""),
                )
                payload = self.shared_broker.status()
                payload["auto_connected_port"] = port
                self._send_json(payload)
                return
            if path == "/connect":
                self.shared_broker.connection.connect(body.get("port", ""), int(body.get("baudrate", 115200)))
                self._send_json(self.shared_broker.status())
                return
            if path == "/disconnect":
                self.shared_broker.connection.disconnect()
                self._send_json(self.shared_broker.status())
                return
            if path == "/input":
                job = InputJob(
                    client_id=str(body.get("client_id", "unknown")),
                    slot_number=_optional_int(body.get("slot_number")),
                    label=str(body.get("label", "input")),
                    steps=list(body.get("steps", [])),
                    expect_ack=bool(body.get("expect_ack", True)),
                    ack_timeout=float(body.get("ack_timeout", 2.0)),
                )
                result = self.shared_broker.submit(job, timeout=float(body.get("timeout", 30.0)))
                self._send_json(result)
                return
            if path == "/release-all":
                self.shared_broker.release_all()
                self._send_json({"ok": True})
                return
            self._send_json({"ok": False, "error": "없는 API입니다."}, status=404)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)

    def log_message(self, fmt: str, *args: Any) -> None:
        """기본 HTTP 로그는 너무 시끄러워서 필요한 정보만 한 줄로 남깁니다."""

        print(f"[pico-common] {self.address_string()} {fmt % args}")

    def _read_json(self) -> dict[str, Any]:
        """요청 본문 JSON을 dict로 읽습니다."""

        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON object만 지원합니다.")
        return data

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        """API 응답을 UTF-8 JSON으로 보냅니다."""

        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _optional_int(value: Any) -> int | None:
    """slot_number처럼 비어 있을 수 있는 값을 int 또는 None으로 정리합니다."""

    if value is None or value == "":
        return None
    return int(value)
