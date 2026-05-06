# pico_common_server

Manager와 RagPilot이 하나의 Pico HID 장비를 공유해서 쓰기 위한 로컬 입력 서버입니다.

## 실행

트레이 앱 실행:

```powershell
python tray_main.py
```

콘솔 서버 실행:

```powershell
python main.py --auto-connect
```

기본 주소는 `http://127.0.0.1:8765` 입니다.

## 빌드

배포용 트레이 exe는 PyInstaller로 생성합니다.

```powershell
pip install -r requirements.txt
pyinstaller PicoCommonServer.spec --noconfirm
```

빌드 결과는 `dist\PicoCommonServer.exe`에 생성됩니다. `dist` 폴더는 로컬 산출물이므로 git에는 올리지 않습니다.

## Windows 시작 시 자동 실행

작업 스케줄러에 현재 사용자 로그온 자동 실행을 등록합니다.

```powershell
.\scripts\install_startup_task.ps1
```

삭제:

```powershell
.\scripts\uninstall_startup_task.ps1
```

등록 스크립트는 `dist\PicoCommonServer.exe`가 있으면 exe를 사용하고, 없으면 `.venv\Scripts\pythonw.exe tray_main.py`를 사용합니다.

## 자동 연결

- 트레이 앱은 `pico_common_server_config.json`의 `auto_connect`가 true이면 시작 시 Pico 연결을 시도합니다.
- 저장된 `pico_port`가 있으면 먼저 사용합니다.
- 저장 포트가 없거나 실패하면 Pico/RP2040/USB Serial로 보이는 COM 포트를 자동 탐색합니다.
- 자동 연결이 실패해도 HTTP 서버는 계속 실행되므로, 이후 `/connect` 또는 `/auto-connect`로 다시 연결할 수 있습니다.

## 주요 API

- `GET /status`: 서버와 Pico 연결 상태, 큐 상태 조회
- `GET /ports`: 사용 가능한 COM 포트 조회
- `POST /connect`: `{ "port": "COM3", "baudrate": 115200 }`
- `POST /auto-connect`: `{ "preferred_port": "COM3", "baudrate": 115200 }`
- `POST /disconnect`: Pico 포트 연결 해제
- `POST /input`: `{ "client_id": "Manager", "slot_number": 1, "label": "buff", "steps": [...], "expect_ack": true }`
- `POST /release-all`: 키보드와 마우스 버튼 전체 해제

## 입력 규칙

- Pico COM 포트는 이 서버 하나가 열고, Manager/RagPilot은 HTTP API로 입력 요청을 보냅니다.
- `alt down + 우클릭 여러 번 + alt up`처럼 하나의 동작으로 취급해야 하는 입력은 `/input` 요청 하나의 `steps` 배열로 묶습니다.
- ACK가 필요한 요청은 마지막 패킷에 ACK 플래그를 붙이고 Pico 응답을 기다립니다.
