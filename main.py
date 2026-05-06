from __future__ import annotations

import argparse

from pico_common.broker import PicoBroker
from pico_common.connection import PicoConnection
from pico_common.server import make_server


def parse_args() -> argparse.Namespace:
    """콘솔 서버 실행 옵션을 읽습니다."""

    parser = argparse.ArgumentParser(description="Pico 공통 입력 서버")
    parser.add_argument("--host", default="127.0.0.1", help="서버 바인딩 주소")
    parser.add_argument("--port", type=int, default=8765, help="서버 포트")
    parser.add_argument("--pico-port", default="", help="시작 시 먼저 연결할 Pico COM 포트")
    parser.add_argument("--baudrate", type=int, default=115200, help="Pico 시리얼 baudrate")
    parser.add_argument("--auto-connect", action="store_true", help="Pico 후보 COM 포트를 자동으로 찾아 연결합니다.")
    return parser.parse_args()


def main() -> None:
    """Pico 공통 HTTP 서버를 실행하고, 요청 시 Pico 자동 연결까지 수행합니다."""

    args = parse_args()
    broker = PicoBroker(PicoConnection())
    if args.pico_port:
        broker.connection.connect(args.pico_port, args.baudrate)
        print(f"[pico-common] Pico connected: {args.pico_port}")
    elif args.auto_connect:
        try:
            connected_port = broker.connection.auto_connect(args.baudrate)
            print(f"[pico-common] Pico auto-connected: {connected_port}")
        except Exception as error:
            # 자동 연결 실패는 서버 자체 실패가 아니므로 HTTP 서버는 계속 띄워 둡니다.
            print(f"[pico-common] Pico auto-connect failed: {error}")

    server = make_server(args.host, args.port, broker)
    print(f"[pico-common] server listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
