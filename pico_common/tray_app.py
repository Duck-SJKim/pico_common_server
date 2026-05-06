from __future__ import annotations

import ctypes
import json
import socket
import sys
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QSpinBox,
    QSystemTrayIcon,
    QVBoxLayout,
)

from .broker import PicoBroker
from .connection import PicoConnection
from .server import make_server


APP_NAME = "PicoCommonServer"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_BAUDRATE = 115200
MUTEX_NAME = "Local\\PicoCommonServerTray"


def app_base_path() -> Path:
    """배포 exe와 소스 실행 환경에서 설정 파일 기준 경로를 계산합니다."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def config_path() -> Path:
    """트레이 서버 전용 설정 파일 경로를 반환합니다."""

    return app_base_path() / "pico_common_server_config.json"


def load_config() -> dict[str, Any]:
    """저장된 서버/Pico 설정을 읽고, 누락된 값은 기본값으로 보강합니다."""

    default = {
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "pico_port": "",
        "baudrate": DEFAULT_BAUDRATE,
        "auto_connect": True,
    }
    path = config_path()
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as file:
            raw = json.load(file)
        if not isinstance(raw, dict):
            return default
        merged = dict(default)
        merged.update(raw)
        return merged
    except Exception:
        return default


def save_config(data: dict[str, Any]) -> None:
    """Pico 공통 서버 설정만 원자적으로 저장합니다."""

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    temp_path.replace(path)


def port_is_listening(host: str, port: int) -> bool:
    """같은 주소에 이미 서버가 떠 있는지 짧게 확인합니다."""

    try:
        with socket.create_connection((host, int(port)), timeout=0.25):
            return True
    except OSError:
        return False


def acquire_single_instance_mutex() -> object | None:
    """Windows 전역 mutex로 트레이 앱 중복 실행을 막습니다."""

    if sys.platform != "win32":
        return object()
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    already_exists = ctypes.GetLastError() == 183
    if already_exists:
        if handle:
            kernel32.CloseHandle(handle)
        return None
    return handle


class PicoCommonTray:
    """트레이에서 Pico 공통 HTTP 서버와 Pico 자동 연결을 관리합니다."""

    def __init__(self) -> None:
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.config = load_config()
        self.broker = PicoBroker(PicoConnection())
        self.server = None
        self.server_thread: threading.Thread | None = None
        self.settings_dialog: QDialog | None = None

        self.tray = QSystemTrayIcon(self.app)
        self.tray.setToolTip(APP_NAME)
        if QIcon.hasThemeIcon("network-server"):
            self.tray.setIcon(QIcon.fromTheme("network-server"))
        else:
            self.tray.setIcon(self.app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.tray.setContextMenu(self._build_menu())
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        self.start_server()
        if bool(self.config.get("auto_connect", True)):
            self.connect_pico(show_error=False)
        QTimer.singleShot(100, self._update_tray_tooltip)

    def run(self) -> int:
        """Qt 이벤트 루프를 실행합니다."""

        return self.app.exec()

    def _build_menu(self) -> QMenu:
        """트레이 우클릭 메뉴를 구성합니다."""

        menu = QMenu()
        open_action = QAction("설정 열기", menu)
        open_action.triggered.connect(self.show_settings)
        start_action = QAction("서버 시작", menu)
        start_action.triggered.connect(self.start_server)
        stop_action = QAction("서버 중지", menu)
        stop_action.triggered.connect(self.stop_server)
        connect_action = QAction("Pico 연결", menu)
        connect_action.triggered.connect(lambda: self.connect_pico(show_error=True))
        disconnect_action = QAction("Pico 연결 해제", menu)
        disconnect_action.triggered.connect(self.disconnect_pico)
        quit_action = QAction("종료", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(open_action)
        menu.addSeparator()
        menu.addAction(start_action)
        menu.addAction(stop_action)
        menu.addSeparator()
        menu.addAction(connect_action)
        menu.addAction(disconnect_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        return menu

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """트레이 아이콘 더블클릭 시 설정 창을 엽니다."""

        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_settings()

    def server_url(self) -> str:
        """Manager/RagPilot이 사용할 로컬 서버 주소를 문자열로 반환합니다."""

        return f"http://{self.config.get('host', DEFAULT_HOST)}:{int(self.config.get('port', DEFAULT_PORT))}"

    def start_server(self) -> None:
        """HTTP 서버를 백그라운드 스레드에서 시작합니다."""

        if self.server is not None:
            self._update_tray_tooltip()
            return
        host = str(self.config.get("host", DEFAULT_HOST)).strip() or DEFAULT_HOST
        port = int(self.config.get("port", DEFAULT_PORT))
        if port_is_listening(host, port):
            self.tray.showMessage(APP_NAME, "이미 같은 주소에서 서버가 실행 중입니다.", QSystemTrayIcon.MessageIcon.Information, 2500)
            self._update_tray_tooltip(extra="외부 서버 감지")
            return
        try:
            self.server = make_server(host, port, self.broker)
        except OSError as error:
            self.tray.showMessage(APP_NAME, f"서버 시작 실패: {error}", QSystemTrayIcon.MessageIcon.Critical, 3500)
            self.server = None
            return
        self.server_thread = threading.Thread(target=self.server.serve_forever, name="pico-common-http", daemon=True)
        self.server_thread.start()
        self._update_tray_tooltip()

    def stop_server(self) -> None:
        """HTTP 서버만 중지합니다. Pico 연결은 사용자가 명시적으로 해제할 때만 닫습니다."""

        if self.server is None:
            self._update_tray_tooltip()
            return
        server = self.server
        self.server = None
        server.shutdown()
        server.server_close()
        self._update_tray_tooltip()

    def connect_pico(self, show_error: bool) -> None:
        """저장 포트를 우선 쓰고, 실패하거나 비어 있으면 Pico 후보 포트를 자동 탐색합니다."""

        port = str(self.config.get("pico_port", "")).strip()
        baudrate = int(self.config.get("baudrate", DEFAULT_BAUDRATE))
        try:
            if port:
                try:
                    self.broker.connection.connect(port, baudrate)
                    connected_port = port
                except Exception:
                    # 저장된 COM 번호가 바뀐 경우 자동 탐색으로 현재 Pico를 다시 찾습니다.
                    connected_port = self.broker.connection.auto_connect(baudrate)
            else:
                connected_port = self.broker.connection.auto_connect(baudrate)
            self.config["pico_port"] = connected_port
            self.config["baudrate"] = baudrate
            save_config(self.config)
            self.tray.showMessage(APP_NAME, f"Pico 연결됨: {connected_port}", QSystemTrayIcon.MessageIcon.Information, 2000)
        except Exception as error:
            if show_error:
                QMessageBox.warning(None, APP_NAME, str(error))
        self._update_tray_tooltip()

    def disconnect_pico(self) -> None:
        """Pico COM 포트 연결을 닫습니다."""

        self.broker.connection.disconnect()
        self._update_tray_tooltip()

    def show_settings(self) -> None:
        """서버 주소, Pico 포트, 자동 연결 여부를 확인하고 저장하는 설정 창을 엽니다."""

        if self.settings_dialog is not None:
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return

        dialog = QDialog()
        dialog.setWindowTitle(APP_NAME)
        dialog.setMinimumWidth(500)
        self.settings_dialog = dialog

        root = QVBoxLayout(dialog)
        form = QFormLayout()
        host_edit = QLineEdit(str(self.config.get("host", DEFAULT_HOST)))
        port_spin = QSpinBox()
        port_spin.setRange(1, 65535)
        port_spin.setValue(int(self.config.get("port", DEFAULT_PORT)))
        baudrate_spin = QSpinBox()
        baudrate_spin.setRange(1200, 1000000)
        baudrate_spin.setValue(int(self.config.get("baudrate", DEFAULT_BAUDRATE)))
        port_combo = QComboBox()
        auto_check = QCheckBox("프로그램 시작 시 Pico 자동 연결")
        auto_check.setChecked(bool(self.config.get("auto_connect", True)))
        self._fill_port_combo(port_combo)
        status_label = QLabel(self._status_text())
        form.addRow("서버 주소", host_edit)
        form.addRow("서버 포트", port_spin)
        form.addRow("Pico 포트", port_combo)
        form.addRow("Baudrate", baudrate_spin)
        form.addRow("자동 연결", auto_check)
        form.addRow("상태", status_label)
        root.addLayout(form)

        buttons = QHBoxLayout()
        refresh_button = QPushButton("포트 새로고침")
        save_button = QPushButton("저장")
        connect_button = QPushButton("Pico 연결")
        disconnect_button = QPushButton("연결 해제")
        close_button = QPushButton("닫기")
        buttons.addWidget(refresh_button)
        buttons.addStretch(1)
        buttons.addWidget(save_button)
        buttons.addWidget(connect_button)
        buttons.addWidget(disconnect_button)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

        def save_current() -> None:
            self.config["host"] = host_edit.text().strip() or DEFAULT_HOST
            self.config["port"] = int(port_spin.value())
            self.config["baudrate"] = int(baudrate_spin.value())
            self.config["pico_port"] = str(port_combo.currentData() or "").strip()
            self.config["auto_connect"] = bool(auto_check.isChecked())
            save_config(self.config)
            status_label.setText(self._status_text())

        refresh_button.clicked.connect(lambda: self._fill_port_combo(port_combo))
        save_button.clicked.connect(save_current)
        connect_button.clicked.connect(lambda: (save_current(), self.connect_pico(show_error=True), status_label.setText(self._status_text())))
        disconnect_button.clicked.connect(lambda: (self.disconnect_pico(), status_label.setText(self._status_text())))
        close_button.clicked.connect(dialog.close)
        dialog.finished.connect(lambda _result: setattr(self, "settings_dialog", None))
        dialog.show()

    def _fill_port_combo(self, combo: QComboBox) -> None:
        """현재 Windows에서 보이는 COM 포트를 설정 콤보박스에 채웁니다."""

        selected = str(self.config.get("pico_port", "")).strip()
        combo.clear()
        combo.addItem("자동 선택", "")
        for port in PicoConnection.available_ports():
            device = port.get("device", "")
            description = port.get("description", "")
            combo.addItem(f"{device} - {description}", device)
        for index in range(combo.count()):
            if combo.itemData(index) == selected:
                combo.setCurrentIndex(index)
                break

    def _status_text(self) -> str:
        """설정 창과 트레이 툴팁에 표시할 현재 상태 문구를 만듭니다."""

        server_state = "실행 중" if self.server is not None else "중지"
        pico_state = "연결됨" if self.broker.connection.is_connected() else "미연결"
        port = self.broker.connection.port or "-"
        return f"서버 {server_state} / Pico {pico_state} ({port}) / {self.server_url()}"

    def _update_tray_tooltip(self, extra: str = "") -> None:
        """트레이 아이콘 툴팁을 최신 서버/Pico 상태로 갱신합니다."""

        text = self._status_text()
        if extra:
            text = f"{text}\n{extra}"
        self.tray.setToolTip(text)

    def quit(self) -> None:
        """서버와 Pico 연결을 정리하고 트레이 앱을 종료합니다."""

        self.stop_server()
        self.disconnect_pico()
        self.tray.hide()
        self.app.quit()


def main() -> int:
    """단일 인스턴스를 보장한 뒤 트레이 앱을 실행합니다."""

    mutex = acquire_single_instance_mutex()
    if mutex is None:
        return 0
    tray = PicoCommonTray()
    return tray.run()
