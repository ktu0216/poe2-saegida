"""Windows 전용: 전역 단축키(RegisterHotKey)와 클릭 통과 창 스타일."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter

user32 = ctypes.windll.user32

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000
WM_HOTKEY = 0x0312
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000

VK = {"LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28}

user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]


def parse_hotkey(spec: str) -> tuple[int, int]:
    """'Ctrl+Alt+Right' -> (modifiers, vk)"""
    mods, vk = MOD_NOREPEAT, 0
    for part in spec.split("+"):
        p = part.strip().upper()
        if p in ("CTRL", "CONTROL"):
            mods |= MOD_CONTROL
        elif p == "ALT":
            mods |= MOD_ALT
        elif p == "SHIFT":
            mods |= MOD_SHIFT
        elif p in VK:
            vk = VK[p]
        elif len(p) == 1:
            vk = ord(p)
        elif p.startswith("F") and p[1:].isdigit():
            vk = 0x70 + int(p[1:]) - 1
    return mods, vk


class HotkeyManager(QAbstractNativeEventFilter):
    def __init__(self):
        super().__init__()
        self._handlers: dict[int, Callable[[], None]] = {}
        self._next_id = 1
        self.failed: list[str] = []

    def register(self, spec: str, handler: Callable[[], None]) -> bool:
        mods, vk = parse_hotkey(spec)
        hid = self._next_id
        self._next_id += 1
        if not vk or not user32.RegisterHotKey(None, hid, mods, vk):
            self.failed.append(spec)
            return False
        self._handlers[hid] = handler
        return True

    def unregister_all(self) -> None:
        for hid in self._handlers:
            user32.UnregisterHotKey(None, hid)
        self._handlers.clear()

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam in self._handlers:
                self._handlers[msg.wParam]()
                return True, 0
        return False, 0


kernel32 = ctypes.windll.kernel32
TH32CS_SNAPPROCESS = 0x2
GAME_EXE_PREFIX = "pathofexile"  # PathOfExile.exe, PathOfExile_x64Steam.exe, PathOfExile_KG.exe ...


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
user32.GetForegroundWindow.restype = wintypes.HWND


def game_pids() -> set[int]:
    """실행 중인 POE 클라이언트 PID. 프로세스를 열지 않으므로 관리자 권한 게임도 보인다."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return set()
    pids = set()
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            if e.szExeFile.lower().startswith(GAME_EXE_PREFIX):
                pids.add(e.th32ProcessID)
            ok = kernel32.Process32NextW(snap, ctypes.byref(e))
    finally:
        kernel32.CloseHandle(snap)
    return pids


def foreground_pid() -> int:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return 0
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def set_click_through(hwnd: int, enabled: bool) -> None:
    style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    style |= WS_EX_LAYERED | WS_EX_NOACTIVATE
    if enabled:
        style |= WS_EX_TRANSPARENT
    else:
        style &= ~WS_EX_TRANSPARENT
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)
