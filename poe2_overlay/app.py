"""앱 진입점: 로그 감시 → 트래커 → 오버레이."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon

from . import config
from .guide import Guide
from .logparse import parse_line
from .logtail import LogTail, iter_lines
from .rewards import RewardTable
from .tracker import Character, PLACEHOLDERS, Tracker
from .ui import Overlay, make_icon
from .winutil import HotkeyManager, set_click_through

HOTKEYS = {
    "next": "Ctrl+Alt+Right",
    "prev": "Ctrl+Alt+Left",
    "click_through": "Ctrl+Alt+T",
    "toggle": "Ctrl+Alt+H",
    "rewards": "Ctrl+Alt+R",
}


class Controller:
    def __init__(self, app: QApplication):
        self.app = app
        self.settings = config.load_settings()
        self.guide = Guide.load(config.find_guide(self.settings.get("guide_path", "")))
        self.log_path: Optional[Path] = config.find_log(self.settings.get("log_path", ""))
        self.rewards = RewardTable.load(config.resource_dir() / "guides" / "rewards_ko.json")
        self.tracker = Tracker(self.guide)
        self.tail: Optional[LogTail] = None
        self.dirty = False
        self.notice = ""
        self.game_cfg = config.find_game_config()
        self._cfg_mtime = None
        self._ticks = 0

        self.overlay = Overlay(self.settings)
        self.overlay.menu_builder = self.build_menu
        self.overlay.moved.connect(self.on_moved)

        self.tray = QSystemTrayIcon(make_icon())
        self.tray.setToolTip("POE2 캠페인 가이드")
        self.tray.activated.connect(self.on_tray)
        self.tray_menu = QMenu()
        self.tray_menu.aboutToShow.connect(lambda: self.build_menu(self.tray_menu, clear=True))
        self.tray.setContextMenu(self.tray_menu)
        self.tray.show()

        self.hotkeys = HotkeyManager()
        app.installNativeEventFilter(self.hotkeys)
        self.hotkeys.register(HOTKEYS["next"], lambda: self.step(1))
        self.hotkeys.register(HOTKEYS["prev"], lambda: self.step(-1))
        self.hotkeys.register(HOTKEYS["click_through"], self.toggle_click_through)
        self.hotkeys.register(HOTKEYS["toggle"], self.toggle_visible)
        # 다른 프로그램이 이미 쓰는 키면 다음 후보로 (실제 등록된 키를 메뉴에 표시)
        for key in (HOTKEYS["rewards"], "Ctrl+Alt+B", "Ctrl+Alt+J", "Ctrl+Alt+F9"):
            if self.hotkeys.register(key, self.toggle_rewards):
                HOTKEYS["rewards"] = key
                break
        self.hotkeys.failed = [k for k in self.hotkeys.failed if k != "Ctrl+Alt+R"]
        if self.hotkeys.failed:
            self.notice = "단축키 등록 실패: " + ", ".join(self.hotkeys.failed)

        self.bootstrap()

        self.timer = QTimer()
        self.timer.timeout.connect(self.poll)
        self.timer.start(300)
        self.save_timer = QTimer()
        self.save_timer.timeout.connect(self.save)
        self.save_timer.start(5000)
        app.aboutToQuit.connect(self.shutdown)

        self.overlay.show()
        if self.settings.get("click_through"):
            self.toggle_click_through()
        self.refresh()

        # 개발용: 화면 캡처를 파일로 남긴다.
        if os.environ.get("POE2_OVERLAY_SHOW_REWARDS"):
            self.toggle_rewards()
        if snap := os.environ.get("POE2_OVERLAY_SNAPSHOT"):
            QTimer.singleShot(1500, lambda: self.overlay.grab().save(snap))

    # ---------------------------------------------------------- 로그
    def bootstrap(self) -> None:
        """저장된 진행도를 불러오고, 그 뒤로 쌓인 로그를 재생해서 현재 상태를 맞춘다."""
        if not self.log_path:
            self.notice = "로그 파일을 찾지 못했습니다. 메뉴 → 로그 파일 선택"
            return
        size = self.log_path.stat().st_size
        saved = config.load_progress()
        start = 0
        if saved.get("log_path") == str(self.log_path) and 0 <= saved.get("offset", -1) <= size:
            chars = {k: Character.from_dict(v) for k, v in saved.get("characters", {}).items()}
            self.tracker = Tracker(self.guide, chars, saved.get("current"))
            self.tracker.pid = saved.get("pid")
            if not saved.get("confirmed", True):
                self.tracker.restore_pending(saved.get("pending", []), saved.get("pending_scene", ""))
                if self.tracker.provisional:
                    self.tracker.provisional.mode = saved.get("pending_mode", "")
            start = saved["offset"]
        for ln in iter_lines(self.log_path, start, size):
            if ev := parse_line(ln):
                self.tracker.feed(ev)
        self.tail = LogTail(self.log_path, size)
        self.dirty = True
        # 과거 로그 재생이 끝난 뒤에만 현재 리그를 적용 (옛 캐릭터에 현재 리그가 찍히지 않도록)
        self._cfg_mtime = None
        self.check_league()

    def check_league(self) -> bool:
        """게임 설정 파일의 league_selected 가 바뀌면 현재 캐릭터에 반영한다."""
        cfg = self.game_cfg
        try:
            mtime = cfg.stat().st_mtime if cfg else None
        except OSError:
            mtime = None
        if mtime == self._cfg_mtime:
            return False
        self._cfg_mtime = mtime
        league = config.read_league(cfg)
        if league == self.tracker.league:
            return False
        self.tracker.league = league
        if league and (c := self.tracker._active()):
            c.league = league
        self.dirty = True
        return True

    def poll(self) -> None:
        if not self.tail:
            return
        self._ticks += 1
        changed = self._ticks % 7 == 0 and self.check_league()
        for ln in self.tail.read_new():
            if ev := parse_line(ln):
                self.tracker.feed(ev)
                changed = True
        if changed:
            self.dirty = True
            self.refresh()

    def refresh(self) -> None:
        snap = self.tracker.snapshot(int(self.settings.get("upcoming", 3)))
        states = self.rewards.evaluate(snap.character.rewards) if snap.character else []
        self.overlay.render(snap, self.notice, states, self.rewards.quest_passive_total)

    def save(self) -> None:
        if not self.dirty or not self.tail:
            return
        chars = {k: v.to_dict() for k, v in self.tracker.chars.items() if k not in PLACEHOLDERS}
        config.save_progress({
            "log_path": str(self.log_path),
            "offset": self.tail.offset,
            "current": self.tracker.current,
            "pid": self.tracker.pid,
            "confirmed": self.tracker.confirmed,
            "pending": [[p.code, p.level, p.ts] for p in self.tracker.pending],
            "pending_scene": self.tracker.provisional.area_name if self.tracker.provisional else "",
            "pending_mode": self.tracker.provisional.mode if self.tracker.provisional else "",
            "characters": chars,
        })
        self.dirty = False

    def shutdown(self) -> None:
        self.save()
        self.settings["click_through"] = self.overlay.click_through
        config.save_settings(self.settings)
        self.hotkeys.unregister_all()

    # ---------------------------------------------------------- 조작
    def step(self, delta: int) -> None:
        self.tracker.move_cursor(delta)
        self.dirty = True
        self.refresh()

    def toggle_click_through(self) -> None:
        self.overlay.click_through = not self.overlay.click_through
        set_click_through(int(self.overlay.winId()), self.overlay.click_through)
        self.refresh()

    def toggle_rewards(self) -> None:
        self.overlay.show_rewards = not self.overlay.show_rewards
        self.refresh()

    def toggle_visible(self) -> None:
        self.overlay.setVisible(not self.overlay.isVisible())

    def on_tray(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_visible()

    def on_moved(self, x: int, y: int) -> None:
        self.settings["window"].update(x=x, y=y)
        config.save_settings(self.settings)

    def select_character(self, name: Optional[str]) -> None:
        self.tracker.select_character(name)
        self.dirty = True
        self.refresh()

    def set_mode(self, mode: str) -> None:
        self.tracker.set_mode(mode)
        self.dirty = True
        self.save()
        self.refresh()

    def choose_log(self) -> None:
        path, _ = QFileDialog.getOpenFileName(None, "POE2 로그 파일 선택", "", "로그 (*.txt)")
        if path:
            self.settings["log_path"] = path
            config.save_settings(self.settings)
            self.log_path = Path(path)
            self.tracker = Tracker(self.guide)
            self.notice = ""
            self.bootstrap()
            self.refresh()

    def choose_guide(self) -> None:
        path, _ = QFileDialog.getOpenFileName(None, "가이드 CSV 선택", "", "CSV (*.csv)")
        if path:
            self.settings["guide_path"] = path
            config.save_settings(self.settings)
            self.guide = Guide.load(Path(path))
            self.tracker.set_guide(self.guide)
            self.dirty = True
            self.refresh()

    def build_menu(self, m: QMenu, clear: bool = False) -> None:
        if clear:
            m.clear()
        m.addAction(f"다음 단계  ({HOTKEYS['next']})", lambda: self.step(1))
        m.addAction(f"이전 단계  ({HOTKEYS['prev']})", lambda: self.step(-1))
        m.addSeparator()

        cm = m.addMenu("캐릭터")
        grp = QActionGroup(cm)
        auto = QAction("자동 인식", cm, checkable=True)
        auto.setChecked(not self.tracker.manual_lock)
        auto.triggered.connect(lambda: self.select_character(None))
        grp.addAction(auto)
        cm.addAction(auto)
        cm.addSeparator()
        chars = sorted((c for c in self.tracker.chars.values() if c.name not in PLACEHOLDERS),
                       key=lambda c: c.last_seen, reverse=True)
        for c in chars[:15]:
            a = QAction(f"{c.name}  ({c.cls} Lv{c.level})", cm, checkable=True)
            a.setChecked(self.tracker.manual_lock and self.tracker.current == c.name)
            a.triggered.connect(lambda _=False, n=c.name: self.select_character(n))
            grp.addAction(a)
            cm.addAction(a)

        cur = self.tracker.snapshot().character
        mm = m.addMenu(f"모드: {cur.mode or '미지정'}" if cur else "모드")
        mm.setEnabled(cur is not None)
        mgrp = QActionGroup(mm)
        for mode in ("", "소프트코어", "하드코어", "SSF", "HC SSF"):
            a = QAction(mode or "미지정", mm, checkable=True)
            a.setChecked(bool(cur) and cur.mode == mode)
            a.triggered.connect(lambda _=False, md=mode: self.set_mode(md))
            mgrp.addAction(a)
            mm.addAction(a)

        ct = QAction(f"클릭 통과  ({HOTKEYS['click_through']})", m, checkable=True)
        ct.setChecked(self.overlay.click_through)
        ct.triggered.connect(self.toggle_click_through)
        m.addAction(ct)
        m.addAction(f"숨기기/보이기  ({HOTKEYS['toggle']})", self.toggle_visible)
        m.addAction(f"영구 보상 전체 목록  ({HOTKEYS['rewards']})", self.toggle_rewards)
        m.addSeparator()
        m.addAction("가이드 CSV 선택…", self.choose_guide)
        m.addAction("가이드 파일 열기", lambda: os.startfile(self.guide.source))
        m.addAction("로그 파일 선택…", self.choose_log)
        info = m.addAction(f"가이드: {Path(self.guide.source).name} ({len(self.guide)}단계)")
        info.setEnabled(False)
        info2 = m.addAction(f"로그: {self.log_path or '없음'}")
        info2.setEnabled(False)
        m.addSeparator()
        m.addAction("종료", self.app.quit)


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("poe2-overlay")
    ctl = Controller(app)  # noqa: F841 - 이벤트 루프 동안 유지
    return app.exec()
