"""앱 진입점: 로그 감시 → 트래커 → 오버레이."""
from __future__ import annotations

import html
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon

from . import config
from .guide import Guide, is_town
from .logparse import parse_line
from .logtail import LogTail, iter_lines
from .regex import RegexBook
from .builds import GemNames, families, family_of, pick_stage, plan, scan
from .encounters import Encounters
from .items import compare, defense_score, is_item_text, parse_item, slot_keys
from .rewards import RewardTable
from .tracker import MAX_GAP, Character, PLACEHOLDERS, Tracker, parse_ts
from .ui import Overlay, make_icon
from .timing import personal_bests, timer_view
from .winutil import HotkeyManager, foreground_pid, game_pids, game_window_rect, set_click_through

HOTKEYS = {
    "next": "Ctrl+Alt+Right",
    "prev": "Ctrl+Alt+Left",
    "click_through": "Ctrl+Alt+T",
    "toggle": "Ctrl+Alt+H",
    "rewards": "Ctrl+Alt+R",
    "opacity_up": "Ctrl+Alt+Up",
    "opacity_down": "Ctrl+Alt+Down",
    "copy_regex": "Ctrl+Alt+C",
    "auto_hide": "Ctrl+Alt+A",
    "equip": "Ctrl+Alt+E",
    "gems": "Ctrl+Alt+G",
}
OPACITY_STEPS = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3)
TOP_RATIO = 0.14  # 기본 위치: 게임 창 왼쪽, 위에서 14% (왼쪽 위 버프·스킬 아이콘 아래)
DOUBLE_COPY_SEC = 0.8  # 이보다 느린 재복사는 '다시 비교'로 본다
PROGRESS_VERSION = 18  # 18: 전직 단계, 2: 플레이 시간/액트 스플릿, 3: 되돌아간 지역 건너뛰기 수정, 4: 같은 이름 새 캐릭터 분리, 5: 보스 처치 전 마을 방문은 단계 유지, 6: NPC 단계 이름 보스 목록에서 제외, 7: 하위 지역 보스, 8: 재접속 시 직전 캐릭터 우선 추정 (이전 저장본은 로그 전체를 다시 읽는다)


class Controller:
    def __init__(self, app: QApplication):
        self.app = app
        self.settings = config.load_settings()
        self.guide = Guide.load(config.find_guide(self.settings.get("guide_path", "")))
        self.log_path: Optional[Path] = config.find_log(self.settings.get("log_path", ""))
        self.rewards = RewardTable.load(config.resource_dir() / "guides" / "rewards_ko.json")
        self.regex_book = RegexBook.load(config.resource_dir() / "guides" / "regex_ko.json")
        self.active_builds: dict[str, str] = {}
        self.gem_names = GemNames.load(config.find_reim_gem_data(), config.resource_dir() / "guides" / "gem_names_ko.json",
                                       config.resource_dir() / "guides" / "gem_names_trade.json")
        self.build_files = scan(config.build_planner_dir() or Path())
        self._last_level: dict[str, int] = {}
        self.current_regex = None
        self._regex_copied_at = 0.0
        self.flash = ""  # 잠깐 보여줄 알림 (정규식 복사됨 등)
        self.encounters = Encounters.load(config.resource_dir() / "guides" / "encounters_ko.json")
        self.tracker = Tracker(self.guide, encounters=self.encounters)
        self.tail: Optional[LogTail] = None
        self.dirty = False
        self.notice = ""
        self.game_cfg = config.find_game_config()
        self._cfg_mtime = None
        self._ticks = 0
        self.user_hidden = False  # Ctrl+Alt+H 로 직접 숨긴 상태
        self.game_running = False
        self._pbs: dict[str, float] = {}
        self._pbs_for: Optional[str] = None

        self.overlay = Overlay(self.settings)
        self.overlay.menu_builder = self.build_menu
        self.overlay.moved.connect(self.on_moved)
        self.overlay.mode_chosen.connect(self.choose_new_char_mode)

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
        self.hotkeys.register(HOTKEYS["auto_hide"], self.toggle_auto_hide)
        self.hotkeys.register(HOTKEYS["equip"], self.set_equipped)
        for key in (HOTKEYS["gems"], "Ctrl+Alt+J", "Ctrl+Alt+F11"):  # 다른 프로그램이 쓰면 다음 후보
            if self.hotkeys.register(key, self.toggle_gem_card):
                HOTKEYS["gems"] = key
                break
        self.show_gem_card = False
        # 게임에서 아이템에 Ctrl+C → 클립보드 감시로 장착 아이템과 비교
        self.item_msg = ""
        self.item_color = "#e8b04a"
        self.last_item_text = ""
        self.compare_target = ""  # 마지막으로 비교한 장착 칸 (Ctrl+Alt+E 가 바꿀 칸)
        self.prev_copied: dict[str, str] = {}  # 부위 -> 직전에 복사한 아이템 (장착 기준이 없을 때 비교용)
        self._last_copy_at = 0.0
        self._tab_until = 0.0
        self._item_clear = QTimer()
        self._item_clear.setSingleShot(True)
        self._item_clear.timeout.connect(self._clear_item)
        app.clipboard().dataChanged.connect(self.on_clipboard)
        self.hotkeys.register(HOTKEYS["opacity_up"], lambda: self.change_opacity(0.1))
        self.hotkeys.register(HOTKEYS["opacity_down"], lambda: self.change_opacity(-0.1))
        # 다른 프로그램이 이미 쓰는 키면 다음 후보로 (실제 등록된 키를 메뉴에 표시)
        for key in (HOTKEYS["rewards"], "Ctrl+Alt+B", "Ctrl+Alt+J", "Ctrl+Alt+F9"):
            if self.hotkeys.register(key, self.toggle_rewards):
                HOTKEYS["rewards"] = key
                break
        for key in (HOTKEYS["copy_regex"], "Ctrl+Alt+Q", "Ctrl+Alt+F10"):
            if self.hotkeys.register(key, lambda: self.copy_regex(auto=False)):
                HOTKEYS["copy_regex"] = key
                break
        self.hotkeys.failed = [k for k in self.hotkeys.failed if k not in ("Ctrl+Alt+R", "Ctrl+Alt+C", "Ctrl+Alt+Q", "Ctrl+Alt+G", "Ctrl+Alt+J")]
        if self.hotkeys.failed:
            self.notice = "단축키 등록 실패: " + ", ".join(self.hotkeys.failed)

        self.bootstrap()

        self.timer = QTimer()
        self.timer.timeout.connect(self.poll)
        self.timer.start(300)
        self.save_timer = QTimer()
        self.save_timer.timeout.connect(self.save)
        self.save_timer.start(5000)
        self.clock = QTimer()  # 타이머 표시와 게임 포커스 확인
        self.clock.timeout.connect(self.tick)
        self.clock.start(1000)
        app.aboutToQuit.connect(self.shutdown)

        self.overlay.setWindowOpacity(float(self.settings.get("window_opacity", 1.0)))
        self.overlay.show()
        set_click_through(int(self.overlay.winId()), False)  # 클릭해도 게임 포커스를 뺏지 않게
        set_click_through(int(self.overlay.toast.winId()), True)  # 알림 창은 보기만: 항상 클릭 통과
        # 저장된 위치가 없으면 게임 창 왼쪽 위(버프·스킬 아이콘 아래)에 붙인다. 게임 창을 찾을 때까지 tick 에서 재시도.
        self.auto_pos = self.settings["window"].get("x") is None
        self._auto_placed = False
        if self.auto_pos:
            self.place_default()
        if self.settings.get("click_through"):
            self.toggle_click_through()
        self.refresh()
        QTimer.singleShot(500, self.on_clipboard)  # 켜기 전에 복사해 둔 아이템도 처리
        if not self.auto_pos:
            QTimer.singleShot(300, self._clamp_saved)  # 저장된 위치가 화면 밖이면 안으로

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
        old_chars = saved.get("characters", {})
        migrate = saved.get("version", 1) < PROGRESS_VERSION
        if not migrate and saved.get("log_path") == str(self.log_path) and 0 <= saved.get("offset", -1) <= size:
            chars = {k: Character.from_dict(v) for k, v in saved.get("characters", {}).items()}
            self.tracker = Tracker(self.guide, chars, saved.get("current"), self.encounters)
            self.tracker.pid = saved.get("pid")
            self.tracker.last_ts = parse_ts(saved.get("last_ts") or "")
            self.tracker.afk = bool(saved.get("afk"))
            if not saved.get("confirmed", True):
                self.tracker.restore_pending(saved.get("pending", []), saved.get("pending_scene", ""))
                if saved.get("provisional"):  # 저장해 둔 추정본이 있으면 그대로 (재계산보다 정확)
                    self.tracker.provisional = Character.from_dict(saved["provisional"])
                    self.tracker._pending_play = float(saved.get("pending_play", 0.0))
                elif self.tracker.provisional:
                    self.tracker.provisional.mode = saved.get("pending_mode", "")
            start = saved["offset"]
        for ln in iter_lines(self.log_path, start, size):
            if ev := parse_line(ln):
                self.tracker.feed(ev)
        if migrate:  # 로그로 되살릴 수 없는 사용자 지정 값만 옮긴다
            for name, old in old_chars.items():
                if c := self.tracker.chars.get(name):
                    c.mode = old.get("mode", "") or c.mode
                    c.league = old.get("league", "") or c.league
                    c.gear = old.get("gear") or c.gear  # Ctrl+C 로 지정한 장착 기준도 로그로는 되살릴 수 없다
        self.tail = LogTail(self.log_path, size)
        self.dirty = True
        self._pbs_for = None
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
        self.active_builds = config.read_active_builds(cfg)  # 캐릭터 -> 빌드 플래너 이름
        self.build_files = scan(config.build_planner_dir() or Path())  # 빌드를 새로 받았을 수 있다
        league = config.read_league(cfg)
        if league == self.tracker.league:
            return True
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
            if self.regex_book.vendor_spoke(ln):
                self.copy_regex(auto=True)
            if ev := parse_line(ln):
                self.tracker.feed(ev)
                changed = True
        if changed:
            self.dirty = True
            self.refresh()

    def live_extra(self) -> float:
        """마지막 로그 이후 지금까지 흐른 시간 (게임 실행 중이고 자리 비움이 아닐 때만)."""
        t = self.tracker
        if not self.game_running or t.afk or t.last_ts is None:
            return 0.0
        gap = (datetime.now() - t.last_ts).total_seconds()
        return gap if 0 < gap <= MAX_GAP else 0.0

    def refresh(self) -> None:
        snap = self.tracker.snapshot(int(self.settings.get("upcoming", 3)))
        c = snap.character
        states = self.rewards.evaluate(c.rewards) if c else []
        timer = None
        if c and c.name not in PLACEHOLDERS[1:]:
            if self._pbs_for != c.name:  # PB 는 캐릭터가 바뀔 때만 다시 계산
                self._pbs = personal_bests(self.tracker.chars.values(), exclude=c.name)
                self._pbs_for = c.name
            pbs = self._pbs if self.settings.get("show_pb", False) else {}
            timer = timer_view(c, pbs, self.live_extra())
        rule = None
        if c and snap.step:
            rule = self.regex_book.select(self.active_builds.get(c.name, ""), c.cls, snap.step.act)
        self.current_regex = rule
        in_town = bool(c and is_town(c.zone))
        if c is not None and c.mode_prompt and (c.mode or c.cursor > 0):
            c.mode_prompt = False  # 이미 정했거나, 고르지 않고 다음 단계로 진행 → 비워 둔다
            self.dirty = True
        self.overlay.show_mode_prompt(bool(c and c.mode_prompt))
        gems = self.gem_plan(c, snap.step.act if snap.step else "")
        self._notify_level_up(c, gems)
        if self._boss_compact(snap):
            return
        self.overlay.render(snap, self.notice, states, self.rewards.quest_passive_total, timer,
                            rule if in_town else None, HOTKEYS["copy_regex"], self.flash, self.item_msg,
                            gems, self.gem_names, self.show_gem_card, self.item_color)

    # ---------------------------------------------------------- 보스전 간단 모드
    def _boss_compact(self, snap) -> bool:
        """곧 보스/보스 전투 중이면 패널을 한 줄로. 처리했으면 True."""
        c, f = snap.character, snap.flags
        subs = {k: v for k, v in f.get("sub", {}).items() if v == "engaged"}
        boss_state = f.get("boss")
        fighting = bool(subs) or boss_state == "engaged"
        soon = bool(f.get("soon")) and boss_state not in ("engaged", "killed", "died")
        on = (self.settings.get("boss_compact", True) and c is not None and snap.in_step_zone
              and (fighting or soon))
        if not on:
            if self.overlay.compact:
                self.overlay.leave_compact()
            return False
        if not self.overlay.compact:  # 막 시작됨 → Tab 안내
            self._tab_until = time.monotonic() + 3 if self.settings.get("tab_hint", True) else 0
        name = html.escape(next(iter(subs)) if subs else (snap.boss or "보스"))
        head = (f'<span style="color:#ff8a65">⚔ {name} 전투 중</span>' if fighting
                else f'<span style="color:#e8b04a">⚠ 곧 {name}</span>')
        gap = c.area_level - c.level if c.area_level else 0
        lv = f'<span style="color:{"#ff8a65" if gap >= 3 else "#9a9284"}"> · Lv {c.level} · 지역 {c.area_level}</span>'
        tab = (' <b style="color:#e8b04a">· Tab→미니맵</b>' if time.monotonic() < self._tab_until else "")
        self.overlay.render_compact(head + lv + tab)
        return True

    def toggle_gem_card(self) -> None:
        self.show_gem_card = not self.show_gem_card
        self.refresh()

    def toggle_setting(self, key: str) -> None:
        self.settings[key] = not self.settings.get(key, True)
        config.save_settings(self.settings)
        self.refresh()

    # ---------------------------------------------------------- 빌드 젬 안내
    def build_family(self, c) -> Optional[str]:
        """캐릭터의 빌드 묶음: 메뉴에서 고른 것 > 게임에 연결된 빌드."""
        chosen = self.settings.get("char_builds", {}).get(c.name)
        if chosen:
            return chosen
        name = self.active_builds.get(c.name)
        return family_of(self.build_files, name) if name else None

    def gem_plan(self, c, act: str):
        if c is None or c.name in PLACEHOLDERS:
            return None
        fam = self.build_family(c)
        files = families(self.build_files).get(fam) if fam else None
        stage = pick_stage(files, act, c.level) if files else None
        return plan(stage, c.level) if stage else None

    def _notify_level_up(self, c, gems) -> None:
        if c is None or gems is None:
            return
        prev = self._last_level.get(c.name)
        self._last_level[c.name] = c.level
        if prev is not None and c.level > prev and gems.unlocked_at:
            names = " · ".join(self.gem_names(g.id) for g in gems.unlocked_at)
            self.flash = f"💎 Lv {c.level} — {names} 장착 가능"
            QTimer.singleShot(10000, self._clear_flash)

    def set_char_build(self, family: Optional[str]) -> None:
        c = self.tracker.snapshot().character
        if c is None:
            return
        cb = self.settings.setdefault("char_builds", {})
        if family:
            cb[c.name] = family
        else:
            cb.pop(c.name, None)
        config.save_settings(self.settings)
        self.refresh()

    def copy_regex(self, auto: bool) -> None:
        """정규식을 클립보드에. auto 는 상인 인사로 호출된 경우 (마을에서만, 20초에 한 번)."""
        rule = self.current_regex
        if rule is None:
            return
        now = time.monotonic()
        if auto:
            c = self.tracker.snapshot().character
            if not self.settings.get("auto_copy_regex", True) or not (c and is_town(c.zone)):
                return
            if now - self._regex_copied_at < 20:
                return
        self._regex_copied_at = now
        QApplication.clipboard().setText(rule.regex)
        self.flash = f"📋 {rule.name} 정규식 복사됨 — 검색창에 Ctrl+V"
        QTimer.singleShot(4000, self._clear_flash)
        self.refresh()

    def on_clipboard(self) -> None:
        text = self.app.clipboard().text()
        if not is_item_text(text):
            return
        now = time.monotonic()
        if text == self.last_item_text:
            gap = now - self._last_copy_at
            if gap < 0.25:  # 복사 한 번에 알림이 여러 번 오는 경우
                return
            self._last_copy_at = now
            if gap <= DOUBLE_COPY_SEC:  # 같은 아이템을 연달아 두 번 (더블클릭처럼) = 장착 기준 등록
                self.set_equipped(via="두 번 복사")
            return
        self._last_copy_at = now
        item = parse_item(text)
        c = self.tracker.snapshot().character
        if item is None or c is None or "젬" in item.item_class:  # 스킬 창의 젬 복사는 장비 비교 대상이 아니다
            return
        self.last_item_text = text
        keys = slot_keys(item.slot)  # 반지는 두 칸
        label = lambda k: (k.replace("#", " ") if "#" in k else f"{k} 1") if len(keys) > 1 else item.slot
        if any(c.gear.get(k) == text for k in keys):
            k = next(k for k in keys if c.gear.get(k) == text)
            title, _, _ = compare(item, None)
            self._show_item(f'📌 장착 중 ({label(k)}) · {title}', "#9a9284")
            return
        empty = [k for k in keys if k not in c.gear]
        prev_text = self.prev_copied.get(item.slot)
        self.prev_copied[item.slot] = text
        if empty and is_town(c.zone) and len(empty) == len(keys):  # 마을에서 복사한 건 대부분 상점/창고 아이템
            hint = f'<br><span style="color:#9a9284">장착 기준 없음 — 장착 중인 아이템이면 한 번 더 Ctrl+C (또는 {HOTKEYS["equip"]}) 로 등록</span>'
            if prev_text and prev_text != text:  # 기준이 없으면 직전에 복사한 같은 부위 아이템과 비교
                title, diffs, verdict = compare(item, parse_item(prev_text))
                color = {1: "#8fd18b", -1: "#ff8a65"}.get(verdict, "#ece6da")
                mark = {1: "▲ 더 좋음", -1: "▼ 더 나쁨"}.get(verdict, "≈ 비슷")
                body = f'{mark} · {item.slot} {title} (직전 복사 대비)' + ("<br>" + " · ".join(diffs) if diffs else "")
                self._show_item(body + hint, color)
                return
            title, _, _ = compare(item, None)
            self._show_item(f'{item.slot} {title}' + hint, "#ece6da")
            return
        if empty and not is_town(c.zone):  # 마을 밖: 빈 칸 = 지금 장착 중인 아이템으로 본다
            c.gear[empty[0]] = text
            self.dirty = True
            title, _, _ = compare(item, None)
            self._show_item(f'📌 {label(empty[0])} 장착 기준 저장 · {title}', "#8fd18b")
            return
        # 비교 대상: 칸이 여러 개면 가장 약한 쪽 (바꾼다면 그걸 뺀다)
        filled = [k for k in keys if k in c.gear]
        target = min(filled, key=lambda k: defense_score(parse_item(c.gear[k])))
        self.compare_target = target
        title, diffs, verdict = compare(item, parse_item(c.gear[target]))
        color = {1: "#8fd18b", -1: "#ff8a65"}.get(verdict, "#ece6da")
        mark = {1: "▲ 더 좋음", -1: "▼ 더 나쁨"}.get(verdict, "≈ 비슷")
        body = f'{mark} · {item.slot} {title}' + (f" ({label(target)} 대비)" if len(keys) > 1 else "")
        if diffs:
            body += "<br>" + " · ".join(diffs)
        body += f'<br><span style="color:#9a9284">장착했다면 한 번 더 Ctrl+C (또는 {HOTKEYS["equip"]}) 로 기준 갱신</span>'
        self._show_item(body, color)

    def _show_item(self, html_text: str, color: str) -> None:
        self.item_color = color
        self.item_msg = f'<span style="color:{color}">{html_text}</span>'
        self._item_clear.start(30000)
        self.refresh()

    def _clear_item(self) -> None:
        self.item_msg = ""
        self.refresh()

    def set_equipped(self, via: str = "") -> None:
        """마지막으로 복사한 아이템을 그 부위의 장착 기준으로."""
        c = self.tracker.snapshot().character
        item = parse_item(self.last_item_text) if self.last_item_text else None
        if c is None or item is None:
            return
        keys = slot_keys(item.slot)
        if any(c.gear.get(k) == self.last_item_text for k in keys):
            return
        empty = [k for k in keys if k not in c.gear]
        # 빈 칸 > 마지막으로 비교한 칸(가장 약한 쪽) > 첫 칸
        key = empty[0] if empty else (self.compare_target if self.compare_target in keys else keys[0])
        c.gear[key] = self.last_item_text
        self.dirty = True
        title, _, _ = compare(item, None)
        name = (key.replace("#", " ") if "#" in key else f"{key} 1") if len(keys) > 1 else key
        how = f"{via} → " if via else ""
        self._show_item(f'📌 {how}{name} 장착 기준 등록 · {title}', "#8fd18b")

    def _clear_flash(self) -> None:
        self.flash = ""
        self.refresh()

    def place_default(self) -> None:
        """게임 창(없으면 주 모니터) 왼쪽 위, 버프·스킬 아이콘 아래. 게임 창 좌표는 물리 픽셀이라 모니터 배율로 나눈다."""
        margin = 8
        ratio = float(self.settings.get("top_ratio", TOP_RATIO))  # 게임 창 위에서부터의 높이 비율
        rect = game_window_rect()
        left = top = height = None
        if rect:
            cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
            for s in self.app.screens():
                g, d = s.geometry(), s.devicePixelRatio()
                if g.x() * d <= cx < (g.x() + g.width()) * d and g.y() * d <= cy < (g.y() + g.height()) * d:
                    left, top, height = int(rect[0] / d), int(rect[1] / d), (rect[3] - rect[1]) / d
                    break
            self._auto_placed = left is not None
        if left is None:
            g = self.app.primaryScreen().availableGeometry()
            left, top, height = g.x(), g.y(), g.height()
        self.overlay.move(left + margin, top + int(height * ratio))

    def _clamp_saved(self) -> None:
        self.overlay.clamp_to_screen()
        self.settings["window"].update(x=self.overlay.x(), y=self.overlay.y())
        config.save_settings(self.settings)

    def reset_position(self) -> None:
        self.settings["window"].update(x=None, y=None)
        config.save_settings(self.settings)
        self.auto_pos = True
        self.place_default()

    def tick(self) -> None:
        pids = game_pids()
        self.game_running = bool(pids)
        if self.auto_pos and pids and not self._auto_placed:
            self.place_default()  # 오버레이를 게임보다 먼저 켠 경우
        if self.settings.get("auto_hide", True) and not self.user_hidden:
            fg = foreground_pid()
            if fg != os.getpid():  # 오버레이 자신(메뉴 등)을 누른 경우는 그대로 둔다
                want = (fg in pids) or not pids  # 게임이 꺼져 있으면 보여준다
                if want != self.overlay.isVisible():
                    self.overlay.setVisible(want)
        if self.overlay.isVisible():
            self.refresh()

    def save(self) -> None:
        if not self.dirty or not self.tail:
            return
        chars = {k: v.to_dict() for k, v in self.tracker.chars.items() if k not in PLACEHOLDERS}
        config.save_progress({
            "log_path": str(self.log_path),
            "offset": self.tail.offset,
            "current": self.tracker.current,
            "pid": self.tracker.pid,
            "version": PROGRESS_VERSION,
            "last_ts": self.tracker.last_ts.strftime("%Y/%m/%d %H:%M:%S") if self.tracker.last_ts else "",
            "afk": self.tracker.afk,
            "confirmed": self.tracker.confirmed,
            "pending": [[p.code, p.level, p.ts] for p in self.tracker.pending],
            "pending_scene": self.tracker.provisional.area_name if self.tracker.provisional else "",
            "pending_mode": self.tracker.provisional.mode if self.tracker.provisional else "",
            # 추정 상태의 캐릭터(모드 지정·퀘스트 패시브 등 확정 전 변경 포함)를 통째로 저장
            "provisional": self.tracker.provisional.to_dict() if self.tracker.provisional else None,
            "pending_play": self.tracker._pending_play,
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

    def set_opacity(self, value: float) -> None:
        value = round(max(OPACITY_STEPS[-1], min(1.0, value)), 2)
        self.overlay.setWindowOpacity(value)
        self.settings["window_opacity"] = value
        config.save_settings(self.settings)

    def change_opacity(self, delta: float) -> None:
        self.set_opacity(float(self.settings.get("window_opacity", 1.0)) + delta)

    def toggle_auto_copy(self) -> None:
        self.settings["auto_copy_regex"] = not self.settings.get("auto_copy_regex", True)
        config.save_settings(self.settings)

    def toggle_pb(self) -> None:
        self.settings["show_pb"] = not self.settings.get("show_pb", False)
        config.save_settings(self.settings)
        self.refresh()

    def toggle_rewards(self) -> None:
        self.overlay.show_rewards = not self.overlay.show_rewards
        self.refresh()

    def toggle_visible(self) -> None:
        self.user_hidden = self.overlay.isVisible()
        self.overlay.setVisible(not self.user_hidden)

    def toggle_auto_hide(self) -> None:
        self.settings["auto_hide"] = not self.settings.get("auto_hide", True)
        config.save_settings(self.settings)
        if not self.settings["auto_hide"] and not self.user_hidden:
            self.overlay.show()
        self.flash = "자동 숨김 켜짐" if self.settings["auto_hide"] else "자동 숨김 꺼짐 (항상 표시)"
        QTimer.singleShot(3000, self._clear_flash)
        self.refresh()

    def on_tray(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_visible()

    def on_moved(self, x: int, y: int) -> None:
        self.auto_pos = False  # 직접 옮긴 위치를 우선
        self.settings["window"].update(x=x, y=y)
        config.save_settings(self.settings)

    def select_character(self, name: Optional[str]) -> None:
        self.tracker.select_character(name)
        self.dirty = True
        self.refresh()

    def choose_new_char_mode(self, mode: str) -> None:
        c = self.tracker.snapshot().character
        if c is None:
            return
        c.mode_prompt = False
        if mode:
            c.mode = mode
        self.dirty = True
        self.save()
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
            self.tracker = Tracker(self.guide, encounters=self.encounters)
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

        bm = m.addMenu("빌드 (젬 안내)")
        cur_c = self.tracker.snapshot().character
        cur_f = self.settings.get("char_builds", {}).get(cur_c.name) if cur_c else None
        bgrp = QActionGroup(bm)
        auto_b = QAction("게임에 연결된 빌드 따라가기", bm, checkable=True)
        auto_b.setChecked(not cur_f)
        auto_b.triggered.connect(lambda: self.set_char_build(None))
        bgrp.addAction(auto_b)
        bm.addAction(auto_b)
        bm.addSeparator()
        for fam, files in families(self.build_files).items():
            a = QAction(f"{files[0].label}  ({len(files)}개 구간)", bm, checkable=True)
            a.setChecked(fam == cur_f)
            a.triggered.connect(lambda _=False, f=fam: self.set_char_build(f))
            bgrp.addAction(a)
            bm.addAction(a)

        cur_op = float(self.settings.get("window_opacity", 1.0))
        om = m.addMenu(f"투명도: {round(cur_op * 100)}%  ({HOTKEYS['opacity_up']} / Down)")
        ogrp = QActionGroup(om)
        for v in OPACITY_STEPS:
            a = QAction(f"{round(v * 100)}%", om, checkable=True)
            a.setChecked(abs(v - cur_op) < 0.01)
            a.triggered.connect(lambda _=False, val=v: self.set_opacity(val))
            ogrp.addAction(a)
            om.addAction(a)

        for key, text in (("boss_compact", "보스전 간단 모드 (한 줄)"), ("tab_hint", "보스전 시작 시 Tab → 미니맵 안내")):
            act = QAction(text, m, checkable=True)
            act.setChecked(self.settings.get(key, True))
            act.triggered.connect(lambda _=False, k=key: self.toggle_setting(k))
            m.addAction(act)
        rx = QAction("상인 대화 시 정규식 자동 복사", m, checkable=True)
        rx.setChecked(self.settings.get("auto_copy_regex", True))
        rx.triggered.connect(self.toggle_auto_copy)
        m.addAction(rx)
        pb = QAction("PB 비교 표시 (연습용)", m, checkable=True)
        pb.setChecked(self.settings.get("show_pb", False))
        pb.triggered.connect(self.toggle_pb)
        m.addAction(pb)

        ct = QAction(f"클릭 통과  ({HOTKEYS['click_through']})", m, checkable=True)
        ct.setChecked(self.overlay.click_through)
        ct.triggered.connect(self.toggle_click_through)
        m.addAction(ct)
        m.addAction(f"숨기기/보이기  ({HOTKEYS['toggle']})", self.toggle_visible)
        ah = QAction(f"게임 창이 아닐 때 자동 숨김  ({HOTKEYS['auto_hide']})", m, checkable=True)
        ah.setChecked(self.settings.get("auto_hide", True))
        ah.triggered.connect(self.toggle_auto_hide)
        m.addAction(ah)
        m.addAction(f"영구 보상 전체 목록  ({HOTKEYS['rewards']})", self.toggle_rewards)
        m.addAction(f"젬 카드  ({HOTKEYS['gems']})", self.toggle_gem_card)
        m.addSeparator()
        m.addAction("위치 초기화 (왼쪽 위 기본 위치)", self.reset_position)
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
