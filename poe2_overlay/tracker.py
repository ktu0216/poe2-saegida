"""로그 이벤트로 '지금 접속한 캐릭터'와 그 캐릭터의 가이드 위치를 추적한다.

로그에는 로그인한 캐릭터 이름이 직접 찍히지 않는다. 그래서
  1) 접속(세션) 시작 시 캐릭터를 '미확정'으로 두고 지역 이동을 버퍼에 쌓는다.
  2) 이름이 들어간 첫 줄(레벨업/사망/보상)이 나오면 그 캐릭터로 확정하고 버퍼를 반영한다.
  3) 미확정 동안에는 진입한 지역과 가장 잘 맞는 캐릭터를 '추정'해서 보여준다.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

from .encounters import Encounters
from .guide import Guide, Step, act_label, is_town
from .logparse import (
    Afk,
    AreaEntered,
    Death,
    Event,
    LevelUp,
    LoginConnect,
    NewCharacter,
    NpcLine,
    PassivePoints,
    Reward,
    SceneName,
)

NEW_CHAR = "(새 캐릭터)"
UNKNOWN_CHAR = "(확인 중)"
PLACEHOLDERS = (NEW_CHAR, UNKNOWN_CHAR)
HC_DEATH = {"하드코어": "소프트코어", "HC SSF": "SSF"}
FIRST_ZONE = "g1_1"
MAX_GAP = 30 * 60  # 이보다 긴 로그 공백은 플레이 시간에서 뺀다


def parse_ts(ts: str) -> Optional[datetime]:
    try:
        return datetime.strptime(ts, "%Y/%m/%d %H:%M:%S")
    except ValueError:
        return None


def zone_act(code: str) -> str:
    code = code.lower()
    if code.startswith("map"):
        return "엔드게임"
    return act_label(code)


@dataclass
class Character:
    name: str
    cls: str = ""
    level: int = 1
    cursor: int = 0
    cursor_zone: str = ""  # 가이드가 바뀌었을 때 위치 복구용
    zone: str = ""
    area_name: str = ""
    area_level: int = 0
    deaths: int = 0
    rewards: list[str] = field(default_factory=list)
    passive_points: int = 0
    weapon_set_points: int = 0
    last_seen: str = ""
    league: str = ""
    mode: str = ""  # 사용자가 지정: 소프트코어/하드코어/SSF/HC SSF
    play_seconds: float = 0.0  # 자리 비움·로그아웃·긴 공백을 뺀 플레이 시간
    splits: dict[str, float] = field(default_factory=dict)  # 액트 -> 처음 들어갔을 때의 play_seconds
    # 가이드 단계 번호 -> {"boss": engaged|killed|died, "marker": 진행 표시}  (보스/진행 대사로 채움)
    step_flags: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Character":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class Snapshot:
    character: Optional[Character]
    confirmed: bool
    step: Optional[Step]
    upcoming: list[Step]
    previous: Optional[Step]
    off_route: bool
    total: int
    league: str = ""
    flags: dict = field(default_factory=dict)  # 현재 단계의 보스/진행 상태
    boss: str = ""  # 현재 단계 지역의 보스 이름


class Tracker:
    def __init__(self, guide: Guide, characters: Optional[dict[str, Character]] = None,
                 current: Optional[str] = None, encounters: Optional[Encounters] = None):
        self.guide = guide
        self.encounters = encounters or Encounters()
        self.chars: dict[str, Character] = characters or {}
        self.current: Optional[str] = current if current in self.chars else None
        self.confirmed = self.current is not None
        self.pid: Optional[str] = None
        self.pending: list[AreaEntered] = []
        self.provisional: Optional[Character] = None
        self._scene_for_pending: dict[str, str] = {}
        self.manual_lock = False  # 사용자가 직접 캐릭터를 고르면 추정/전환하지 않음
        self.league = ""  # 게임 설정 파일의 현재 리그 (라이브 감시 중에만 설정)
        self.last_ts: Optional[datetime] = None  # 현재 세션의 마지막 로그 시각
        self.afk = False
        self._pending_play = 0.0  # 미확정 동안 쌓인 플레이 시간
        self.new_char_session = False  # 튜토리얼 줄로 '새 캐릭터'가 확정된 세션
        for c in self.chars.values():
            self._repair_cursor(c)

    # ---------------------------------------------------------------- 이벤트
    def feed(self, ev: Event) -> None:
        new_pid = self.pid is not None and ev.pid != self.pid
        self._account_time(ev, reset=new_pid or isinstance(ev, LoginConnect))
        if new_pid:
            self._new_session()
        self.pid = ev.pid

        if isinstance(ev, LoginConnect):
            self._new_session()
        elif isinstance(ev, AreaEntered):
            self._on_area(ev)
        elif isinstance(ev, SceneName):
            self._on_scene(ev)
        elif isinstance(ev, LevelUp):
            if c := self._identify(ev.name, ev.ts):
                c.cls, c.level = ev.cls, ev.level
        elif isinstance(ev, Death):
            if c := self._identify(ev.name, ev.ts):
                c.deaths += 1
                f = self._flags(c)
                if f is not None and f.get("boss") == "engaged":
                    f["boss"] = "died"
                # 하드코어 캐릭터는 죽으면 일반 리그로 옮겨진다
                c.mode = HC_DEATH.get(c.mode, c.mode)
        elif isinstance(ev, Reward):
            if c := self._identify(ev.name, ev.ts):
                c.rewards.append(ev.text)
        elif isinstance(ev, NpcLine):
            self._on_npc(ev)
        elif isinstance(ev, NewCharacter):
            self._on_new_character()
        elif isinstance(ev, Afk):
            self.afk = ev.on
        elif isinstance(ev, PassivePoints):
            if c := self._active():
                if ev.weapon_set:
                    c.weapon_set_points += ev.points
                else:
                    c.passive_points += ev.points

    def _account_time(self, ev: Event, reset: bool) -> None:
        t = parse_ts(ev.ts)
        if t is None:
            return
        if reset:
            self.last_ts, self.afk = None, False
        elif self.last_ts is not None and not self.afk:
            delta = (t - self.last_ts).total_seconds()
            if 0 < delta <= MAX_GAP and (c := self._active()):
                c.play_seconds += delta
                if not self.confirmed:
                    self._pending_play += delta
        self.last_ts = t

    def _new_session(self) -> None:
        self._pending_play = 0.0
        self.new_char_session = False
        if self.manual_lock:
            return
        self._flush_pending_to_provisional()
        self.confirmed = False
        self.pending = []
        self.provisional = Character(name=UNKNOWN_CHAR)

    def _flags(self, c: Character) -> Optional[dict]:
        """현재 가이드 단계의 상태 (캐릭터가 그 단계 지역에 있을 때만)."""
        steps = self.guide.steps
        if not steps or not (0 <= c.cursor < len(steps)) or steps[c.cursor].zone != c.zone:
            return None
        return c.step_flags.setdefault(str(c.cursor), {})

    def _on_npc(self, ev: NpcLine) -> None:
        c = self._active()
        enc = self.encounters.get(c.zone) if c else None
        if not enc:
            return
        f = self._flags(c)
        if f is None:
            return
        if ev.who in enc.bosses:
            f["boss"] = "engaged"
        for m in enc.markers:
            if ev.who == m.speaker and m.text in ev.text:
                f["marker"] = m.label

    def _on_new_character(self) -> None:
        """새 캐릭터 확정 (이름은 아직 모름). 이번 세션의 지역 이동을 새 캐릭터에 다시 적용한다."""
        if self.confirmed or self.manual_lock:
            return
        self.new_char_session = True
        old = self.provisional
        if old is not None and old.name == NEW_CHAR:
            return
        nc = Character(name=NEW_CHAR, league=self.league, mode=old.mode if old and old.name in PLACEHOLDERS else "")
        for p in self.pending:
            self._apply_area(nc, p.code, p.level, p.ts)
        nc.play_seconds = self._pending_play
        self.provisional = nc

    def _on_area(self, ev: AreaEntered) -> None:
        if self.confirmed and self.current:
            self._apply_area(self.chars[self.current], ev.code, ev.level, ev.ts)
            return
        self.pending.append(ev)
        self.provisional = self._guess()
        if self.provisional:
            self._apply_area(self.provisional, ev.code, ev.level, ev.ts)

    def _on_scene(self, ev: SceneName) -> None:
        if c := self._active():
            if c.zone and not c.area_name:
                c.area_name = ev.name

    def _apply_area(self, c: Character, code: str, level: int, ts: str) -> None:
        c.zone = code.lower()
        c.area_name = self.guide.area_name(code) or ""
        c.area_level = level
        c.last_seen = ts
        act = zone_act(code)
        if act and act not in c.splits:
            c.splits[act] = c.play_seconds
        if self.league:
            c.league = self.league
        if code.lower().startswith("map") and self.guide.steps:
            # 엔드게임 지도에 들어갔다면 캠페인은 끝난 캐릭터
            c.cursor = len(self.guide.steps) - 1
            c.cursor_zone = self.guide.steps[c.cursor].zone
            return
        steps = self.guide.steps
        cur = steps[c.cursor] if steps and 0 <= c.cursor < len(steps) else None
        flags = c.step_flags.get(str(c.cursor), {}) if cur else {}
        if cur and flags.get("boss") == "engaged" and code.lower() != cur.zone:
            flags["boss"] = "killed"  # 보스와 싸우다 죽지 않고 지역을 떠남 = 처치
        new = self.guide.next_position(c.cursor, code)
        if new is not None and cur and new == c.cursor + 1 and steps[new].is_town:
            enc = self.encounters.get(cur.zone)
            if enc and enc.bosses and flags.get("boss") != "killed":
                new = None  # 보스 처치 전 마을 방문(정비)은 단계를 넘기지 않는다
        if new is not None:
            c.cursor = new
            c.cursor_zone = self.guide.steps[new].zone

    # ------------------------------------------------------- 캐릭터 식별
    def _identify(self, name: str, ts: str) -> Optional[Character]:
        """이름이 찍힌 이벤트. 세션의 캐릭터를 확정하거나, 다른 사람(파티원)이면 무시."""
        if self.confirmed:
            return self.chars[self.current] if name == self.current else None
        if self.manual_lock and self.current and name != self.current:
            return None
        c = self.chars.get(name)
        if c is not None and self.new_char_session:
            # 삭제한 캐릭터와 같은 이름으로 새로 만든 경우: 옛 기록은 PB용으로 이름을 바꿔 보관
            archived = f"{name} (이전 {c.last_seen[:10]})"
            c.name = archived
            self.chars[archived] = c
            c = None
        if c is None:
            c = Character(name=name)
            self.chars[name] = c
            replay = self.pending
        elif self.provisional is not None and self.provisional.name == name:
            c = self.chars[name] = self.provisional  # 추정이 맞았으므로 추정본을 그대로 채택
            replay = []
        else:
            replay = self.pending
        for p in replay:
            self._apply_area(c, p.code, p.level, p.ts)
        if c is not self.provisional:  # 추정본을 채택한 경우는 이미 시간이 쌓여 있다
            c.play_seconds += self._pending_play
        self._pending_play = 0.0
        c.last_seen = ts
        if self.league:
            c.league = self.league
        p = self.provisional
        if p is not None and p.name in PLACEHOLDERS and p.mode and not c.mode:
            c.mode = p.mode  # 확정 전에 지정한 모드 이어받기
        self.current = name
        self.confirmed = True
        self.pending = []
        self.provisional = None
        return c

    def _guess(self) -> Optional[Character]:
        """미확정 세션에서 버퍼의 지역들과 가장 잘 맞는 캐릭터를 고른다."""
        if self.manual_lock and self.current:
            return self.chars[self.current]
        codes = [p.code.lower() for p in self.pending]
        first = codes[0]
        # 튜토리얼 줄이 나왔거나, 접속하자마자 강둑(g1_1)이면 새 캐릭터로 본다.
        if self.new_char_session or first == FIRST_ZONE:
            if self.provisional and self.provisional.name == NEW_CHAR:
                return self.provisional
            nc = Character(name=NEW_CHAR, league=self.league)
            return nc
        best, best_score = None, -1
        cands = [c for c in self.chars.values()
                 if not (self.league and c.league and c.league != self.league)]
        for c in sorted(cands, key=lambda c: c.last_seen, reverse=True):
            score = self._match_score(c, codes)
            if score > best_score:
                best, best_score = c, score
        if best is None or best_score <= 0:
            # 은신처 등 단서가 없는 곳: 아무 캐릭터나 고르지 말고 확인 대기
            if self.provisional and self.provisional.name == UNKNOWN_CHAR:
                return self.provisional
            return Character(name=UNKNOWN_CHAR)
        # 추정 캐릭터 원본은 확정 전까지 건드리지 않도록 복사본을 쓴다.
        if self.provisional and self.provisional.name == best.name:
            return self.provisional
        return Character.from_dict(best.to_dict())

    def _match_score(self, c: Character, codes: list[str]) -> int:
        steps = self.guide.steps
        if not steps:
            return 0
        score = 0
        window = {s.zone for s in steps[max(0, c.cursor - 1): c.cursor + 4]}
        for code in codes:
            if code == c.zone:
                score += 3
            elif code in window and not is_town(code):
                score += 2
            elif code in window:
                score += 1
        return score

    def _flush_pending_to_provisional(self) -> None:
        """세션이 이름 확인 없이 끝났을 때: 추정 캐릭터가 기존 캐릭터면 그대로 반영한다."""
        p = self.provisional
        if p and p.name in self.chars and self.pending:
            self.chars[p.name] = p

    def _active(self) -> Optional[Character]:
        if self.confirmed and self.current:
            return self.chars[self.current]
        return self.provisional

    def _display(self) -> Optional[Character]:
        """화면 표시용: 아직 아무 단서가 없으면 마지막으로 플레이한 캐릭터."""
        if c := self._active():
            return c
        if self.current in self.chars:
            return self.chars[self.current]
        if self.chars:
            return max(self.chars.values(), key=lambda c: c.last_seen)
        return None

    def restore_pending(self, pending: list, scene: str = "") -> None:
        """저장해 둔 미확정 세션을 되살린다 (오버레이 재시작 대비)."""
        self.confirmed = False
        self.pending = []
        self.provisional = Character(name=UNKNOWN_CHAR)
        for code, level, ts in pending:
            self._on_area(AreaEntered(ts, self.pid or "", code, int(level)))
        if self.provisional and scene and not self.provisional.area_name:
            self.provisional.area_name = scene

    # ------------------------------------------------------- 수동 조작
    def set_mode(self, mode: str) -> None:
        if c := self._display():
            c.mode = mode

    def select_character(self, name: Optional[str]) -> None:
        """None 이면 자동 모드로 복귀."""
        if name is None:
            self.manual_lock = False
            return
        if name not in self.chars:
            return
        self.manual_lock = True
        self.current = name
        self.confirmed = True
        self.pending = []
        self.provisional = None

    def move_cursor(self, delta: int) -> None:
        c = self._display()
        if not c or not self.guide.steps:
            return
        c.cursor = max(0, min(len(self.guide.steps) - 1, c.cursor + delta))
        c.cursor_zone = self.guide.steps[c.cursor].zone

    def set_guide(self, guide: Guide) -> None:
        self.guide = guide
        for c in self.chars.values():
            self._repair_cursor(c)

    def _repair_cursor(self, c: Character) -> None:
        steps = self.guide.steps
        if not steps:
            c.cursor = 0
            return
        if 0 <= c.cursor < len(steps) and (not c.cursor_zone or steps[c.cursor].zone == c.cursor_zone):
            return
        # 같은 지역 중 예전 위치에 가장 가까운 단계로 옮긴다.
        cands = [s.index for s in steps if s.zone == c.cursor_zone]
        c.cursor = min(cands, key=lambda i: abs(i - c.cursor)) if cands else min(c.cursor, len(steps) - 1)
        c.cursor_zone = steps[c.cursor].zone

    # ------------------------------------------------------- 화면용 요약
    def snapshot(self, upcoming: int = 3) -> Snapshot:
        c = self._display()
        steps = self.guide.steps
        if not c or not steps or c.name == UNKNOWN_CHAR:
            return Snapshot(c, self.confirmed, None, [], None, False, len(steps),
                            (c.league if c else "") or self.league)
        i = max(0, min(c.cursor, len(steps) - 1))
        step = steps[i]
        off = bool(c.zone) and c.zone != step.zone and not (
            i + 1 < len(steps) and steps[i + 1].zone == c.zone)
        return Snapshot(
            character=c,
            confirmed=self.confirmed,
            step=step,
            upcoming=steps[i + 1: i + 1 + upcoming],
            previous=steps[i - 1] if i > 0 else None,
            off_route=off,
            total=len(steps),
            league=c.league or self.league,
            flags=dict(c.step_flags.get(str(i), {})),
            boss=self.encounters.boss_name(step.zone),
        )
