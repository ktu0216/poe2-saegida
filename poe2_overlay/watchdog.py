"""멈춤 진단: 화면 스레드가 5초 넘게 응답하지 않으면 모든 스레드의 호출 위치를 로그 파일에 남긴다.

오버레이가 '응답 없음'으로 닫혀도 다음에 원인을 찾을 수 있게 한다.
화면 스레드가 Qt·Windows 함수 안에서 멈추면 파이썬 스레드는 돌지 못하므로(GIL),
기록은 faulthandler 의 C 수준 타이머(dump_traceback_later)로 한다. 1초마다 다시 걸어 두고,
5초 안에 다시 걸지 못하면(= 멈춤) 그때의 호출 위치가 기록된다.
로그: %APPDATA%\\poe2-saegida\\overlay.log (1MB 넘으면 새로 시작)
"""
from __future__ import annotations

import faulthandler
import functools
import os
import time
from datetime import datetime
from pathlib import Path

STALL_SEC = 5.0


class Watchdog:
    def __init__(self, log_path: Path):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if log_path.exists() and log_path.stat().st_size > 1_000_000:
            log_path.unlink()
        self.file = open(log_path, "a", encoding="utf-8", buffering=1)
        self.write(f"시작 (pid {os.getpid()})")
        global _active
        _active = self
        faulthandler.enable(self.file)  # 비정상 종료도 기록
        self.heartbeat()

    def write(self, msg: str) -> None:
        self.file.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
        self.file.flush()

    def heartbeat(self) -> None:
        """화면 스레드의 타이머에서 1초마다 호출: 멈춤 기록 타이머를 다시 건다."""
        faulthandler.dump_traceback_later(STALL_SEC, repeat=False, file=self.file, exit=False)

    def stop(self) -> None:
        faulthandler.cancel_dump_traceback_later()


SLOW_SEC = 1.5
_active: "Watchdog | None" = None


def timed(name: str):
    """오래 걸린 작업 이름을 기록하는 데코레이터 (멈춤이 어느 작업에서 났는지 좁히기 위해)."""
    def wrap(fn):
        @functools.wraps(fn)
        def inner(*a, **kw):
            t0 = time.monotonic()
            try:
                return fn(*a, **kw)
            finally:
                dt = time.monotonic() - t0
                if dt > SLOW_SEC and _active is not None:
                    _active.write(f"느린 작업: {name} {dt:.1f}초")
        return inner
    return wrap
