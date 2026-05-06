from __future__ import annotations

import threading
import time
from typing import Iterable

import serial
from serial.tools import list_ports

from .protocol import ACK_BYTE, NACK_BYTE, PicoPacket


class PicoConnection:
    """Pico 직렬 포트를 단일 소유자로 열고, 패킷 묶음을 ACK까지 처리합니다."""

    def __init__(self) -> None:
        self._serial: serial.Serial | None = None
        self._lock = threading.RLock()
        self.port = ""
        self.baudrate = 115200

    @staticmethod
    def available_ports() -> list[dict[str, str]]:
        """Windows에 잡힌 COM 포트를 UI/클라이언트가 표시하기 좋은 형태로 반환합니다."""

        return [
            {
                "device": port.device,
                "description": port.description,
                "hwid": port.hwid,
            }
            for port in list_ports.comports()
        ]

    @staticmethod
    def auto_connect_candidates(preferred_port: str = "") -> list[dict[str, str]]:
        """자동 연결에서 시도할 Pico 후보 포트를 우선순위 순서로 반환합니다."""

        preferred = str(preferred_port or "").strip()
        ports = PicoConnection.available_ports()
        if preferred:
            # 사용자가 마지막으로 저장한 포트가 있으면 장치 설명이 달라져도 가장 먼저 시도합니다.
            preferred_rows = [port for port in ports if str(port.get("device", "")).lower() == preferred.lower()]
            other_rows = [port for port in ports if str(port.get("device", "")).lower() != preferred.lower()]
            return preferred_rows + other_rows

        # Pico/RP2040 계열로 보이는 포트를 먼저 고릅니다. 포트가 하나뿐이면 설명이 애매해도 후보로 둡니다.
        likely_keywords = ("pico", "rp2040", "raspberry", "cdc", "usb serial", "serial device")
        likely_ports: list[dict[str, str]] = []
        fallback_ports: list[dict[str, str]] = []
        for port in ports:
            haystack = f"{port.get('device', '')} {port.get('description', '')} {port.get('hwid', '')}".lower()
            if any(keyword in haystack for keyword in likely_keywords):
                likely_ports.append(port)
            else:
                fallback_ports.append(port)
        if likely_ports:
            return likely_ports + fallback_ports
        if len(ports) == 1:
            return ports
        return []

    def auto_connect(self, baudrate: int = 115200, preferred_port: str = "") -> str:
        """저장 포트 또는 Pico로 보이는 COM 포트를 찾아 연결하고, 성공한 포트명을 반환합니다."""

        errors: list[str] = []
        candidates = self.auto_connect_candidates(preferred_port)
        if not candidates:
            raise RuntimeError("자동 연결할 Pico 후보 COM 포트를 찾지 못했습니다.")
        for port_info in candidates:
            device = str(port_info.get("device", "")).strip()
            if not device:
                continue
            try:
                self.connect(device, baudrate)
                return device
            except Exception as error:
                errors.append(f"{device}: {error}")
        detail = " / ".join(errors) if errors else "시도 가능한 COM 포트가 없습니다."
        raise RuntimeError(f"Pico 자동 연결에 실패했습니다. {detail}")

    def connect(self, port: str, baudrate: int = 115200) -> None:
        """지정한 Pico COM 포트를 열어 서버가 독점 관리하도록 만듭니다."""

        clean_port = str(port or "").strip()
        if not clean_port:
            raise ValueError("Pico 포트가 비어 있습니다.")
        with self._lock:
            self.disconnect()
            self._serial = serial.Serial(
                port=clean_port,
                baudrate=int(baudrate),
                timeout=0.2,
                write_timeout=0.5,
            )
            self.port = clean_port
            self.baudrate = int(baudrate)

    def disconnect(self) -> None:
        """현재 열려 있는 직렬 포트를 닫습니다."""

        with self._lock:
            if self._serial is not None:
                try:
                    if self._serial.is_open:
                        self._serial.close()
                finally:
                    self._serial = None
            self.port = ""

    def is_connected(self) -> bool:
        """Pico 직렬 포트가 현재 열린 상태인지 확인합니다."""

        return self._serial is not None and self._serial.is_open

    def send_packets(self, packets: Iterable[PicoPacket], expect_ack: bool = True, ack_timeout: float = 2.0) -> None:
        """패킷 묶음을 중간 끼어듦 없이 전송하고, 필요하면 마지막 ACK를 기다립니다."""

        packet_list = list(packets)
        if not packet_list:
            return
        if expect_ack:
            packet_list[-1] = packet_list[-1].with_ack()

        with self._lock:
            if not self.is_connected():
                raise RuntimeError("Pico가 연결되어 있지 않습니다.")
            assert self._serial is not None
            self._serial.reset_input_buffer()
            for packet in packet_list:
                self._serial.write(packet.to_bytes())
            self._serial.flush()
            if expect_ack:
                self._wait_for_ack(ack_timeout)

    def _wait_for_ack(self, timeout: float) -> None:
        """ACK 요청 패킷 뒤 Pico가 보내는 ACK/NACK 1바이트를 기다립니다."""

        assert self._serial is not None
        deadline = time.monotonic() + max(0.1, float(timeout))
        while time.monotonic() < deadline:
            byte = self._serial.read(1)
            if byte == ACK_BYTE:
                return
            if byte == NACK_BYTE:
                raise RuntimeError("Pico가 명령을 NACK로 거부했습니다.")
        raise TimeoutError("Pico ACK 대기 시간이 초과되었습니다.")
