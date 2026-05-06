from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Mapping


# Pico 펌웨어와 맞춘 고정 8바이트 명령 코드입니다.
CMD_KBD_DOWN = 0x11
CMD_KBD_UP = 0x12
CMD_MOUSE_MOVE = 0x20
CMD_MOUSE_BTN_SET = 0x21
CMD_MOUSE_MOVE_ABS = 0x22
CMD_DELAY_MS = 0x30

# ACK 요청은 마지막 패킷에만 붙여서 한 묶음 명령의 완료 여부를 확인합니다.
FLAG_ACK_REQUEST = 0x01
ACK_BYTE = b"\x06"
NACK_BYTE = b"\x15"

# HID 마우스 버튼 비트입니다.
MOUSE_LEFT = 0x01
MOUSE_RIGHT = 0x02
MOUSE_MIDDLE = 0x04
MOUSE_X1 = 0x08
MOUSE_X2 = 0x10

# HID modifier 비트입니다. Pico 펌웨어의 키보드 리포트 규칙과 맞춥니다.
MODIFIER_MAP = {
    "ctrl": 0x01,
    "control": 0x01,
    "shift": 0x02,
    "alt": 0x04,
    "win": 0x08,
    "windows": 0x08,
    "gui": 0x08,
}

# Manager와 RagPilot 양쪽에서 쓰는 키 이름을 HID keycode로 변환하기 위한 표입니다.
KEYCODE_MAP = {
    "a": 0x04,
    "b": 0x05,
    "c": 0x06,
    "d": 0x07,
    "e": 0x08,
    "f": 0x09,
    "g": 0x0A,
    "h": 0x0B,
    "i": 0x0C,
    "j": 0x0D,
    "k": 0x0E,
    "l": 0x0F,
    "m": 0x10,
    "n": 0x11,
    "o": 0x12,
    "p": 0x13,
    "q": 0x14,
    "r": 0x15,
    "s": 0x16,
    "t": 0x17,
    "u": 0x18,
    "v": 0x19,
    "w": 0x1A,
    "x": 0x1B,
    "y": 0x1C,
    "z": 0x1D,
    "1": 0x1E,
    "2": 0x1F,
    "3": 0x20,
    "4": 0x21,
    "5": 0x22,
    "6": 0x23,
    "7": 0x24,
    "8": 0x25,
    "9": 0x26,
    "0": 0x27,
    "enter": 0x28,
    "return": 0x28,
    "esc": 0x29,
    "escape": 0x29,
    "backspace": 0x2A,
    "tab": 0x2B,
    "space": 0x2C,
    "insert": 0x49,
    "home": 0x4A,
    "pageup": 0x4B,
    "page up": 0x4B,
    "delete": 0x4C,
    "end": 0x4D,
    "pagedown": 0x4E,
    "page down": 0x4E,
    "right": 0x4F,
    "left": 0x50,
    "down": 0x51,
    "up": 0x52,
    "pause": 0x48,
    "num/": 0x54,
    "num*": 0x55,
    "num-": 0x56,
    "num+": 0x57,
    "numenter": 0x58,
    "num1": 0x59,
    "num2": 0x5A,
    "num3": 0x5B,
    "num4": 0x5C,
    "num5": 0x5D,
    "num6": 0x5E,
    "num7": 0x5F,
    "num8": 0x60,
    "num9": 0x61,
    "num0": 0x62,
    "numdecimal": 0x63,
}

for number in range(1, 13):
    KEYCODE_MAP[f"f{number}"] = 0x3A + (number - 1)
for number in range(13, 25):
    KEYCODE_MAP[f"f{number}"] = 0x68 + (number - 13)


@dataclass(slots=True)
class PicoPacket:
    """Pico로 보내는 고정 8바이트 패킷입니다."""

    cmd: int
    p1: int = 0
    p2: int = 0
    p3: int = 0
    p4: int = 0
    p5: int = 0
    p6: int = 0
    flags: int = 0

    def to_bytes(self) -> bytes:
        """각 필드를 unsigned 1바이트로 잘라 Pico 전송용 bytes로 만듭니다."""

        return bytes([
            self.cmd & 0xFF,
            self.p1 & 0xFF,
            self.p2 & 0xFF,
            self.p3 & 0xFF,
            self.p4 & 0xFF,
            self.p5 & 0xFF,
            self.p6 & 0xFF,
            self.flags & 0xFF,
        ])

    def with_ack(self) -> PicoPacket:
        """이 패킷 실행 뒤 Pico가 ACK를 돌려주도록 플래그를 추가합니다."""

        return PicoPacket(self.cmd, self.p1, self.p2, self.p3, self.p4, self.p5, self.p6, self.flags | FLAG_ACK_REQUEST)


def hotkey_to_hid(hotkey_text: str) -> tuple[int, int]:
    """`Ctrl+F1` 같은 문자열을 HID modifier/keycode 쌍으로 변환합니다."""

    parts = [part.strip() for part in str(hotkey_text).split("+") if part.strip()]
    modifier = 0
    keycode: int | None = None
    for raw_part in parts:
        part = raw_part.lower().replace(" ", "")
        if part in MODIFIER_MAP:
            modifier |= MODIFIER_MAP[part]
            continue
        normalized = _normalize_key_name(part)
        if normalized in KEYCODE_MAP:
            keycode = KEYCODE_MAP[normalized]
            continue
    if keycode is None:
        raise ValueError(f"지원하지 않는 키 입력입니다: {hotkey_text}")
    return modifier, keycode


def steps_to_packets(steps: list[Mapping[str, object]]) -> list[PicoPacket]:
    """상위 모듈이 넘긴 step 배열을 Pico 패킷 목록으로 변환합니다."""

    packets: list[PicoPacket] = []
    for step in steps:
        packets.extend(_step_to_packets(step))
    return packets


def _step_to_packets(step: Mapping[str, object]) -> list[PicoPacket]:
    """step 하나를 1개 이상의 Pico 패킷으로 변환합니다."""

    op = str(step.get("op", "") or "").strip().lower()
    if not op:
        return []
    if op == "delay_ms":
        return [_delay_packet(int(step.get("delay_ms", 0) or 0))]
    if op == "key_down":
        modifier, keycode = _modifier_and_key_from_step(step)
        return [PicoPacket(CMD_KBD_DOWN, modifier, keycode)]
    if op == "modifier_down":
        modifier = _modifier_value(str(step.get("modifier_name", "") or ""))
        return [PicoPacket(CMD_KBD_DOWN, modifier, 0)]
    if op == "key_up":
        return [PicoPacket(CMD_KBD_UP)]
    if op in {"key_press", "combo_key_press"}:
        modifier, keycode = _modifier_and_key_from_step(step)
        hold_ms = int(step.get("hold_ms", 40) or 40)
        return [PicoPacket(CMD_KBD_DOWN, modifier, keycode), _delay_packet(hold_ms), PicoPacket(CMD_KBD_UP)]
    if op == "mouse_button_down":
        return [PicoPacket(CMD_MOUSE_BTN_SET, mouse_button_value(str(step.get("button_name", "") or step.get("button", "left") or "left")))]
    if op == "mouse_button_up":
        return [PicoPacket(CMD_MOUSE_BTN_SET, 0)]
    if op == "mouse_click":
        button = mouse_button_value(str(step.get("button_name", "") or step.get("button", "left") or "left"))
        hold_ms = int(step.get("hold_ms", 30) or 30)
        return [PicoPacket(CMD_MOUSE_BTN_SET, button), _delay_packet(hold_ms), PicoPacket(CMD_MOUSE_BTN_SET, 0)]
    if op == "mouse_move_abs":
        return [_mouse_move_abs_packet(int(step.get("x", 0) or 0), int(step.get("y", 0) or 0))]
    if op == "mouse_click_at":
        button = mouse_button_value(str(step.get("button_name", "") or step.get("button", "left") or "left"))
        hold_ms = int(step.get("hold_ms", 30) or 30)
        return [
            _mouse_move_abs_packet(int(step.get("x", 0) or 0), int(step.get("y", 0) or 0)),
            _delay_packet(40),
            PicoPacket(CMD_MOUSE_BTN_SET, button),
            _delay_packet(hold_ms),
            PicoPacket(CMD_MOUSE_BTN_SET, 0),
        ]
    raise ValueError(f"지원하지 않는 Pico step입니다: {op}")


def mouse_button_value(button_name: str) -> int:
    """문자열 마우스 버튼명을 HID 버튼 비트로 변환합니다."""

    key = str(button_name).lower().replace(" ", "")
    button_map = {
        "mouseleft": MOUSE_LEFT,
        "left": MOUSE_LEFT,
        "mouseright": MOUSE_RIGHT,
        "right": MOUSE_RIGHT,
        "mousemiddle": MOUSE_MIDDLE,
        "middle": MOUSE_MIDDLE,
        "mousex1": MOUSE_X1,
        "x1": MOUSE_X1,
        "mousex2": MOUSE_X2,
        "x2": MOUSE_X2,
    }
    if key not in button_map:
        raise ValueError(f"지원하지 않는 마우스 버튼입니다: {button_name}")
    return button_map[key]


def _modifier_and_key_from_step(step: Mapping[str, object]) -> tuple[int, int]:
    """step의 hotkey/key/modifier 표현 중 하나를 골라 HID 값으로 바꿉니다."""

    hotkey = str(step.get("hotkey", "") or step.get("key", "") or "")
    key_name = str(step.get("key_name", "") or "")
    modifier_name = str(step.get("modifier_name", "") or "")
    if hotkey:
        return hotkey_to_hid(hotkey)
    if modifier_name:
        return _modifier_value(modifier_name), _keycode_value(key_name)
    return 0, _keycode_value(key_name)


def _delay_packet(delay_ms: int) -> PicoPacket:
    """Pico 내부에서 대기할 delay 패킷을 만듭니다."""

    value = max(0, min(65_535, int(delay_ms)))
    return PicoPacket(CMD_DELAY_MS, value & 0xFF, (value >> 8) & 0xFF)


def _mouse_move_abs_packet(screen_x: int, screen_y: int) -> PicoPacket:
    """Windows 화면 좌표를 TinyUSB 절대 마우스 좌표로 바꾼 패킷을 만듭니다."""

    abs_x, abs_y = screen_to_absolute_hid(screen_x, screen_y)
    return PicoPacket(CMD_MOUSE_MOVE_ABS, 0, abs_x & 0xFF, (abs_x >> 8) & 0xFF, abs_y & 0xFF, (abs_y >> 8) & 0xFF)


def screen_to_absolute_hid(screen_x: int, screen_y: int) -> tuple[int, int]:
    """가상 데스크톱 좌표를 0~32767 범위 HID 좌표로 변환합니다."""

    user32 = ctypes.windll.user32
    left = int(user32.GetSystemMetrics(76))
    top = int(user32.GetSystemMetrics(77))
    width = max(1, int(user32.GetSystemMetrics(78)))
    height = max(1, int(user32.GetSystemMetrics(79)))
    relative_x = int(screen_x) - left
    relative_y = int(screen_y) - top
    clamped_x = max(0, min(width - 1, relative_x))
    clamped_y = max(0, min(height - 1, relative_y))
    return (
        int(clamped_x * 32767 / max(1, width - 1)),
        int(clamped_y * 32767 / max(1, height - 1)),
    )


def _modifier_value(name: str) -> int:
    """modifier 이름을 HID modifier 비트로 변환합니다."""

    key = name.strip().lower()
    if key not in MODIFIER_MAP:
        raise ValueError(f"지원하지 않는 modifier입니다: {name}")
    return MODIFIER_MAP[key]


def _keycode_value(name: str) -> int:
    """키 이름을 HID keycode로 변환합니다."""

    key = _normalize_key_name(name)
    if key not in KEYCODE_MAP:
        raise ValueError(f"지원하지 않는 키 입력입니다: {name}")
    return KEYCODE_MAP[key]


def _normalize_key_name(name: str) -> str:
    """표기 흔들림이 있는 키 이름을 keycode table 이름으로 정규화합니다."""

    key = str(name).strip().lower().replace(" ", "")
    aliases = {
        "pageup": "pageup",
        "pagedown": "pagedown",
        "return": "enter",
        "escape": "esc",
    }
    return aliases.get(key, key)
