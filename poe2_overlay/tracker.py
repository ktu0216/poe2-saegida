"""로그 이벤트로 '지금 접속한 캐릭터'와 그 캐릭터의 가이드 위치를 추적한다.

로그에는 로그인한 캐릭터 이름이 직접 찍히지 않는다. 그래서
  1) 접속(세션) 시작 시 캐릭터를 '미확정'으로 두고 지역 이동을 버퍼에 쌓는다.
  2) 이름이 들어간 첫 줄(레벨업/사망/보상)이 나오면 그 캐릭터로 확정하고 버퍼를 반영한다.
  3) 미확정 동안에는 진입한 지역과 가장 잘 맞는 캐릭터를 '추정'해서 보여준다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

from . import endgame, i18n
from .encounters import Encounters
from .guide import Guide, Step, act_label, is_town
from .logparse import (
    Afk,
    AreaEntered,
    AscendancyNode,
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
# 전직 ID -> 한국어 전직 이름 (레벨업 줄 "(젬링 리저네어)" 에서 확인한 것). 모르는 전직은 다음 레벨업 때 채워진다.
ASCENDANCY_KO = {
    "Mercenary2": "위치헌터", "Mercenary3": "젬링 리저네어", "Warrior1": "타이탄", "Warrior2": "워브링어",
    "Warrior3": "스미스 오브 키타바", "Sorceress1": "스톰위버", "Huntress1": "아마존", "Witch3": "리치",
    "Druid1": "오라클", "Druid2": "샤먼",
}
# 영어 클라이언트 (전직 노드를 찍은 뒤 다음 레벨업 줄 전까지 클래스 이름)
ASCENDANCY_EN = {
    "Mercenary2": "Witchhunter", "Mercenary3": "Gemling Legionnaire", "Warrior1": "Titan", "Warrior2": "Warbringer",
    "Warrior3": "Smith of Kitava", "Sorceress1": "Stormweaver", "Sorceress3": "Disciple of Varashta",
    "Huntress1": "Amazon", "Witch3": "Lich", "Druid1": "Oracle", "Druid2": "Shaman",
}
ASCENSION_MAX = 4  # 전직 시련 1~4차, 한 번에 2포인트


def _ascension_points(nodes: list[str]) -> int:
    """찍은 전직 노드 → 사용한 포인트. 시작 노드와 선택지 노드(Notable2_1 등)는 포인트를 쓰지 않는다."""
    return sum(1 for n in nodes if not n.endswith("Start") and not re.search(r"Notable\d+_\d", n))


def ascension_stage(nodes: list[str]) -> int:
    return min(ASCENSION_MAX, (_ascension_points(nodes) + 1) // 2)


HC_DEATH = {"하드코어": "소프트코어", "HC SSF": "SSF"}


# 전투 중 보스 대사가 이만큼 없으면 화면은 일반 패널로 (처치 대사가 없는 보스: 잡고 나서 다음 단계를 볼 수 있게).
# 기록상 처치는 그대로 지역을 떠날 때. 보스가 다시 말하면 다시 한 줄.
BOSS_QUIET_SEC = 30


def fight_quiet(flags: dict, now: datetime) -> bool:
    """마지막 보스 대사 뒤 BOSS_QUIET_SEC 초가 지났는지."""
    ts = parse_ts(flags.get("last_line", "") or "")
    return ts is not None and (now - ts).total_seconds() > BOSS_QUIET_SEC


def league_for_mode(league: str, mode: str) -> str:
    """일반 모드 캐릭터에 하드코어 리그가 찍혀 있으면 앞의 HC 를 뗀다 (예전 버전이 캐릭터 선택 화면의 리그를 잘못 옮겨 적은 값)."""
    if mode in ("소프트코어", "SSF") and league.startswith("HC "):
        return league[3:]
    return league
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
    mode_prompt: bool = False  # 새 캐릭터: 모드 선택 버튼을 보여줄지 (선택/건너뛰기/진행하면 False)
    play_seconds: float = 0.0  # 자리 비움·로그아웃·긴 공백을 뺀 플레이 시간
    splits: dict[str, float] = field(default_factory=dict)  # 액트 -> 처음 들어갔을 때의 play_seconds
    # 가이드 단계 번호 -> {"boss": engaged|killed|died, "marker": 진행 표시}  (보스/진행 대사로 채움)
    step_flags: dict[str, dict] = field(default_factory=dict)
    # 단계 번호 -> 그 단계의 지역 (가이드에 단계를 넣거나 빼서 번호가 밀리면 같은 지역으로 step_flags 를 옮기는 데 쓴다)
    flag_zones: dict[str, str] = field(default_factory=dict)
    gear: dict[str, str] = field(default_factory=dict)  # 부위 -> 장착 기준 아이템 텍스트 (Ctrl+C)
    last_field_zone: str = ""  # 마지막으로 있던 마을 밖 지역
    jump_from: int = -1  # 단계를 건너뛰며 전진하기 직전 단계 (원래 지역으로 돌아오면 되돌린다)
    ascendancy: list[str] = field(default_factory=list)  # 찍은 전직 노드 ID (로그의 전직 패시브 줄)
    # 엔드게임 기록 (endgame.py): 지도·최종 보스 판, 보스별 도전/처치/사망, 지금 있는 판
    eg_maps: list[dict] = field(default_factory=list)
    eg_bosses: dict[str, dict] = field(default_factory=dict)
    eg_cur: str = ""
    eg_since: str = ""
    campaign_done: str = ""  # 캠페인을 끝낸(엔드게임에 처음 들어간) 로그 시각

    @property
    def ascension(self) -> int:
        """전직 단계 (0 = 전직 전, 1~4차)."""
        return ascension_stage(self.ascendancy)

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
    in_step_zone: bool = False  # 캐릭터가 현재 단계 지역(또는 그 하위 지역)에 있는지
    roam_flags: dict = field(default_factory=dict)  # 단계 밖 보스 지역(지난 액트 다시 가기 등)의 전투 상태
    roam_boss: str = ""


class Tracker:
    def __init__(self, guide: Guide, characters: Optional[dict[str, Character]] = None,
                 current: Optional[str] = None, encounters: Optional[Encounters] = None):
        self.guide = guide
        self.encounters = encounters or Encounters()
        self.scene_lang = ""  # 마지막 지역 이름으로 본 게임 언어 ("ko"/"en")
        self.endgame = endgame.EndgameBosses({})  # 최종 보스 지역 (app 이 넣어 준다)
        self.passive_sources: list = []  # rewards.PassiveSource: 퀘스트 패시브를 주는 단계 (app 이 넣어 준다)
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
        self._dead_here = False  # 이 지역에서 죽음: 지역을 다시 들어올 때까지 보스 대사로 전투를 다시 잡지 않는다
        # 가이드 단계 밖의 보스 지역 (막간 캐릭터로 액트 4 보스 다시 잡기 등): 지역을 옮기면 버리는 임시 상태
        self._roam_key: tuple[str, str] = ("", "")
        self._roam_flags: dict = {}
        self._pending_play = 0.0  # 미확정 동안 쌓인 플레이 시간
        self.new_char_session = False  # 튜토리얼 줄로 '새 캐릭터'가 확정된 세션
        self.relog = False  # 게임을 끄지 않고 캐릭터 선택에 다녀온 세션
        for c in self.chars.values():
            c.league = league_for_mode(c.league, c.mode)
            self._repair_cursor(c)
            self._repair_flags(c)

    # ---------------------------------------------------------------- 이벤트
    def feed(self, ev: Event) -> None:
        new_pid = self.pid is not None and ev.pid != self.pid
        self._account_time(ev, reset=new_pid or isinstance(ev, LoginConnect))
        if new_pid:
            self._new_session()
            self.relog = False  # 게임 재시작: 다른 캐릭터일 수 있다
        self.pid = ev.pid

        if isinstance(ev, LoginConnect):
            self._new_session()
            self.relog = not new_pid
        elif isinstance(ev, AreaEntered):
            self._dead_here = False
            self._on_area(ev)
        elif isinstance(ev, SceneName):
            self._on_scene(ev)
        elif isinstance(ev, LevelUp):
            if c := self._identify(ev.name, ev.ts):
                c.cls, c.level = ev.cls, ev.level
        elif isinstance(ev, Death):
            if c := self._identify(ev.name, ev.ts):
                c.deaths += 1
                endgame.death(c)
                self._dead_here = True  # 사망 직후 보스의 승리 대사(타바카이: 무로 돌아가라)로 전투 중이 되살아나지 않게
                f = self._flags(c)
                if f is not None and f.get("boss") == "engaged":
                    f["boss"] = "died"
                if f is not None:
                    for k, v in f.get("sub", {}).items():
                        if v == "engaged":
                            f["sub"][k] = "died"
                # 하드코어 캐릭터는 죽으면 일반 리그로 옮겨진다
                c.mode = HC_DEATH.get(c.mode, c.mode)
                if c.league.startswith("HC "):
                    c.league = c.league[3:]
        elif isinstance(ev, Reward):
            if c := (self._identify(ev.name, ev.ts) if ev.name else self._active()):
                c.rewards.append(ev.text)
                # 보스가 떨군 퀘스트 아이템 사용(검은턱 → 화염 저항) = 전투가 끝났다
                f = self._flags(c)
                if f is not None and f.get("boss") == "engaged":
                    f["boss"] = "killed"
        elif isinstance(ev, NpcLine):
            self._on_npc(ev)
        elif isinstance(ev, NewCharacter):
            self._on_new_character()
        elif isinstance(ev, Afk):
            self.afk = ev.on
        elif isinstance(ev, AscendancyNode):
            if c := self._active():
                if ev.allocated and ev.node not in c.ascendancy:
                    c.ascendancy.append(ev.node)
                elif not ev.allocated and ev.node in c.ascendancy:
                    c.ascendancy.remove(ev.node)
                # 클래스 이름은 게임 언어대로 (지금 이름에 한글이 있으면 한국어 클라이언트)
                names = ASCENDANCY_KO if re.search("[가-힣]", c.cls) else ASCENDANCY_EN
                if ev.allocated and (name := names.get(ev.asc)):
                    c.cls = name
        elif isinstance(ev, PassivePoints):
            if c := self._active():
                if ev.weapon_set:
                    c.weapon_set_points += ev.points
                else:
                    c.passive_points += ev.points
                    if (i := self._passive_step(c)) is not None:  # 🎁 퀘스트 패시브 → ✓ 받음
                        self._step_flag(c, i)["passive"] = True
                    self._book_kill(c)

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

    def _passive_step(self, c: Character) -> Optional[int]:
        """퀘스트 패시브를 받은 단계: 패시브를 주는 단계(passive_sources) 중 아직 안 받은 것.
        1) 지금 지역의 출처 (사냥터에서 바로 쓴 책, 마을 NPC 보상)
        2) 마을에서 썼으면 직전에 있던 사냥터의 출처 (은빛 주먹을 늦게 잡고 마을에서 책 사용 등)
        여러 개면 현재 단계에서 가까운 것. 못 찾으면 현재 단계가 출처일 때만 그 단계."""
        steps = self.guide.steps
        if not steps:
            return None

        def cands(zone: str) -> list[int]:
            return [i for i, st in enumerate(steps)
                    if st.zone == zone and any(src.on(st.zone, st.text) for src in self.passive_sources)
                    and not c.step_flags.get(str(i), {}).get("passive")]

        found = cands(c.zone) or (cands(c.last_field_zone) if is_town(c.zone) and c.last_field_zone else [])
        if found:
            return min(found, key=lambda i: abs(i - c.cursor))
        if 0 <= c.cursor < len(steps) and any(src.on(steps[c.cursor].zone, steps[c.cursor].text)
                                               for src in self.passive_sources):
            return c.cursor
        return None

    def _flags(self, c: Character) -> Optional[dict]:
        """현재 가이드 단계의 상태 (캐릭터가 그 단계 지역에 있을 때). 단계 밖 보스 지역이면 임시 상태."""
        zone = self._step_zone(c)
        if zone is not None:
            return self._step_flag(c, c.cursor)
        return self._roam(c)

    def _step_flag(self, c: Character, i: int) -> dict:
        """i 번째 단계의 상태 (그 단계의 지역도 함께 적어 둔다)."""
        c.flag_zones[str(i)] = self.guide.steps[i].zone
        return c.step_flags.setdefault(str(i), {})

    def _step_zone(self, c: Character) -> Optional[str]:
        """캐릭터가 현재 단계 지역(또는 하위 지역)에 있으면 그 단계 지역 코드."""
        steps = self.guide.steps
        if not steps or not (0 <= c.cursor < len(steps)):
            return None
        zone = steps[c.cursor].zone
        if zone != c.zone and not self._subzone(zone, c.zone):
            return None
        return zone

    def _roam(self, c: Character) -> Optional[dict]:
        if not c.zone or not self.encounters.get(c.zone):
            return None
        key = (c.name, c.zone)
        if self._roam_key != key:
            self._roam_key, self._roam_flags = key, {}
        return self._roam_flags

    def _subzone(self, step_zone: str, zone: str):
        enc = self.encounters.get(step_zone)
        return enc.subzones.get(zone.lower()) if enc else None

    def _book_kill(self, c: Character) -> None:
        """보스가 떨구는 특화의 서를 그 지역에서 쓰면 처치로 본다."""
        enc = self.encounters.get(c.zone)
        f = self._flags(c)
        if not enc or not enc.book_kill or f is None or f.get("boss") == "killed":
            return
        if enc.book_kill == "any" or f.get("boss") == "engaged":
            f["boss"] = "killed"

    def _on_npc(self, ev: NpcLine) -> None:
        c = self._active()
        if c:
            endgame.npc(c, ev.who, ev.text, self.endgame)
        f = self._flags(c) if c else None
        if f is None:
            return
        step_zone = self._step_zone(c) or c.zone
        if sub := self._subzone(step_zone, c.zone):  # 하위 지역 보스 (집정관의 능묘 등)
            if ev.who == sub.boss:
                f.setdefault("sub", {})[sub.label] = "engaged"
                f["last_line"] = ev.ts
            return
        enc = self.encounters.get(c.zone)
        if not enc:
            return
        if self._dead_here:
            return
        if ev.who in enc.bosses:
            f["last_line"] = ev.ts  # 마지막 보스 대사 시각 (조용해지면 일반 패널로)
        engaged = f.get("boss") == "engaged"
        killed = f.get("boss") == "killed"
        for m in enc.markers:
            if ev.who == m.speaker and m.text in ev.text:
                if m.task:  # 할 일 체크 (보스 전투와 별개)
                    done = f.setdefault("tasks", [])
                    if m.task not in done:
                        done.append(m.task)
                    if not engaged:  # 할 일 진행을 표시: "시험 2/3 (카옴 · 마아타)"
                        f["marker"] = f"{enc.task_label} {len(done)}/{len(enc.tasks)} ({' · '.join(done)})"
                    return
                if killed and (m.phase or m.engage or m.soon or m.kill):
                    return  # 처치 뒤 대화(지오너: 광기가...)로 전투·페이즈 표시가 되살아나지 않게
                if m.soon:  # 곧 보스 등장
                    f["soon"] = True
                if m.kill:  # 처치 대사: 지역을 떠나기 전에 바로 처치
                    f["boss"] = "killed"
                    return
                if m.label and (not engaged or m.phase):  # 전투 중 다시 나온 진행 대사로 표시를 되돌리지 않는다
                    f["marker"] = m.label
                if m.engage or (m.phase and ev.who in enc.bosses):
                    f["boss"] = "engaged"
                return  # 보스가 말한 진행 대사(의식 등)는 전투로 보지 않는다
        if f.get("boss") != "killed" and (ev.who in enc.bosses or (f.get("soon") and ev.who in enc.engage_after_soon)):
            f["boss"] = "engaged"

    def _on_new_character(self) -> None:
        """새 캐릭터 확정 (이름은 아직 모름). 이번 세션의 지역 이동을 새 캐릭터에 다시 적용한다."""
        if self.confirmed or self.manual_lock:
            return
        self.new_char_session = True
        old = self.provisional
        if old is not None and old.name == NEW_CHAR:
            return
        nc = Character(name=NEW_CHAR, league=self.league, mode=old.mode if old and old.name in PLACEHOLDERS else "",
                       mode_prompt=old.mode_prompt if old and old.name == NEW_CHAR else True)
        for p in self.pending:
            self._apply_area(nc, p.code, p.level, p.ts, p.seed)
        nc.play_seconds = self._pending_play
        self.provisional = nc

    def _on_area(self, ev: AreaEntered) -> None:
        if self.confirmed and self.current:
            self._apply_area(self.chars[self.current], ev.code, ev.level, ev.ts, ev.seed)
            return
        self.pending.append(ev)
        self.provisional = self._guess()
        if self.provisional:
            self._apply_area(self.provisional, ev.code, ev.level, ev.ts, ev.seed)

    def _on_scene(self, ev: SceneName) -> None:
        self.scene_lang = i18n.scene_lang(ev.name)  # 게임 언어 (한글 지역 이름 = 한국어 클라이언트)
        if c := self._active():
            endgame.scene(c, ev.name)
            if c.zone and not c.area_name:
                c.area_name = ev.name

    def _apply_area(self, c: Character, code: str, level: int, ts: str, seed: str = "") -> None:
        endgame.enter(c, code, seed, ts, self.endgame)
        prev_zone = c.zone
        if prev_zone and not is_town(prev_zone):
            c.last_field_zone = prev_zone  # 마을에서 퀘스트 보상(책)을 쓰면 직전 사냥터의 보상으로 본다
        c.zone = code.lower()
        c.area_name = self.guide.area_name(code) or ""
        c.area_level = level
        c.last_seen = ts
        act = zone_act(code)
        # 구간은 그 액트의 사냥터에 처음 들어갈 때 시작 (막간 마을은 서로 오갈 수 있어 들르기만 해도 시작되면 안 된다).
        # 단, 지구라트 피난처는 캠페인을 끝내야 갈 수 있으니 들어가면 바로 캠페인 끝 (가이드의 '캠페인 완료!'와 맞춘다)
        endgame_town = code.lower() == "g_endgame_town"
        if act and act not in c.splits and (not is_town(code) or endgame_town):
            c.splits[act] = c.play_seconds
            if act == "엔드게임" and not c.campaign_done:
                c.campaign_done = ts
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
        enc_cur = self.encounters.get(cur.zone) if cur else None
        if (cur and enc_cur and enc_cur.silent and flags.get("soon") and not flags.get("boss")
                and code.lower() != cur.zone):
            flags["boss"] = "killed"  # 말 없는 보스: 곧 보스 신호 뒤 지역을 떠남 = 처치
        if cur and (sub := self._subzone(cur.zone, prev_zone)) and code.lower() != prev_zone:
            subs = flags.get("sub", {})
            if subs.get(sub.label) == "engaged":
                subs[sub.label] = "killed"
        jf = c.jump_from
        if 0 <= jf < c.cursor and steps[jf].zone == code.lower():
            # 단계를 건너뛰어 앞 지역에 들어갔다가(거점만 찍기 등) 원래 지역으로 돌아옴 → 원래 단계로
            c.jump_from = -1
            c.cursor, c.cursor_zone = jf, steps[jf].zone
            return
        new = self.guide.next_position(c.cursor, code)
        if new is not None and cur and cur.is_town and new == c.cursor - 1:
            prev_flags = c.step_flags.get(str(new), {})
            if prev_flags.get("boss") == "killed":
                new = None  # 보스를 이미 잡은 단계로는 되돌리지 않는다 (마을 갔다가 다시 들른 경우)
        if new is not None and cur and new == c.cursor + 1 and steps[new].is_town:
            enc = self.encounters.get(cur.zone)
            if enc and enc.bosses and enc.gate and flags.get("boss") != "killed":
                new = None  # 보스 처치 전 마을 방문(정비)은 단계를 넘기지 않는다
        if new is None and (back := self._interlude_back(c, code)) is not None:
            # 막간 안에서 순서를 바꿔 갔다가(갈라이 문·키마 먼저) 건너뛴 지역으로 돌아옴 → 건너뛴 단계로
            c.jump_from = -1
            c.cursor, c.cursor_zone = back, steps[back].zone
            return
        if new is not None:
            skipped = any(not steps[k].is_town for k in range(c.cursor + 1, new))
            keep = c.jump_from >= 0 and self._same_interlude(steps[c.jump_from].zone, steps[new].zone)
            if skipped:
                c.jump_from = min(c.jump_from, c.cursor) if keep else c.cursor
            elif not keep:
                c.jump_from = -1  # 막간 안에서는 막간이 끝날 때까지 건너뛴 위치를 기억한다
            c.cursor = new
            c.cursor_zone = self.guide.steps[new].zone

    @staticmethod
    def _same_interlude(a: str, b: str) -> bool:
        la = act_label(a)
        return la.startswith("막간") and la == act_label(b)

    def _interlude_back(self, c: Character, code: str) -> Optional[int]:
        """막간에서 건너뛴 단계 중 지금 들어간 사냥터의 첫 단계 (이미 잡은 보스 단계는 빼고)."""
        steps, z, jf = self.guide.steps, code.lower(), c.jump_from
        if is_town(z) or not 0 <= jf < c.cursor or not self._same_interlude(steps[jf].zone, z):
            return None
        for k in range(jf, c.cursor):
            if steps[k].zone == z and c.step_flags.get(str(k), {}).get("boss") != "killed":
                return k
        return None

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
        if c is None and self.provisional is not None and self.provisional.name == NEW_CHAR:
            # 새 캐릭터 임시본을 그대로 이어받는다 (보스 전투 기록, 플레이 시간, 모드 선택 등 유지)
            c = self.provisional
            c.name = name
            self.chars[name] = c
            replay = []
        elif c is None:
            c = Character(name=name, mode_prompt=self.new_char_session)
            self.chars[name] = c
            replay = self.pending
        elif self.provisional is not None and self.provisional.name == name:
            c = self.chars[name] = self.provisional  # 추정이 맞았으므로 추정본을 그대로 채택
            replay = []
        else:
            replay = self.pending
        for p in replay:
            self._apply_area(c, p.code, p.level, p.ts, p.seed)
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
            nc = Character(name=NEW_CHAR, league=self.league, mode_prompt=True)
            return nc
        best, best_score = None, -1
        cands = [c for c in self.chars.values()
                 if not (self.league and c.league and c.league != self.league)]
        for c in sorted(cands, key=lambda c: c.last_seen, reverse=True):
            score = self._match_score(c, codes)
            if score > 0 and self.relog and c.name == self.current:
                score += 4  # 같은 게임 실행에서 캐릭터 선택에 다녀온 경우(맵 초기화 등)는 대부분 같은 캐릭터
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
        for code, level, ts, *seed in pending:
            self._on_area(AreaEntered(ts, self.pid or "", code, int(level), seed[0] if seed else ""))
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
            self._repair_flags(c)

    def _repair_flags(self, c: Character) -> None:
        """가이드가 바뀌어 단계 번호가 밀렸으면 단계 상태(처치·패시브 등)를 같은 지역의 가장 가까운 단계로 옮긴다."""
        steps = self.guide.steps
        if not steps or not c.step_flags:
            return
        flags: dict[str, dict] = {}
        zones: dict[str, str] = {}
        for key in sorted(c.step_flags, key=lambda k: int(k) if k.lstrip("-").isdigit() else 0):
            if not key.lstrip("-").isdigit():
                continue
            i, v = int(key), c.step_flags[key]
            z = c.flag_zones.get(key)
            if z is None:  # 예전 저장본: 저장할 때의 가이드와 같다고 본다
                if not 0 <= i < len(steps):
                    continue
                z = steps[i].zone
            if 0 <= i < len(steps) and steps[i].zone == z:
                j = i
            else:
                cands = [s.index for s in steps if s.zone == z]
                if not cands:
                    continue  # 그 지역이 가이드에서 빠졌다
                j = min(cands, key=lambda x: (abs(x - i), x < i))  # 같으면 뒤쪽 (단계를 넣으면 뒤로 밀린다)
            k = str(j)
            flags[k] = {**flags.get(k, {}), **v}
            zones[k] = z
        c.step_flags, c.flag_zones = flags, zones

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
        off = bool(c.zone) and c.zone != step.zone and not self._subzone(step.zone, c.zone) and not (
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
            in_step_zone=c.zone == step.zone or bool(self._subzone(step.zone, c.zone)),
            roam_flags=dict(self._roam_flags) if self._roam_key == (c.name, c.zone) else {},
            roam_boss=self.encounters.boss_name(c.zone) if self._roam_key == (c.name, c.zone) else "",
        )
