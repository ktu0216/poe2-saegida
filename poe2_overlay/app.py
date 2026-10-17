"""앱 진입점: 로그 감시 → 트래커 → 오버레이."""
from __future__ import annotations

import html
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QProcess, QTimer
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox, QSystemTrayIcon

from . import __version__, config, endgame, export, i18n, progress_code, updater
from .i18n import t
from .guide import Guide, is_town
from .logparse import parse_line
from .logtail import LogTail, iter_lines
from .regex import RegexBook
from .builds import (GemNames, families, family_for_class, family_of, parse_uncut, pick_stage, plan, scan,
                     uncut_advice)
from .encounters import Encounters
from .items import (MAIN, OFF, build_profile, compare, defense_score, equip_key, hand_keys, hand_plan, is_gear, is_item_text,
                    normalize_gear, parse_item, slot_keys, slot_label)
from .rewards import RewardTable, load_passive_sources
from .tracker import MAX_GAP, Character, PLACEHOLDERS, Snapshot, Tracker, fight_quiet, parse_ts
from .ui import Overlay, make_icon
from .timing import ENDGAME, personal_bests, timer_view

RESTARTED = "--restarted"  # 오버레이가 스스로 다시 켠 경우 (언어 변경 등)
from .trade import (RateLimited, TradeClient, TradeData, bait, build_query, ex_text, price_text, summary,
                    trade_league)
from .watchdog import timed
from .winutil import HotkeyManager, foreground_pid, game_pids, game_window_rect, set_click_through

KOFI_URL = "https://ko-fi.com/saegida"  # 후원 (모든 기능 무료, 메뉴 맨 아래 한 줄만)
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
    "expand": "Ctrl+Alt+X",
}
OPACITY_STEPS = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3)
TOP_RATIO = 0.08  # 기본 위치: 게임 창 왼쪽, 위에서 8% (왼쪽 위 버프·스킬 아이콘 아래)
DOUBLE_COPY_SEC = 0.8  # 이보다 느린 재복사는 '다시 비교'로 본다
# 시세: Ctrl+C 뒤 이 시간 안에 시세 키 (게임은 다른 프로그램이 키를 엿보거나 대신 누르는 것을 막아서,
# 복사 직후에만 RegisterHotKey 로 잠깐 잡는다 — 평소에는 게임·다른 프로그램이 그 키를 그대로 쓴다)
# Ctrl 을 누른 채 C → V 로 굴린다. D 는 이동(WASD), X 는 무기 교체라 손이 헷갈림 (2026-10-17 플레이 시험).
# Ctrl+V 는 채팅·검색창 붙여넣기에만 쓰이고, 복사 직후 잠깐만 잡으니 정규식 붙여넣기와 거의 겹치지 않는다.
PRICE_KEYS = ("Ctrl+V", "Ctrl+B", "Ctrl+G")  # 다른 프로그램이 쓰면 다음 후보, settings.json "price_key" 로 바꿈
PRICE_WINDOW_SEC = 2.0  # 5초는 길었음 (settings.json "price_window_sec")
def _slot_title(item, title: str) -> str:
    """비교 카드 제목: 부위 + 제목. 제목에 부위 이름이 이미 있으면("도마뱀비늘 장화") 한 번만 ("장화 장화" 방지)."""
    slot = t(item.slot)
    return title if slot in title else f"{slot} {title}"


_NUM_RE = re.compile(r"\d+(?:\.\d+)?")  # 시세 카드: 옵션 문구 안의 숫자 자리
PROGRESS_VERSION = 23  # 23: 마을에서 쓴 책은 직전 사냥터 보상, 22: 22: 퀘스트 패시브를 주는 단계에 받음 표시, 21: 21: 퀘스트 패시브 받은 단계 표시, 20: 보스전 중 보상 획득은 처치, 19: 19: 건너뛴 지역에서 돌아오면 되돌리기, 18: 전직 단계, 2: 플레이 시간/액트 스플릿, 3: 되돌아간 지역 건너뛰기 수정, 4: 같은 이름 새 캐릭터 분리, 5: 보스 처치 전 마을 방문은 단계 유지, 6: NPC 단계 이름 보스 목록에서 제외, 7: 하위 지역 보스, 8: 재접속 시 직전 캐릭터 우선 추정 (이전 저장본은 로그 전체를 다시 읽는다)


class Controller:
    def __init__(self, app: QApplication):
        self.app = app
        self.settings = config.load_settings()
        self.log_path: Optional[Path] = config.find_log(self.settings.get("log_path", ""))
        # 화면 언어: 설정(auto/ko/en). auto 는 로그 파일로 (Client.txt = 영어 클라이언트, KakaoClient.txt = 한국어)
        self.lang = i18n.resolve(self.settings.get("language", "auto"), self.log_path)
        # 게임(로그) 언어: 로그와 맞춰 보는 데이터(보상 문구, 보스 대사, 상인 정규식)는 화면 언어가 아니라 이것을 따른다
        self.log_lang = i18n.resolve("auto", self.log_path)
        i18n.set_lang(self.lang)
        self.guide_file: Optional[Path] = config.find_guide(self.settings.get("guide_path", ""), self.lang,
                                                                  self.settings.get("guide_kind", "default"))
        self.guide = Guide.load(self.guide_file)
        self._guide_mtime = self._mtime(self.guide_file)
        self.rewards = RewardTable.load(config.data_file("rewards", self.lang),
                                        *(config.data_file("rewards", lg) for lg in ("ko", "en")))
        self.passive_sources = load_passive_sources(config.data_file("quest_passives", self.lang))
        rx = config.data_file("regex", self.log_lang)
        # 상인 정규식은 게임 언어의 아이템 문구라야 한다: 그 언어 데이터가 없으면 끈다
        self.regex_book = RegexBook.load(rx) if rx.stem.endswith(self.log_lang) else RegexBook([], set())
        self.active_builds: dict[str, str] = {}
        self.gem_names = GemNames.load(None, config.resource_dir() / "guides" / "gem_names_ko.json",
                                       config.resource_dir() / "guides" / "gem_names_trade.json",
                                       config.resource_dir() / "guides" / "gem_ids_pob.json")
        self.gem_names.english = self.lang == "en"
        self.build_files = scan(config.build_planner_dir() or Path())
        self._builds_sig = self._build_dir_sig()
        self._last_level: dict[str, int] = {}
        self.current_regex = None
        self._regex_copied_at = 0.0
        self.flash = ""  # 잠깐 보여줄 알림 (정규식 복사됨 등)
        self._restarting = False
        self.encounters = Encounters.load(config.data_file("encounters", self.log_lang))
        if self.lang != self.log_lang:  # 보스 이름표만 화면 언어로
            self.encounters.display = Encounters.load(config.data_file("encounters", self.lang))
        self.endgame_bosses = endgame.EndgameBosses.load(config.data_file("endgame_bosses", self.log_lang))
        if self.lang != self.log_lang:  # 처치 대사는 로그 언어, 이름표는 화면 언어
            shown = endgame.EndgameBosses.load(config.data_file("endgame_bosses", self.lang))
            for code, b in self.endgame_bosses.bosses.items():
                if (s := shown.get(code)) is not None:
                    self.endgame_bosses.bosses[code] = endgame.Boss(b.key, s.label, b.kill)
        self.tracker = Tracker(self.guide, encounters=self.encounters)
        self.tracker.endgame = self.endgame_bosses
        self.tracker.passive_sources = self.passive_sources
        self.tail: Optional[LogTail] = None
        self.dirty = False
        self.notice = ""
        self.game_cfg = config.find_game_config()
        self._cfg_mtime = None
        self._ticks = 0
        self.user_hidden = False  # Ctrl+Alt+H 로 직접 숨긴 상태
        self.game_running = bool(game_pids())  # 게임이 꺼져 있으면 지난 캐릭터 대신 실행 대기 화면
        self._pbs: dict[str, float] = {}
        self._pbs_for: Optional[str] = None

        self.overlay = Overlay(self.settings)
        self.overlay.menu_builder = self.build_menu
        self.overlay.passive_sources = self.passive_sources
        self.zone_tips = config.load_zone_tips(config.data_file("zone_tips", self.lang))
        self.overlay.moved.connect(self.on_moved)
        self.overlay.mode_chosen.connect(self.choose_new_char_mode)
        self.overlay.action.connect(self.on_tool)

        self.tray = QSystemTrayIcon(make_icon())
        self.tray.setToolTip(t("POE2 새기다"))
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
        for key in (HOTKEYS["expand"], "Ctrl+Alt+F8"):  # 다른 프로그램이 쓰면 다음 후보
            if self.hotkeys.register(key, self.expand_compact):
                HOTKEYS["expand"] = key
                break
        for key in (HOTKEYS["gems"], "Ctrl+Alt+J", "Ctrl+Alt+F11"):  # 다른 프로그램이 쓰면 다음 후보
            if self.hotkeys.register(key, self.toggle_gem_card):
                HOTKEYS["gems"] = key
                break
        self.show_gem_card = False
        # 게임에서 아이템에 Ctrl+C → 클립보드 감시로 장착 아이템과 비교
        self.item_msg = ""
        self.item_color = "#e8b04a"
        self.last_item_text = ""
        self._equip_undo: tuple[str, str] = ("", "")  # 반지 칸 옮기기: (방금 등록한 칸, 그 칸에 있던 아이템)
        self.compare_target = ""  # 마지막으로 비교한 장착 칸 (Ctrl+Alt+E 가 바꿀 칸)
        self.prev_copied: dict[str, str] = {}  # 부위 -> 직전에 복사한 아이템 (장착 기준이 없을 때 비교용)
        self._last_copy_at = 0.0
        self._tab_until = 0.0
        self._expanded_at: tuple[str, str] = ("", "")  # 보스전 한 줄을 펼친 (캐릭터, 지역): 그 지역에서는 다시 줄이지 않는다
        self._item_clear = QTimer()
        self._item_clear.setSingleShot(True)
        self._item_clear.timeout.connect(self._clear_item)
        self._price_text = ""  # 시세 키를 누르면 검색할 아이템 (마지막 복사)
        self._price_hid = 0  # 잠깐 등록한 시세 키 id (0 = 꺼짐)
        self._price_key = ""
        self._price_timer = QTimer()
        self._price_timer.setSingleShot(True)
        self._price_timer.timeout.connect(self._disarm_price)
        # 거래소: 카카오 클라이언트면 카카오 거래소, 아니면 국제 거래소
        self.realm = "kakao" if self.log_path and "kakao" in self.log_path.name.lower() else "ggg"
        self.trade_data: dict[tuple[str, str], TradeData] = {}  # (거래소, 아이템 문구 언어)
        self._price_query = self._price_res = self._price_data = None  # 마지막 시세 (조건 바꿔 다시 찾기·다시 보기)
        self._price_league, self._price_lang = "", "ko"
        self._price_ssf, self._price_mode = False, ""
        self._price_dirty = False  # 카드에서 조건을 바꿨지만 아직 다시 찾지 않음
        self.trade_clients: dict[str, TradeClient] = {}
        self.price_msg, self.price_color = "", "#e0b862"
        self.price_tools: tuple = ()  # 시세 카드 머리글 오른쪽 아이콘 (↗ 거래소, ✕ 닫기)
        self.price_head = ""  # 시세 카드 머리글 (💰 시세 · 리그)
        self._price_busy = False
        self._price_result = None  # 작업 스레드 → tick 에서 화면에
        self._price_clear = QTimer()
        self._price_clear.setSingleShot(True)
        self._price_clear.timeout.connect(self._clear_price)
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
            self.notice = t("단축키 등록 실패: ") + ", ".join(self.hotkeys.failed)

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

        # 캠페인 완주 카드: 이번 실행 중에 캠페인을 끝낸 캐릭터만 자동으로 (예전 완주는 메뉴에서)
        self._finished_at_start = {n for n, ch in self.tracker.chars.items() if ENDGAME in ch.splits}
        self._cards_made: set[str] = set()

        # 새 버전 확인: 시작 조금 뒤 한 번, 그 뒤 6시간마다 (설정에서 끌 수 있음)
        self.update: Optional[updater.Release] = None
        self._update_result: Optional[tuple] = None  # 백그라운드 작업 결과 (종류, 값, 수동 여부)
        self._update_busy = False
        self._update_msg = ""  # 수동 확인 결과 (대기 화면에도 보이도록 알림 줄에 잠깐)
        self._update_msg_until = 0.0
        QTimer.singleShot(8000, self.start_update_check)
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.start_update_check)
        self.update_timer.start(6 * 60 * 60 * 1000)

        self.overlay.setWindowOpacity(float(self.settings.get("window_opacity", 1.0)))
        self.overlay.show()
        set_click_through(int(self.overlay.winId()), False)  # 클릭해도 게임 포커스를 뺏지 않게
        set_click_through(int(self.overlay.toast.winId()), True)  # 알림 창은 보기만: 시세 카드가 있을 때만 클릭
        self.overlay.toast.link.connect(self.on_price_link)
        # 저장된 위치가 없으면 게임 창 왼쪽 위(버프·스킬 아이콘 아래)에 붙인다. 게임 창을 찾을 때까지 tick 에서 재시도.
        self.auto_pos = self.settings["window"].get("x") is None
        self._auto_placed = False
        if self.auto_pos:
            self.place_default()
        if self.settings.get("click_through"):
            self.toggle_click_through()
        self.refresh()
        if RESTARTED not in sys.argv:  # 켜기 전에 복사해 둔 아이템도 처리 (언어 변경 등 스스로 재시작할 때는 같은 아이템이 또 뜨지 않게)
            QTimer.singleShot(500, self.on_clipboard)
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
            self.notice = t("로그 파일을 찾지 못했습니다. 메뉴 → 로그 파일 선택")
            return
        size = self.log_path.stat().st_size
        saved = config.load_progress()
        start = 0
        old_chars = saved.get("characters", {})
        migrate = saved.get("version", 1) < PROGRESS_VERSION
        if not migrate and saved.get("log_path") == str(self.log_path) and 0 <= saved.get("offset", -1) <= size:
            chars = {k: Character.from_dict(v) for k, v in saved.get("characters", {}).items()}
            for ch in chars.values():  # 예전 저장본: 젬·화폐·퀘스트 아이템 칸 정리, 무기는 주 손 / 보조 손으로, 부위 키는 언어 무관하게
                ch.gear = normalize_gear({k: v for k, v in ch.gear.items() if "젬" not in k})
            self.tracker = Tracker(self.guide, chars, saved.get("current"), self.encounters)
            self.tracker.endgame = self.endgame_bosses
            self.tracker.passive_sources = self.passive_sources
            self.tracker.pid = saved.get("pid")
            self.tracker.last_ts = parse_ts(saved.get("last_ts") or "")
            self.tracker.afk = bool(saved.get("afk"))
            self.tracker.relog = bool(saved.get("relog"))  # 재시작해도 "같은 게임에서 재접속" 추정을 이어 간다
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
                    c.gear = normalize_gear(old.get("gear") or c.gear)  # Ctrl+C 로 지정한 장착 기준도 로그로는 되살릴 수 없다
        if not saved.get("eg_backfill"):  # 엔드게임 기록 기능 이전 캐릭터: 전체 로그로 한 번 채운다 (몇 초)
            self._backfill_endgame(size)
        self.tail = LogTail(self.log_path, size)
        self.dirty = True
        self._pbs_for = None
        # 과거 로그 재생이 끝난 뒤에만 현재 리그를 적용 (옛 캐릭터에 현재 리그가 찍히지 않도록)
        self._cfg_mtime = None
        self.check_league()

    def _backfill_endgame(self, size: int) -> None:
        tmp = Tracker(self.guide, encounters=self.encounters)
        tmp.endgame = self.endgame_bosses
        for ln in iter_lines(self.log_path, 0, size):
            if ev := parse_line(ln):
                tmp.feed(ev)
        for name, src in tmp.chars.items():
            if (c := self.tracker.chars.get(name)) and not c.eg_maps and not c.eg_bosses:
                c.eg_maps, c.eg_bosses, c.eg_cur, c.eg_since = src.eg_maps, src.eg_bosses, src.eg_cur, src.eg_since
            if (p := self.tracker.provisional) and p.name == name and not p.eg_maps:  # 확정 전 추정 캐릭터
                p.eg_maps, p.eg_bosses, p.eg_cur, p.eg_since = src.eg_maps, src.eg_bosses, src.eg_cur, src.eg_since

    @staticmethod
    def _build_dir_sig() -> tuple:
        """빌드 플래너 폴더의 .build 파일 이름·수정 시각 (추가·삭제·이름 변경·수정 감지용)."""
        folder = config.build_planner_dir()
        try:
            return tuple(sorted((f.name, f.stat().st_mtime) for f in folder.glob("*.build"))) if folder else ()
        except OSError:
            return ()

    @staticmethod
    def _mtime(path: Optional[Path]) -> Optional[float]:
        try:
            return path.stat().st_mtime if path else None
        except OSError:
            return None

    def reload_guide_if_changed(self) -> bool:
        """가이드 CSV 를 고치면(문구 수정 등) 재시작 없이 다시 읽는다."""
        mtime = self._mtime(self.guide_file)
        if mtime is None or mtime == self._guide_mtime:
            return False
        self._guide_mtime = mtime
        try:
            guide = Guide.load(self.guide_file)
        except (OSError, ValueError):
            return False  # 저장 도중이면 다음 확인 때
        if not guide.steps:
            return False
        self.guide = guide
        self.tracker.set_guide(guide)
        self.dirty = True
        return True

    def rescan_builds(self, force: bool = False) -> bool:
        sig = self._build_dir_sig()
        if not force and sig == self._builds_sig:
            return False
        self._builds_sig = sig
        self.build_files = scan(config.build_planner_dir() or Path())
        return True

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
        self.rescan_builds(force=True)  # 빌드를 새로 받았을 수 있다
        league = config.read_league(cfg)
        if league == self.tracker.league:
            return True
        # 캐릭터에는 지역에 들어갈 때 적용한다. 여기서 바로 넣으면 캐릭터 선택 화면에서 다른 리그를 고를 때
        # 방금까지 하던 캐릭터에 그 리그가 찍힌다 (일반 캐릭터에 HC 리그)
        self.tracker.league = league
        self.dirty = True
        return True

    @timed("poll")
    def poll(self) -> None:
        if not self.tail:
            return
        self._ticks += 1
        changed = self._ticks % 7 == 0 and self.check_league()
        if self.tracker.scene_lang and self.tracker.scene_lang != self.log_lang and not self._restarting:
            # 게임 언어를 바꿨다 (카카오판도 영어 가능): 로그와 맞춰 보는 데이터·화면 언어(자동)를 다시 정한다
            self._restarting = True
            self.restart()
            return
        if self._ticks % 7 == 3 and self.rescan_builds():  # 빌드 파일을 넣거나 지운 경우
            changed = True
        if self._ticks % 7 == 5 and self.reload_guide_if_changed():
            changed = True
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

    @timed("refresh")
    def refresh(self) -> None:
        snap = self.tracker.snapshot(int(self.settings.get("upcoming", 3)))
        if not self.game_running:  # 게임을 켜기 전: 지난 캐릭터 정보 대신 대기 화면
            self.overlay.show_mode_prompt(False)
            self.overlay.leave_compact()
            self.overlay.waiting = True
            self.overlay.render(Snapshot(None, False, None, [], None, False, snap.total), self._notice_text(), [])
            return
        self.overlay.waiting = False
        c = snap.character
        states = self.rewards.evaluate(c.rewards) if c else []
        for i in (c.assumed_slots if c else []):  # '이전 보상 채우기'로 받았다고 표시한 칸
            if i < len(states) and not states[i].got:
                states[i].got = [t("이전 기록")]
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
        self.overlay.zone_tips = self.zone_tips if self.settings.get("zone_tips", True) else {}
        if (c and snap.confirmed and ENDGAME in c.splits and timer is not None
                and c.name not in self._finished_at_start and c.name not in self._cards_made):
            self._cards_made.add(c.name)
            try:
                pbs = personal_bests(self.tracker.chars.values(), exclude=c.name)
                path = export.save_card(c, timer_view(c, pbs, 0.0), snap.league)
                self.flash = t("🏁 캠페인 완주! 완주 카드 저장: {p}", p=path.name)
            except OSError:
                pass
        eg = None
        if c and ENDGAME in c.splits and snap.step and snap.step.index == snap.total - 1:
            eg = endgame.summary(c, self.tracker.endgame, datetime.now())
            if eg is None:
                eg = endgame.Summary(0, 0.0, 0, 0, "", 0.0, [])
        self.overlay.render(snap, self._notice_text(), states, self.rewards.quest_passive_total, timer,
                            rule if in_town else None, HOTKEYS["copy_regex"], self.flash, self.item_msg + self.price_hint(),
                            gems, self.gem_names, self.show_gem_card, self.item_color, endgame=eg,
                            price_msg=self.price_msg, price_color=self.price_color, price_tools=self.price_tools,
                            price_head=self.price_head)

    # ---------------------------------------------------------- 보스전 간단 모드
    def _boss_compact(self, snap) -> bool:
        """곧 보스/보스 전투 중이면 패널을 한 줄로. 처리했으면 True."""
        c, f = snap.character, snap.flags
        here = snap.in_step_zone
        boss_name = snap.boss
        if not here and snap.roam_flags:  # 가이드 단계 밖의 보스 지역 (지난 액트 보스 다시 잡기 등)
            f, here, boss_name = snap.roam_flags, True, snap.roam_boss
        subs = {k: v for k, v in f.get("sub", {}).items() if v == "engaged"}
        boss_state = f.get("boss")
        fighting = bool(subs) or boss_state == "engaged"
        if fighting and fight_quiet(f, datetime.now()):
            # 처치 대사가 없는 보스: 한참 조용하면 끝난 것으로 보고 일반 패널 (다음 단계 보이게)
            subs, fighting, boss_state = {}, False, "quiet"
        soon = bool(f.get("soon")) and boss_state not in ("engaged", "killed", "died", "quiet")
        on = (self.settings.get("boss_compact", True) and c is not None and here
              and (fighting or soon) and self._expanded_at != (c.name, c.zone))
        if not on:
            if self.overlay.compact:
                self.overlay.leave_compact()
            return False
        if not self.overlay.compact:  # 막 시작됨 → Tab 안내
            self._tab_until = time.monotonic() + 3 if self.settings.get("tab_hint", True) else 0
        name = html.escape(next(iter(subs)) if subs else (boss_name or t("보스")))
        head = (f'<span style="color:#ff8a65">{t("⚔ {name} 전투 중", name=name)}</span>' if fighting
                else f'<span style="color:#e8b04a">{t("⚠ 곧 {name}", name=name)}</span>')
        gap = c.area_level - c.level if c.area_level else 0
        lv = f'<span style="color:{"#ff8a65" if gap >= 3 else "#9a9284"}">{t(" · Lv {lv} · 지역 {area}", lv=c.level, area=c.area_level)}</span>'
        tab = (' <b style="color:#e8b04a">' + t("· Tab→미니맵") + '</b>' if time.monotonic() < self._tab_until else "")
        tab += f' <span style="color:#6f685c">{t("· 클릭: 펼치기 ({key})", key=HOTKEYS["expand"])}</span>'
        self.overlay.render_compact(head + lv + tab)
        return True

    def toggle_gem_card(self) -> None:
        self.show_gem_card = not self.show_gem_card
        self.refresh()

    # ---------------------------------------------------------- PC 옮기기
    def copy_progress_code(self) -> None:
        c = self.tracker.snapshot().character
        if c is None or c.name in PLACEHOLDERS:
            return
        code = progress_code.encode(c, self.settings.get("char_builds", {}).get(c.name, ""))
        QApplication.clipboard().setText(code)
        self.flash = t("진행 코드 복사됨 ({n}자) — 카톡 나에게 보내기 등에 붙여 두세요", n=len(code))
        QTimer.singleShot(8000, self._clear_flash)
        self.refresh()

    def paste_progress_code(self) -> None:
        try:
            imp, build = progress_code.decode(QApplication.clipboard().text())
        except ValueError:
            self.flash = t("클립보드에 진행 코드가 없습니다 — 코드 전체를 복사한 뒤 다시")
            QTimer.singleShot(6000, self._clear_flash)
            self.refresh()
            return
        local = self.tracker.chars.get(imp.name)
        if local is not None and not local.partial_from and local.last_seen > imp.last_seen:
            ask = t("{name}: 이 PC 의 기록(Lv {a}, {at})이 코드(Lv {b}, {bt})보다 최근입니다. 코드로 바꿀까요? 이 PC 기록은 '(이전)' 이름으로 남겨 둡니다.",
                    name=imp.name, a=local.level, at=local.last_seen[:16], b=imp.level, bt=imp.last_seen[:16])
            if QMessageBox.question(None, "POE2 Saegida", ask) != QMessageBox.StandardButton.Yes:
                return
        if local is not None and not local.partial_from:  # 온전한 기록은 버리지 않고 이름을 바꿔 보관
            archived = f"{local.name} (이전 {local.last_seen[:10]})"
            local.name = archived
            self.tracker.chars[archived] = local
            local = None
        c = progress_code.merge(imp, local)
        self.tracker.chars[c.name] = c
        if build:
            self.settings.setdefault("char_builds", {})[c.name] = build
            config.save_settings(self.settings)
        self._pbs_for = None
        self.dirty = True
        self.flash = t("✓ {name} 진행을 가져왔습니다 (Lv {lv}, {step}단계)", name=c.name, lv=c.level, step=c.cursor + 1)
        QTimer.singleShot(8000, self._clear_flash)
        self.refresh()

    def fill_previous_rewards(self) -> None:
        c = self.tracker.snapshot().character
        if c is None or c.name in PLACEHOLDERS:
            return
        states = self.rewards.evaluate(c.rewards)
        done = frozenset(i for i, st in enumerate(states) if st.got)
        n, pts = progress_code.fill_previous(c, self.guide.steps, self.rewards.slots, self.passive_sources, done)
        self.dirty = True
        self.flash = t("지나온 단계: 영구 보상 {n}칸 · 퀘스트 패시브 +{p} 받음으로 표시", n=n, p=pts)
        QTimer.singleShot(8000, self._clear_flash)
        self.refresh()

    def dismiss_partial(self) -> None:
        c = self.tracker.snapshot().character
        if c is not None:
            c.partial_ack = True
            self.dirty = True
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
        if name:
            return family_of(self.build_files, name)
        # 게임은 빌드 연결을 로그아웃할 때만 저장한다 → 그 전에는 직업이 맞는 빌드가 하나뿐이면 그것으로
        return family_for_class(self.build_files, c.cls)

    def gem_plan(self, c, act: str):
        if c is None or c.name in PLACEHOLDERS:
            return None
        fam = self.build_family(c)
        files = families(self.build_files).get(fam) if fam else None
        stage = pick_stage(files, act, c.level, ascended=c.ascension >= 1) if files else None
        return plan(stage, c.level) if stage else None

    def _notify_level_up(self, c, gems) -> None:
        if c is None or gems is None:
            return
        prev = self._last_level.get(c.name)
        self._last_level[c.name] = c.level
        if prev is not None and c.level > prev and gems.unlocked_at:
            names = " · ".join(self.gem_names(g.id) for g in gems.unlocked_at)
            self.flash = t("💎 Lv {lv} — {names} 장착 가능", lv=c.level, names=names)
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
        QApplication.clipboard().setText(rule.search_text)
        self.flash = t("📋 {name} 정규식 복사됨 — 검색창에 Ctrl+V", name=rule.name)
        QTimer.singleShot(4000, self._clear_flash)
        self.refresh()

    @timed("on_clipboard")
    def on_clipboard(self) -> None:
        # 게임 창에서 복사했을 때만 읽는다. 다른 프로그램의 복사까지 읽으면 그 프로그램이 클립보드 응답을
        # 늦게 줄 때 오버레이가 같이 멈춘다(응답 없음으로 닫힘, 2026-09-30·10-01).
        if foreground_pid() not in game_pids():
            return
        text = self.app.clipboard().text()
        if not is_item_text(text):
            return
        self._arm_price(text)
        now = time.monotonic()
        if text == self.last_item_text:
            gap = now - self._last_copy_at
            if gap < 0.25:  # 복사 한 번에 알림이 여러 번 오는 경우
                return
            self._last_copy_at = now
            if gap <= DOUBLE_COPY_SEC:  # 같은 아이템을 연달아 두 번 (더블클릭처럼) = 장착 기준 등록
                self.set_equipped(via=t("두 번 복사"))
                self._last_copy_at = 0.0  # 다음 등록(칸 옮기기)도 다시 두 번 복사로
            return
        self._last_copy_at = now
        if uncut := parse_uncut(text):  # 미가공 젬: 빌드 기준으로 만들 젬 안내
            self.last_item_text = text
            self._show_uncut(*uncut)
            return
        item = parse_item(text)
        c = self.tracker.snapshot().character
        if item is None or c is None or not is_gear(item):  # 젬·화폐는 장비 비교 대상이 아니다
            return
        self.last_item_text = text
        if item.hand:  # 무기·방패·집중구: 주 손 / 보조 손 두 칸
            keys = hand_keys(item, c.gear)
            filled, notes = hand_plan(item, c.gear)
            check = [MAIN, OFF]
        else:
            keys = slot_keys(item.slot)  # 반지는 두 칸
            filled = sorted((k for k in keys if k in c.gear),
                            key=lambda k: defense_score(parse_item(c.gear[k]), build_profile(c.gear)))
            notes, check = [], keys
        label = lambda k: t(slot_label(k, keys))
        note_html = "".join(f'<br><span style="color:#e0b862">⚠ {t(n, **kw)}</span>' for n, kw in notes)
        hint = f'<br><span style="color:#9a9284">' + t("기준 없음 · 장착 중이면 Ctrl+C 한 번 더 → 등록") + '</span>'
        if any(c.gear.get(k) == text for k in check):
            k = next(k for k in check if c.gear.get(k) == text)
            title, _, _ = compare(item, None, build_profile(c.gear))
            self._show_item(t("📌 장착 중 ({slot}) · {title}", slot=label(k), title=title), "#9a9284")
            return
        prev_text = self.prev_copied.get(item.slot)
        self.prev_copied[item.slot] = text
        if not filled and is_town(c.zone):  # 마을에서 복사한 건 대부분 상점/창고 아이템
            if prev_text and prev_text != text:  # 기준이 없으면 직전에 복사한 같은 부위 아이템과 비교
                title, diffs, verdict = compare(item, parse_item(prev_text), build_profile(c.gear))
                color = {1: "#8fd18b", -1: "#ff8a65"}.get(verdict, "#ece6da")
                mark = t({1: "▲ 더 좋음", -1: "▼ 더 나쁨"}.get(verdict, "≈ 비슷"))
                body = f'{mark} · {_slot_title(item, title)} {t("(직전 복사 대비)")}' + ("<br>" + " · ".join(diffs) if diffs else "")
                self._show_item(body + note_html + hint, color)
                return
            title, _, _ = compare(item, None, build_profile(c.gear))
            self._show_item(f'{_slot_title(item, title)}' + note_html + hint, "#ece6da")
            return
        key = equip_key(item, c.gear)
        if not is_town(c.zone) and key not in c.gear and not notes and (not filled or not item.hand):
            # 마을 밖: 빈 칸 = 지금 장착 중인 아이템으로 본다 (양손 무기를 든 채 주운 방패처럼 안내가 붙는 경우는 제외)
            c.gear[key] = text
            self.dirty = True
            title, _, _ = compare(item, None, build_profile(c.gear))
            self._show_item(t("📌 {slot} 장착 기준 저장 · {title}", slot=label(key), title=title), "#8fd18b")
            return
        if not filled:  # 비교할 기준이 없음 (예: 방패만 등록된 채 무기 복사)
            title, _, _ = compare(item, None, build_profile(c.gear))
            self._show_item(f'{_slot_title(item, title)}' + note_html + hint, "#ece6da")
            return
        # 비교 대상: 칸이 여러 개면 가장 약한 쪽 (바꾼다면 그걸 뺀다)
        target = filled[0]
        self.compare_target = target
        marks = {1: "▲ 더 좋음", -1: "▼ 더 나쁨"}
        title, diffs, verdict = compare(item, parse_item(c.gear[target]), build_profile(c.gear))
        color = {1: "#8fd18b", -1: "#ff8a65"}.get(verdict, "#ece6da")
        if len(filled) > 1:  # 반지·두 손 무기: 두 칸 모두와 비교해 보여 준다 (바꾼다면 약한 쪽 기준 판정)
            body = f'{_slot_title(item, title)}'
            for k in filled:
                _, d, v = compare(item, parse_item(c.gear[k]), build_profile(c.gear))
                body += (f'<br>{t(marks.get(v, "≈ 비슷"))} · {t("{slot} 대비", slot=label(k))}'
                         + (t(" (약한 쪽)") if k == target else "") + (" — " + " · ".join(d) if d else ""))
        else:
            body = (f'{t(marks.get(verdict, "≈ 비슷"))} · {_slot_title(item, title)}'
                    + (" " + t("({slot} 대비)", slot=label(target)) if len(keys) > 1 or item.hand else ""))
            if diffs:
                body += "<br>" + " · ".join(diffs)
        body += note_html
        body += f'<br><span style="color:#9a9284">' + t("장착했으면 Ctrl+C 한 번 더 → 기준 갱신") + '</span>'
        self._show_item(body, color)

    # ---------------------------------------------------------- 시세 키 (Ctrl+C 뒤 잠깐)
    def _arm_price(self, text: str) -> None:
        """아이템을 복사하면 PRICE_WINDOW_SEC 동안 시세 키를 잡는다. 다시 복사하면 대상·시간을 새로."""
        self._price_text = text
        if self.price_msg and not self._price_busy:
            self._clear_price()  # 다른 아이템을 복사하면 지난 시세 카드는 닫는다 (메뉴에서 다시 보기)
        if not self._price_hid:
            first = self.settings.get("price_key", "")
            for key in ((first,) if first else ()) + PRICE_KEYS:
                if hid := self.hotkeys.register_temp(key, self.price_check):
                    self._price_hid, self._price_key = hid, key
                    break
        if self._price_hid:
            self._price_timer.start(int(self._price_window() * 1000))

    def _price_window(self) -> float:
        try:
            return max(1.0, float(self.settings.get("price_window_sec", PRICE_WINDOW_SEC)))
        except (TypeError, ValueError):
            return PRICE_WINDOW_SEC

    def _disarm_price(self) -> None:
        self._price_timer.stop()
        if self._price_hid:
            self.hotkeys.unregister(self._price_hid)
            self._price_hid = 0
            self.refresh()

    def price_hint(self) -> str:
        """비교 결과 아래 붙는 안내 (시세 키가 잡혀 있는 동안만)."""
        if not self._price_hid or not self.item_msg:
            return ""
        return (f'<br><span style="color:#9a9284">'
                + t("💰 {key} → 시세 ({sec}초 안)", key=self._price_key, sec=f"{self._price_window():g}") + "</span>")

    def price_check(self) -> None:
        """마지막으로 복사한 아이템의 시세 (거래소 검색 1번 + 매물 10개). 네트워크는 작업 스레드에서."""
        text = self._price_text
        self._disarm_price()
        if not text or self._price_busy:
            return
        c = self.tracker.snapshot().character
        league = (c.league if c else "") or self.tracker.league
        if not league:
            self._show_price(t("리그를 알 수 없습니다 — 캐릭터 선택 화면에서 리그를 고른 뒤 다시"), "#ff8a65", 10)
            return
        level = c.level if c and c.level < 90 else 0  # 레벨링 중이면 지금 낄 수 있는 것만
        profile = build_profile(c.gear) if c else ""
        text_lang = "en" if text.lstrip().startswith("Item Class:") else "ko"
        league, self._price_ssf = trade_league(league)  # SSF 는 같은 일반/하드코어 리그 시세
        self._price_mode = c.mode if c else ""
        self._price_league = league
        self._price_search(league, text_lang, lambda data: build_query(text, data, level, profile))

    def _price_search(self, league: str, text_lang: str, make_query, keep_card: bool = False) -> None:
        """make_query(data) → Query 를 작업 스레드에서 검색. 조건을 바꿔 다시 찾을 때도 같은 길 (그때는 카드를 그대로 둔다)."""
        realm = self.realm
        self._price_busy = True
        self._price_lang = text_lang
        if keep_card:
            self._render_price()  # "다시 찾는 중…" 만 바뀐다
        else:
            self.price_head = ""
            self._show_price(t("💰 시세 찾는 중…"), "#9a9284")

        def work():
            try:
                key = (realm, text_lang)
                data = self.trade_data.get(key) or TradeData.load(config.APP_DIR / "trade", realm, text_lang)
                self.trade_data[key] = data
                q = make_query(data)
                if q.unsupported:
                    self._price_result = ("unsupported", q, None)
                    return
                client = self.trade_clients.setdefault(realm, TradeClient(realm))
                res = client.search(league, q)
                if not q.exchange:
                    client.add_rates(league, res)  # 엑잘 환산 (화폐 종류당 교환소 1번, 30분 캐시)
                self._price_result = ("ok", (q, data), res)
            except RateLimited as e:
                self._price_result = ("limited", None, e.wait)
            except Exception as e:  # 네트워크·거래소 오류: 화면에 짧게
                self._price_result = ("error", None, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _handle_price_result(self) -> None:
        if self._price_result is None:
            return
        kind, qd, value = self._price_result
        self._price_result = None
        self._price_busy = False
        esc = html.escape
        if kind == "limited":
            self._show_price(t("거래소 요청 제한 — {sec}초 뒤 다시", sec=int(value) + 1), "#ff8a65", 10)
            return
        if kind == "error":
            self._show_price(t("거래소 연결 실패: {err}", err=esc(value)[:80]), "#ff8a65", 10)
            return
        if kind == "unsupported":
            self._show_price(t(qd.unsupported), "#9a9284", 6)
            return
        q, data = qd
        self._price_query, self._price_data = q, data
        self._price_res = value
        self._price_dirty = False
        self._render_price()

    def _render_price(self) -> None:
        """시세 카드. 머리글: 💰 시세 · 리그 / 본문: 아이템 → 가격(크게) → 매물 수 → 조건 → 옵션 한 줄."""
        q, res, data = self._price_query, self._price_res, self._price_data
        esc = html.escape
        lang = "ko" if self.lang == "ko" else "en"
        dim = lambda s: f'<span style="color:#9a9284">{s}</span>'
        p = lambda a, c: esc(price_text(a, c, data, lang))
        exs = lambda v: esc(ex_text(v, lang))
        # 리그: 머리글 오른쪽에 작게 (아이템 이름·가격과 섞이지 않게)
        # 리그 · 모드 (메인 패널과 같은 색): "금단의 의식 · 하드코어", SSF 는 "· SSF → 거래 리그 시세"
        lg = self._price_league
        names = data.leagues if data else {}
        hc = lg.startswith("HC ") or lg == "Hardcore"
        league = names.get(lg[3:], lg[3:]) if lg.startswith("HC ") else names.get(lg, lg)
        mode = ("HC SSF" if hc else "SSF") if self._price_ssf else ("하드코어" if hc else "소프트코어")
        mcolor = {"하드코어": "#ff6b5b", "HC SSF": "#ff6b5b", "SSF": "#7fb8ff"}.get(mode, "#9a9284")
        tag = f'<span style="color:{mcolor}">{esc(t(mode))}</span>'
        if self._price_ssf:
            tag += f' <span style="color:#9a9284">{t("(거래 리그 시세)")}</span>'
        self.price_head = (f'{t("💰 시세")} <span style="color:#9a9284;font-weight:normal">· {esc(league)} · </span>'
                           f'<span style="font-weight:normal">{tag}</span>')
        title = f"<b>{esc(q.base or q.name)}</b>" + (f" {dim(esc(q.name))}" if q.rarity == "unique" else "")
        changed = (any(f.changed for f in q.filters) or q.status != "securable" or q.indexed != "1week")
        self.price_tools = ((("↺", "r:reset", t("조건 원래대로")),) if changed and not q.exchange else ()) + (
            (("↗", res.url, t("거래소에서 열기")),) if res.url else ()) + (("✕", "x:close", t("닫기")),)
        if q.exchange:  # 화폐·룬 …: 교환소 1개 가격
            if res.unit_ex is None:
                body = t("교환소에 엑잘로 사는 매물이 없습니다")
            else:
                body = (f'<big>{t("1개 ≈ {p}", p=f"<b style=\"color:#e8b04a\">{exs(res.unit_ex)}</b>")}</big>'
                        + "<br>" + dim(t("교환소 온라인 매물 {n}개", n=res.total)))
            self._show_price(f"{title}<br>{body}", "#e0b862", tools=self.price_tools)
            return
        # 조건 줄: 숫자는 굵게(휠로 바꾼 값은 노란색), "이상/이하" 는 뒤에 한 번
        chips, opts = [], []
        for i, f in enumerate(q.filters):
            if f.kind == "opt":  # 타락: 아래 옵션 줄로
                state = {"": t("상관없음"), "false": t("타락 아님"), "true": t("타락만")}[f.text]
                if f.text != f.orig_text:
                    state = f'<span style="color:#e8b04a">{state}</span>'
                opts.append(f'<a href="f:{i}" style="color:#ece6da;text-decoration:none">⇄ {t("타락")}: {state}</a>')
                continue
            box = "☑" if f.enabled else "☐"
            color = "#ece6da" if f.enabled else "#6f685c"
            if f.kind == "type":
                text = t("베이스 {name}", name=esc(f.label))
            elif f.value is None:
                text = esc(t(f.label))
            else:
                n = f"{f.value:g}"
                n = f'<b style="color:#e8b04a">{n}</b>' if f.value != f.orig else f"<b>{n}</b>"
                more = t("이상") if f.min is not None else t("이하")
                if f.avg:  # "번개 피해 1~18 추가" → 거래소는 평균으로 비교
                    text = f"{esc(f.label)} {dim(t('평균'))} {n}{f.unit} {more}"
                elif f.kind == "stat" and not f.key.startswith("pseudo.") and _NUM_RE.search(f.label):
                    # 옵션 한 줄: 문구 안의 숫자를 기준값으로 ("민첩 +25" → "민첩 +25 이상")
                    m = _NUM_RE.search(f.label)
                    text = esc(f.label[:m.start()]) + n + esc(f.label[m.end():]) + " " + more
                else:
                    text = f"{esc(t(f.label))} {n}{f.unit} {more}"
            chips.append((str(i), f'<a href="f:{i}" style="color:{color};text-decoration:none">{box} {text}</a>'))
        opts = [f'<a href="o:status" style="color:#ece6da;text-decoration:none">'
                f'{"☑" if q.status == "securable" else "☐"} {t("즉시 구매만")}</a>',
                f'<a href="o:indexed" style="color:#ece6da;text-decoration:none">'
                f'{"☑" if q.indexed else "☐"} {t("최근 1주일")}</a>'] + opts
        head = f'<hr>{dim(t("조건 · 누르면 켜고 끄기 · 휠로 수치"))}'
        bottom = " &nbsp; ".join(opts)
        if self._price_busy:
            bottom += "<br>" + dim(t("다시 찾는 중…"))
        elif self._price_dirty:  # 여러 개를 고른 뒤 한 번에 찾기 (위 가격은 바꾸기 전 조건)
            bottom += (f'<br><a href="s:go" style="color:#e8b04a">{t("🔍 이 조건으로 다시 검색")}</a>'
                       + " " + dim(t("(위 가격은 바꾸기 전 조건)")))
        rows = tuple(chips)
        if not res.listings:
            self._show_price((f"{title}<br>{t('비슷한 매물이 없습니다')}{head}", rows, bottom), "#9a9284",
                             tools=self.price_tools)
            return
        low, mid, _groups = summary(res)
        ex_part = lambda l: f" {dim('≈' + exs(l.ex))}" if l.ex is not None and l.currency != "exalted" else ""
        # 최저·중간을 한 줄씩 (한 줄에 넣으면 엑잘 환산이 다음 줄로 꺾인다)
        big = ("<big>" + t("최저 {p}", p=f'<b style="color:#e8b04a">{p(low.amount, low.currency)}</b>') + "</big>"
               + ex_part(low) + "<br><big>" + t("중간 {p}", p=f"<b>{p(mid.amount, mid.currency)}</b>") + "</big>"
               + ex_part(mid))
        if bait(res):
            big += f'<br><span style="color:#ff8a65">{t("⚠ 최저가가 유난히 쌉니다 (미끼일 수 있음)")}</span>'
        exs_known = [l.ex for l in res.listings if l.ex is not None]
        if len(exs_known) == len(res.listings):  # 싼 10개를 엑잘로 한 줄
            count = t("매물 {n}개 · 싼 {k}개 {lo}~{hi}", n=res.total, k=len(res.listings),
                      lo=ex_text(min(exs_known), lang).split(" ")[0], hi=exs(max(exs_known)))
        else:
            count = t("매물 {n}개", n=res.total)
        self._show_price((f"{title}<br>{big}<br>{dim(count)}{head}", rows, bottom), "#e0b862", tools=self.price_tools)

    def on_price_link(self, href: str) -> None:
        """시세 카드의 링크: 거래소 열기 / 조건 켜고 끄기 / 다시 검색."""
        if href.startswith("http"):
            webbrowser.open(href)
            return
        q = self._price_query
        if q is None or self._price_busy:
            return
        if href == "x:close":
            self._clear_price()
            return
        if href == "r:reset":  # 처음 조건으로 (값·켜고 끈 것·즉시 구매·기간)
            for f in q.filters:
                f.reset()
            q.status, q.indexed = "securable", "1week"
            self._price_dirty = True
            self._render_price()
            return
        if href == "s:go":
            self._redo_price()
            return
        if href.startswith("w:"):  # 휠: w:줄:±1
            _, i, d = href.split(":")
            if not (0 <= int(i) < len(q.filters)) or not q.filters[int(i)].nudge(int(d)):
                return
        elif href.startswith("f:"):
            i = int(href[2:])
            if 0 <= i < len(q.filters):
                if q.filters[i].kind == "opt":
                    q.filters[i].cycle()
                else:
                    q.filters[i].enabled = not q.filters[i].enabled
        elif href == "o:status":
            q.status = "available" if q.status == "securable" else "securable"
        elif href == "o:indexed":
            q.indexed = "" if q.indexed else "1week"
        self._price_dirty = True  # 검색은 "다시 검색" 을 누를 때 한 번 (여러 개를 바꿀 수 있게)
        self._render_price()

    def _redo_price(self) -> None:
        q = self._price_query
        if q is not None and self._price_league:
            self._price_search(self._price_league, self._price_lang, lambda data: q, keep_card=True)

    def show_last_price(self) -> None:
        if self._price_query is not None and self._price_res is not None:
            self._render_price()

    def _show_price(self, html_text, color: str, seconds: int = 60, tools: tuple = ()) -> None:
        """html_text: html 문자열, 또는 시세 결과 (위 html, 조건 줄들, 아래 html)."""
        self.price_msg, self.price_color = html_text, color
        self.price_tools = tools or (("✕", "x:close", t("닫기")),)  # 오류·안내 카드도 닫을 수 있게
        self._price_clear.start(seconds * 1000)
        # 알림 창은 평소 클릭 통과 — 시세 카드가 있는 동안만 눌러서 조건·거래소 열기·닫기 (포커스는 뺏지 않음)
        set_click_through(int(self.overlay.toast.winId()), False)
        self.refresh()

    def _clear_price(self) -> None:
        self.price_msg = ""
        set_click_through(int(self.overlay.toast.winId()), True)
        self.refresh()

    def _show_uncut(self, kind: str, level: int) -> None:
        snap = self.tracker.snapshot()
        c = snap.character
        title = t({"skill": "미가공 스킬 젬", "support": "미가공 보조 젬", "spirit": "미가공 정신력 젬"}[kind])
        title += t(" ({lv}레벨)", lv=level) if level else ""
        gp = self.gem_plan(c, snap.step.act if snap.step else "") if c else None
        if gp is None:
            body = t("빌드가 연결되지 않았습니다 — 우클릭 메뉴 → 빌드 (젬 안내)")
        else:
            body = uncut_advice(gp.build, kind, level, c.level, self.gem_names)
        self._show_item(t("💎 {title} → 빌드 기준", title=title) + f"<br>{body}", "#9fd3ff")

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
        if c is None or item is None or not is_gear(item):  # 젬·화폐(미가공 젬 등)는 장착 기준이 아니다
            return
        keys = hand_keys(item, c.gear) if item.hand else slot_keys(item.slot)
        name = lambda k: t(slot_label(k, keys))
        how = f"{via} → " if via else ""
        title, _, _ = compare(item, None, build_profile(c.gear))
        cur = next((k for k in ([MAIN, OFF] if item.hand else keys) if c.gear.get(k) == self.last_item_text), None)
        if cur is not None:
            if item.hand == "two" and cur == MAIN:
                keys = [MAIN, OFF]  # 양손 무기를 다시 등록 = 두 손에 하나씩 (거인의 피 등) → 보조 손으로 옮긴다
            if len(keys) == 1:
                return
            # 반지·한 손 무기처럼 칸이 둘: 다시 등록하면 다른 칸으로 옮긴다 (원래 칸은 등록 전 아이템으로 되돌림)
            key = keys[(keys.index(cur) + 1) % len(keys)] if cur in keys else keys[0]
            back_key, back_text = self._equip_undo
            if back_key == cur and back_text:
                c.gear[cur] = back_text
            else:
                c.gear.pop(cur, None)
        else:
            key = equip_key(item, c.gear, self.compare_target)
        dropped = ""
        if item.hand == "two" and keys == [MAIN] and OFF in c.gear:
            dropped = c.gear.pop(OFF)  # 양손 무기: 보조 손은 비운다 (양손을 한 손에 든다면 보조 손을 다시 등록)
        self._equip_undo = (key, c.gear.get(key, ""))
        c.gear[key] = self.last_item_text
        self.dirty = True
        msg = t("📌 {how}{slot} 장착 기준 등록 · {title}", how=how, slot=name(key), title=title)
        if dropped:
            msg += f'<br><span style="color:#9a9284">' + t("보조 손 기준을 비움 — 양손 무기를 한 손에 든다면 보조 손 아이템도 다시 등록") + '</span>'
        if len(keys) > 1:
            other = name(keys[(keys.index(key) + 1) % len(keys)])
            msg += f'<br><span style="color:#9a9284">' + t("{other} 자리에 꼈다면 한 번 더 두 번 복사 (또는 {key})", other=other, key=HOTKEYS["equip"]) + '</span>'
        self._show_item(msg, "#8fd18b")

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

    @timed("tick")
    # ---------------------------------------------------------- 새 버전
    def start_update_check(self, manual: bool = False) -> None:
        if self._update_busy or not (manual or (getattr(sys, "frozen", False)
                                                 and self.settings.get("update_check", True))):
            return
        self._update_busy = True
        if manual:
            self._set_update_msg(t("업데이트 확인 중…"), 30)

        def work():
            try:
                self._update_result = ("checked", updater.fetch_latest(), manual)
            except Exception as e:  # 네트워크 오류 등: 조용히 넘긴다 (수동 확인일 때만 알림)
                self._update_result = ("error", str(e), manual)
        threading.Thread(target=work, daemon=True).start()

    def install_update(self) -> None:
        rel = self.update
        if rel is None or self._update_busy:
            return
        if not (updater.installed() and rel.setup_url):  # 휴대용·개발 실행: 릴리스 페이지
            webbrowser.open(rel.page_url)
            return
        self._update_busy = True
        self._set_update_msg(t("🆕 {v} 내려받는 중…", v=rel.version), 600)

        def work():
            try:
                path = updater.download(rel, Path(os.environ.get("TEMP", ".")) / "poe2-saegida-update")
                self._update_result = ("downloaded", path, True)
            except Exception as e:
                self._update_result = ("error", str(e), True)
        threading.Thread(target=work, daemon=True).start()

    def _handle_update_result(self) -> None:
        if self._update_result is None:
            return
        kind, value, manual = self._update_result
        self._update_result = None
        self._update_busy = False
        if kind == "checked":
            if value is not None and updater.is_newer(value.version):
                self.update = value
                if manual:
                    self._set_update_msg("", 0)  # 🆕 새 버전 줄이 대신 보인다
            elif manual:
                self._set_update_msg(t("✓ 최신 버전입니다 ({v})", v=__version__), 8)
        elif kind == "downloaded":
            # 설치 파일이 오버레이를 닫고 덮어쓴 뒤 다시 실행한다 (/UPDATE=1)
            self.save()
            subprocess.Popen([str(value), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/UPDATE=1"],
                             close_fds=True)
            self.app.quit()
            return
        elif kind == "error" and manual:
            self._set_update_msg(t("업데이트 확인 실패: {e}", e=value[:80]), 15)
        self.refresh()

    def _set_update_msg(self, text: str, seconds: float) -> None:
        self._update_msg = text
        self._update_msg_until = time.monotonic() + seconds
        if text:
            QTimer.singleShot(int(seconds * 1000) + 100, self.refresh)
        self.refresh()

    # ---------------------------------------------------------- 기록 내보내기
    def _current_timer(self):
        c = self.tracker.snapshot().character
        if c is None or c.name in PLACEHOLDERS:
            return None, None
        # 카드·스플릿에는 PB 비교 설정과 관계없이 다른 캐릭터 기준 PB 를 넣는다
        return c, timer_view(c, personal_bests(self.tracker.chars.values(), exclude=c.name), 0.0)

    def export_card(self) -> None:
        c, tv = self._current_timer()
        if c is None or tv is None:
            return
        path = export.save_card(c, tv, self.tracker.snapshot().league)
        self.flash = t("완주 카드 저장: {p}", p=path.name)  # 전체 경로는 사용자 이름이 보여서 파일 이름만
        os.startfile(path.parent)
        self.refresh()

    def export_lss(self) -> None:
        c, tv = self._current_timer()
        if c is None or tv is None:
            return
        best = personal_bests(self.tracker.chars.values())  # 모든 캐릭터 중 구간별 최고 (골드)
        path = export.save_lss(c.name, tv, best)
        self.flash = t("LiveSplit 파일 저장: {p}", p=path.name)
        os.startfile(path.parent)
        self.refresh()

    def _notice_text(self) -> str:
        parts = [self.notice] if self.notice else []
        c = self.tracker.snapshot().character if self.tracker else None
        if c and c.partial_from and not c.partial_ack and c.name not in PLACEHOLDERS:
            parts.append('<span style="color:#e0b862">' + t("📋 {act} 중간부터 잡힌 캐릭터 — 다른 PC 의 기록이 있으면 우클릭 → 진행 코드 → 붙여넣기, 없으면 → 이전 보상 받음으로 채우기", act=i18n.act(c.partial_from)) + '</span>')
        if self._update_msg and time.monotonic() < self._update_msg_until:
            parts.append(f'<span style="color:#9a9284">{html.escape(self._update_msg)}</span>')
        if self.update is not None:
            parts.append(f'<span style="color:#8fd18b">{t("🆕 새 버전 {v} — 우클릭 → 업데이트", v=self.update.version)}</span>')
        return "<br>".join(parts)

    def tick(self) -> None:
        self._handle_update_result()
        self._handle_price_result()
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
            "pending": [[p.code, p.level, p.ts, p.seed] for p in self.tracker.pending],
            "relog": self.tracker.relog,
            "eg_backfill": True,
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
        if self.overlay.click_through:
            self.overlay.tools.hide()  # 클릭 통과 중엔 아이콘을 누를 수 없다
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

    def set_language(self, lang: str) -> None:
        """언어를 바꾸면 가이드·데이터 파일도 바뀌므로 오버레이를 다시 시작한다."""
        if self.settings.get("language", "auto") == lang:
            return
        self.settings["language"] = lang
        config.save_settings(self.settings)
        self.restart()

    def restart(self) -> None:
        self.save()
        args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
        QProcess.startDetached(sys.executable, [a for a in args if a != RESTARTED] + [RESTARTED])
        self.app.quit()

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
        self.flash = t("자동 숨김 켜짐") if self.settings["auto_hide"] else t("자동 숨김 꺼짐 (항상 표시)")
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
        path, _ = QFileDialog.getOpenFileName(None, t("POE2 로그 파일 선택"), "", t("로그 (*.txt)"))
        if path:
            self.settings["log_path"] = path
            config.save_settings(self.settings)
            self.log_path = Path(path)
            self.tracker = Tracker(self.guide, encounters=self.encounters)
            self.tracker.endgame = self.endgame_bosses
            self.tracker.passive_sources = self.passive_sources
            self.notice = ""
            self.bootstrap()
            self.refresh()

    def choose_guide(self) -> None:
        path, _ = QFileDialog.getOpenFileName(None, t("가이드 CSV 선택"), "", "CSV (*.csv)")
        if path:
            self.settings["guide_path"] = path
            self._use_guide(Path(path))

    def set_guide_kind(self, kind: str) -> None:
        """동봉 가이드 바꾸기 (기본 / 스피드런). 직접 고른 CSV 는 해제. 진행 위치는 지역 코드로 다시 맞춘다."""
        self.settings["guide_kind"] = kind
        self.settings["guide_path"] = ""
        self._use_guide(config.find_guide("", self.lang, kind))

    def _use_guide(self, path: Path) -> None:
        config.save_settings(self.settings)
        self.guide_file = path
        self._guide_mtime = self._mtime(self.guide_file)
        self.guide = Guide.load(self.guide_file)
        self.tracker.set_guide(self.guide)
        self.dirty = True
        self.refresh()

    def on_tool(self, key: str) -> None:
        """패널 오른쪽 위 아이콘."""
        if key in ("prev", "next"):
            self.step(-1 if key == "prev" else 1)
        elif key == "rewards":
            self.toggle_rewards()
        elif key == "gems":
            self.toggle_gem_card()
        elif key == "expand":
            self.expand_compact()

    def expand_compact(self) -> None:
        """보스전 한 줄 → 일반 패널. 지역을 옮기면 다시 한 줄 모드가 동작한다."""
        c = self.tracker.snapshot().character
        if c is None:
            return
        self._expanded_at = (c.name, c.zone)
        self.refresh()

    def build_menu(self, m: QMenu, clear: bool = False) -> None:
        if clear:
            m.clear()
        if self.update is not None:
            label = (t("🆕 업데이트 설치 ({v})", v=self.update.version) if updater.installed()
                     else t("🆕 새 버전 받기 ({v}) — 릴리스 페이지", v=self.update.version))
            m.addAction(label, self.install_update)
            m.addSeparator()
        m.addAction(t("다음 단계  ({key})", key=HOTKEYS['next']), lambda: self.step(1))
        m.addAction(t("이전 단계  ({key})", key=HOTKEYS['prev']), lambda: self.step(-1))
        m.addSeparator()

        cm = m.addMenu(t("캐릭터"))
        grp = QActionGroup(cm)
        auto = QAction(t("자동 인식"), cm, checkable=True)
        auto.setChecked(not self.tracker.manual_lock)
        auto.triggered.connect(lambda: self.select_character(None))
        grp.addAction(auto)
        cm.addAction(auto)
        cm.addSeparator()
        chars = sorted((c for c in self.tracker.chars.values() if c.name not in PLACEHOLDERS),
                       key=lambda c: c.last_seen, reverse=True)
        for c in chars[:15]:
            a = QAction(f"{c.name}  ({i18n.cls(c.cls)} Lv{c.level})", cm, checkable=True)
            a.setChecked(self.tracker.manual_lock and self.tracker.current == c.name)
            a.triggered.connect(lambda _=False, n=c.name: self.select_character(n))
            grp.addAction(a)
            cm.addAction(a)

        cur = self.tracker.snapshot().character
        mm = m.addMenu(t("모드: {mode}", mode=t(cur.mode or '미지정')) if cur else t("모드"))
        mm.setEnabled(cur is not None)
        mgrp = QActionGroup(mm)
        for mode in ("", "소프트코어", "하드코어", "SSF", "HC SSF"):
            a = QAction(t(mode or "미지정"), mm, checkable=True)
            a.setChecked(bool(cur) and cur.mode == mode)
            a.triggered.connect(lambda _=False, md=mode: self.set_mode(md))
            mgrp.addAction(a)
            mm.addAction(a)

        self.rescan_builds()  # 메뉴를 열 때는 항상 최신 목록
        bm = m.addMenu(t("빌드 (젬 안내)"))
        cur_c = self.tracker.snapshot().character
        cur_f = self.settings.get("char_builds", {}).get(cur_c.name) if cur_c else None
        bgrp = QActionGroup(bm)
        auto_b = QAction(t("게임에 연결된 빌드 따라가기"), bm, checkable=True)
        auto_b.setChecked(not cur_f)
        auto_b.triggered.connect(lambda: self.set_char_build(None))
        bgrp.addAction(auto_b)
        bm.addAction(auto_b)
        bm.addSeparator()
        for fam, files in families(self.build_files).items():
            a = QAction(t("{label}  ({n}개 구간)", label=files[0].label, n=len(files)), bm, checkable=True)
            a.setChecked(fam == cur_f)
            a.triggered.connect(lambda _=False, f=fam: self.set_char_build(f))
            bgrp.addAction(a)
            bm.addAction(a)

        cur_op = float(self.settings.get("window_opacity", 1.0))
        om = m.addMenu(t("투명도: {v}%  ({key} / Down)", v=round(cur_op * 100), key=HOTKEYS['opacity_up']))
        ogrp = QActionGroup(om)
        for v in OPACITY_STEPS:
            a = QAction(f"{round(v * 100)}%", om, checkable=True)
            a.setChecked(abs(v - cur_op) < 0.01)
            a.triggered.connect(lambda _=False, val=v: self.set_opacity(val))
            ogrp.addAction(a)
            om.addAction(a)

        for key, text in (("boss_compact", "보스전 간단 모드 (한 줄)"), ("tab_hint", "보스전 시작 시 Tab → 미니맵 안내"),
                          ("zone_tips", "지역 길 찾기 메모 (🧭)")):
            act = QAction(t(text), m, checkable=True)
            act.setChecked(self.settings.get(key, True))
            act.triggered.connect(lambda _=False, k=key: self.toggle_setting(k))
            m.addAction(act)
        rx = QAction(t("상인 대화 시 정규식 자동 복사"), m, checkable=True)
        rx.setChecked(self.settings.get("auto_copy_regex", True))
        rx.triggered.connect(self.toggle_auto_copy)
        m.addAction(rx)
        pb = QAction(t("PB 비교 표시 (연습용)"), m, checkable=True)
        pb.setChecked(self.settings.get("show_pb", False))
        pb.triggered.connect(self.toggle_pb)
        m.addAction(pb)

        ct = QAction(t("클릭 통과  ({key})", key=HOTKEYS['click_through']), m, checkable=True)
        ct.setChecked(self.overlay.click_through)
        ct.triggered.connect(self.toggle_click_through)
        m.addAction(ct)
        m.addAction(t("숨기기/보이기  ({key})", key=HOTKEYS['toggle']), self.toggle_visible)
        ah = QAction(t("게임 창이 아닐 때 자동 숨김  ({key})", key=HOTKEYS['auto_hide']), m, checkable=True)
        ah.setChecked(self.settings.get("auto_hide", True))
        ah.triggered.connect(self.toggle_auto_hide)
        m.addAction(ah)
        m.addAction(t("영구 보상 전체 목록  ({key})", key=HOTKEYS['rewards']), self.toggle_rewards)
        m.addAction(t("젬 카드  ({key})", key=HOTKEYS['gems']), self.toggle_gem_card)
        m.addSeparator()
        m.addAction(t("위치 초기화 (왼쪽 위 기본 위치)"), self.reset_position)
        gm = m.addMenu(t("가이드: {name}", name=Path(self.guide.source).name))
        ggrp = QActionGroup(gm)
        custom = bool(self.settings.get("guide_path"))
        for kind, text in (("default", t("기본 (보상 다 챙기기)")), ("speedrun", t("스피드런"))):
            a = QAction(text, gm, checkable=True)
            a.setEnabled(config.bundled_guide(kind, self.lang) is not None)
            a.setChecked(not custom and self.settings.get("guide_kind", "default") == kind)
            a.triggered.connect(lambda _=False, k=kind: self.set_guide_kind(k))
            ggrp.addAction(a)
            gm.addAction(a)
        gm.addSeparator()
        gm.addAction(t("가이드 CSV 선택…"), self.choose_guide)
        gm.addAction(t("가이드 파일 열기"), lambda: os.startfile(self.guide.source))
        m.addAction(t("로그 파일 선택…"), self.choose_log)
        info = m.addAction(t("가이드: {name} ({n}단계)", name=Path(self.guide.source).name, n=len(self.guide)))
        info.setEnabled(False)
        info2 = m.addAction(t("로그: {path}", path=self.log_path or t('없음')))
        info2.setEnabled(False)
        lm = m.addMenu(t("언어 / Language"))
        lgrp = QActionGroup(lm)
        cur_lang = self.settings.get("language", "auto")
        for key, text in (("auto", t("자동 (로그 파일 기준)")), ("ko", "한국어"), ("en", "English")):
            a = QAction(text, lm, checkable=True)
            a.setChecked(cur_lang == key)
            a.triggered.connect(lambda _=False, k=key: self.set_language(k))
            lgrp.addAction(a)
            lm.addAction(a)
        pm = m.addMenu(t("진행 코드 (PC 옮기기)"))
        pc = self.tracker.snapshot().character
        a = pm.addAction(t("진행 코드 복사"), self.copy_progress_code)
        a.setEnabled(bool(pc and pc.name not in PLACEHOLDERS))
        pm.addAction(t("진행 코드 붙여넣기 (클립보드)"), self.paste_progress_code)
        pm.addSeparator()
        a = pm.addAction(t("이전 보상 받음으로 채우기 (지나온 단계)"), self.fill_previous_rewards)
        a.setEnabled(bool(pc and pc.name not in PLACEHOLDERS))
        if pc and pc.partial_from and not pc.partial_ack:
            pm.addAction(t("안내 닫기"), self.dismiss_partial)
        rm = m.addMenu(t("기록 내보내기"))
        cur_c = self.tracker.snapshot().character
        has_splits = bool(cur_c and cur_c.splits)
        a = rm.addAction(t("캠페인 완주 카드 (PNG)"), self.export_card)
        a.setEnabled(bool(cur_c and ENDGAME in cur_c.splits))
        a = rm.addAction(t("LiveSplit 스플릿 파일 (.lss)"), self.export_lss)
        a.setEnabled(has_splits)
        rm.addAction(t("저장 폴더 열기"), export.open_out_dir)
        um = m.addMenu(t("업데이트 (현재 {v})", v=__version__))
        um.addAction(t("지금 확인"), lambda: self.start_update_check(manual=True))
        uc = QAction(t("새 버전 자동 확인"), um, checkable=True)
        uc.setChecked(self.settings.get("update_check", True))
        uc.triggered.connect(lambda: self.toggle_setting("update_check"))
        um.addAction(uc)
        a = m.addAction(t("💰 마지막 시세 다시 보기"), self.show_last_price)
        a.setEnabled(self._price_res is not None)
        m.addSeparator()
        m.addAction(t("☕ 개발자에게 커피 사주기 (Ko-fi)"), lambda: webbrowser.open(KOFI_URL))
        m.addAction(t("종료"), self.app.quit)


def main() -> int:
    from .watchdog import Watchdog
    dog = Watchdog(config.APP_DIR / "overlay.log")  # 멈추면 원인(호출 위치)을 남긴다
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("poe2-saegida")
    ctl = Controller(app)  # noqa: F841 - 이벤트 루프 동안 유지
    beat = QTimer()
    beat.timeout.connect(dog.heartbeat)
    beat.start(1000)
    code = app.exec()
    dog.stop()
    dog.write(f"종료 ({code})")
    return code
