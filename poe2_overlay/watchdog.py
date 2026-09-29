"""멈춤 진단: 화면 스레드가 5초 넘게 응답하지 않으면 모든 스레드의 호출 위치를 로그 파일에 남긴다.

오버레이가 '응답 없음'으로 닫혀도 다음에 원인을 찾을 수 있게 한다.
로그: %APPDATA%\\poe2-overlay\\overlay.log (1MB 넘으면 새로 시작)
"""
from __future__ import annotations

import faulthandler
import threading
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
        self.write(f"시작 (pid {__import__('os').getpid()})")
        faulthandler.enable(self.file)  # 비정상 종료도 기록
        self.beat = time.monotonic()
        self._reported = False
        threading.Thread(target=self._run, name="watchdog", daemon=True).start()

    def write(self, msg: str) -> None:
        self.file.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")

    def heartbeat(self) -> None:
        """화면 스레드의 타이머에서 호출."""
        if self._reported:
            self.write(f"응답 회복 ({time.monotonic() - self.beat:.1f}초 멈춤)")
            self._reported = False
        self.beat = time.monotonic()

    def _run(self) -> None:
        while True:
            time.sleep(1.0)
            stalled = time.monotonic() - self.beat
            if stalled > STALL_SEC and not self._reported:
                self._reported = True
                self.write(f"화면 스레드 {stalled:.1f}초 멈춤 — 스레드별 호출 위치:")
                faulthandler.dump_traceback(self.file, all_threads=True)
