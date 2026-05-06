from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .connection import PicoConnection
from .protocol import CMD_KBD_UP, CMD_MOUSE_BTN_SET, PicoPacket, steps_to_packets


@dataclass(slots=True)
class InputJob:
    """클라이언트가 요청한 하나의 원자적 Pico 입력 작업입니다."""

    client_id: str
    slot_number: int | None
    label: str
    steps: list[dict[str, Any]]
    expect_ack: bool = True
    ack_timeout: float = 2.0
    created_at: float = field(default_factory=time.time)
    done: threading.Event = field(default_factory=threading.Event)
    ok: bool = False
    error: str = ""


class PicoBroker:
    """여러 프로그램의 입력 요청을 하나의 큐로 직렬화하는 공통 브로커입니다."""

    def __init__(self, connection: PicoConnection | None = None) -> None:
        self.connection = connection or PicoConnection()
        self._queue: queue.Queue[InputJob] = queue.Queue()
        self._active_job: InputJob | None = None
        self._last_slot_number: int | None = None
        self._worker = threading.Thread(target=self._run_worker, name="pico-input-worker", daemon=True)
        self._worker.start()

    def submit(self, job: InputJob, timeout: float | None = None) -> dict[str, Any]:
        """작업을 큐에 넣고 완료될 때까지 기다린 뒤 결과를 반환합니다."""

        self._queue.put(job)
        if not job.done.wait(timeout):
            raise TimeoutError("Pico 입력 작업 대기 시간이 초과되었습니다.")
        if not job.ok:
            raise RuntimeError(job.error or "Pico 입력 작업이 실패했습니다.")
        return {
            "ok": True,
            "client_id": job.client_id,
            "slot_number": job.slot_number,
            "label": job.label,
        }

    def release_all(self) -> None:
        """키보드와 마우스 버튼을 모두 떼서 입력이 물린 상태를 정리합니다."""

        self.connection.send_packets(
            [
                PicoPacket(CMD_KBD_UP),
                PicoPacket(CMD_MOUSE_BTN_SET, 0),
            ],
            expect_ack=True,
        )

    def status(self) -> dict[str, Any]:
        """서버와 Pico 연결, 큐 상태를 상태 화면에서 쓰기 좋게 반환합니다."""

        active = self._active_job
        return {
            "ok": True,
            "connected": self.connection.is_connected(),
            "port": self.connection.port,
            "baudrate": self.connection.baudrate,
            "queue_size": self._queue.qsize(),
            "last_slot_number": self._last_slot_number,
            "active_job": None if active is None else {
                "client_id": active.client_id,
                "slot_number": active.slot_number,
                "label": active.label,
                "created_at": active.created_at,
            },
        }

    def _run_worker(self) -> None:
        """큐에서 하나씩 꺼내 Pico에 전송하므로 세트 입력 중간에 다른 요청이 끼지 않습니다."""

        while True:
            job = self._queue.get()
            self._active_job = job
            try:
                packets = steps_to_packets(job.steps)
                self.connection.send_packets(packets, expect_ack=job.expect_ack, ack_timeout=job.ack_timeout)
                self._last_slot_number = job.slot_number
                job.ok = True
            except Exception as exc:
                job.error = str(exc)
            finally:
                self._active_job = None
                job.done.set()
                self._queue.task_done()
