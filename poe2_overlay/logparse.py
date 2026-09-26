"""POE2 Client.txt / KakaoClient.txt 한 줄을 이벤트로 변환한다.

한국어(카카오) 클라이언트 기준 문구를 우선 지원하고, 영문 클라이언트 문구도 함께 인식한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Union

# 2026/09/26 22:57:03 947613015 2caa229f [DEBUG Client 26920] 본문
_PREFIX = re.compile(
    r"^(?P<date>\d{4}/\d{2}/\d{2}) (?P<time>\d{2}:\d{2}:\d{2}) \d+ \w+ \[(?P<lvl>\w+) Client (?P<pid>\d+)\] (?P<body>.*)$"
)

_AREA = re.compile(r'^Generating level (?P<level>\d+) area "(?P<code>[^"]+)"')
_SCENE = re.compile(r"^\[SCENE\] Set Source \[(?P<name>[^\]]*)\]")
_LOGIN = re.compile(r"^Async connecting to .*login", re.IGNORECASE)

# 채팅/시스템 메시지는 "본문"이 ": " 로 시작한다.
_LEVEL_KO = re.compile(r"^: (?P<name>\S+)\((?P<cls>[^)]+)\) 님이 (?P<level>\d+)레벨이 되었습니다\.")
_LEVEL_EN = re.compile(r"^: (?P<name>\S+) \((?P<cls>[^)]+)\) is now level (?P<level>\d+)")
_DEATH_KO = re.compile(r"^: (?P<name>\S+) 님이 사망했습니다\.")
_DEATH_EN = re.compile(r"^: (?P<name>\S+) has been slain\.")
_REWARD_KO = re.compile(r"^: (?P<name>\S+) 님이 (?P<text>.+?)을\(를\) 획득했습니다\.")
_REWARD_EN = re.compile(r"^: (?P<name>\S+) has received (?P<text>.+?)\.$")
_PASSIVE_KO = re.compile(r"^: (?:(?P<weapon>무기 세트 )?패시브 스킬 포인트(?:를)? ?(?P<n>\d+)(?:포인트를)? ?획득했습니다\.)")
_PASSIVE_EN = re.compile(r"^: You have received (?P<n>\d+) (?P<weapon>Weapon Set )?Passive Skill Points?", re.IGNORECASE)

# [Resistances|냉기] -> 냉기
_MARKUP = re.compile(r"\[(?:[^\[\]|]*\|)?([^\[\]]*)\]")


def strip_markup(text: str) -> str:
    return _MARKUP.sub(r"\1", text)


@dataclass(frozen=True)
class AreaEntered:
    ts: str
    pid: str
    code: str
    level: int


@dataclass(frozen=True)
class SceneName:
    ts: str
    pid: str
    name: str


@dataclass(frozen=True)
class LevelUp:
    ts: str
    pid: str
    name: str
    cls: str
    level: int


@dataclass(frozen=True)
class Death:
    ts: str
    pid: str
    name: str


@dataclass(frozen=True)
class Reward:
    ts: str
    pid: str
    name: str
    text: str


@dataclass(frozen=True)
class PassivePoints:
    ts: str
    pid: str
    points: int
    weapon_set: bool


@dataclass(frozen=True)
class LoginConnect:
    ts: str
    pid: str


Event = Union[AreaEntered, SceneName, LevelUp, Death, Reward, PassivePoints, LoginConnect]

# 빠른 사전 필터: 이 문자열이 하나도 없으면 정규식을 돌리지 않는다.
_HINTS = ("Generating level", "[SCENE]", "] : ", "Async connecting")


def parse_line(line: str) -> Optional[Event]:
    if not any(h in line for h in _HINTS):
        return None
    m = _PREFIX.match(line.rstrip("\r\n"))
    if not m:
        return None
    ts = f"{m['date']} {m['time']}"
    pid = m["pid"]
    body = m["body"]

    if a := _AREA.match(body):
        return AreaEntered(ts, pid, a["code"], int(a["level"]))
    if s := _SCENE.match(body):
        name = s["name"]
        if name in ("(null)", "(unknown)", ""):
            return None
        return SceneName(ts, pid, name)
    if _LOGIN.match(body):
        return LoginConnect(ts, pid)
    if not body.startswith(": "):
        return None
    for rx in (_LEVEL_KO, _LEVEL_EN):
        if lv := rx.match(body):
            return LevelUp(ts, pid, lv["name"], lv["cls"], int(lv["level"]))
    for rx in (_DEATH_KO, _DEATH_EN):
        if d := rx.match(body):
            return Death(ts, pid, d["name"])
    for rx in (_PASSIVE_KO, _PASSIVE_EN):
        if p := rx.match(body):
            return PassivePoints(ts, pid, int(p["n"]), bool(p["weapon"]))
    for rx in (_REWARD_KO, _REWARD_EN):
        if r := rx.match(body):
            return Reward(ts, pid, r["name"], strip_markup(r["text"]))
    return None
