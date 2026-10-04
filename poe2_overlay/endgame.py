"""엔드게임 기록: 지도 판 수·시간·사망, 최종 보스 도전/처치 (로그만으로).

판 하나 = 지역 코드 + 시드 (같은 판에 포탈로 다시 들어가도 한 판). 시간은 들어간 시각부터 나온 시각까지
(한 번에 MAX_STAY 넘게는 세지 않는다 — 자리 비움·로그 공백). 최종 보스 처치는 처치 뒤 NPC 대사가
확실한 보스만 센다 (guides/endgame_bosses_ko.json). 나머지는 도전·사망만.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

MAX_STAY = 30 * 60  # 한 번 머문 시간 상한 (초)
SESSION_GAP = 2 * 60 * 60  # 판 시작 사이가 이보다 벌어지면 다른 세션
MAX_RECORDS = 400


@dataclass(frozen=True)
class Boss:
    key: str
    label: str
    kill: tuple[tuple[str, str], ...] = ()  # (화자, 대사 일부): 처치 뒤 나오는 대사


class EndgameBosses:
    def __init__(self, bosses: dict[str, Boss]):
        self.bosses = bosses  # 지역 코드(소문자) -> 보스

    @classmethod
    def load(cls, path: Path) -> "EndgameBosses":
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls({})
        out = {}
        for code, b in d.get("zones", {}).items():
            if code.startswith("_"):
                continue
            out[code.lower()] = Boss(code.lower(), b["label"], tuple(tuple(k) for k in b.get("kill", [])))
        return cls(out)

    def get(self, code: str) -> Optional[Boss]:
        return self.bosses.get(code.lower())


def is_map(code: str) -> bool:
    return code.lower().startswith("map")


def _ts(ts: str) -> Optional[datetime]:
    try:
        return datetime.strptime(ts, "%Y/%m/%d %H:%M:%S")
    except ValueError:
        return None


def _stay(start: str, end: str) -> float:
    a, b = _ts(start), _ts(end)
    if a is None or b is None:
        return 0.0
    return max(0.0, min((b - a).total_seconds(), MAX_STAY))


def leave(c, ts: str) -> None:
    """지금 판에서 나옴: 머문 시간을 더한다."""
    if not c.eg_cur:
        return
    for r in reversed(c.eg_maps[-50:]):
        if r["key"] == c.eg_cur:
            r["secs"] += _stay(c.eg_since, ts)
            break
    c.eg_cur, c.eg_since = "", ""


def enter(c, code: str, seed: str, ts: str, bosses: EndgameBosses) -> None:
    """지역에 들어감: 지도·최종 보스 지역이면 판을 기록한다 (같은 판 재입장은 한 판)."""
    leave(c, ts)
    boss = bosses.get(code)
    if not (is_map(code) or boss):
        return
    key = f"{code.lower()}|{seed}"
    c.eg_cur, c.eg_since = key, ts
    if any(r["key"] == key for r in c.eg_maps[-50:]):
        return
    c.eg_maps.append({"key": key, "code": code.lower(), "name": "", "start": ts, "secs": 0.0,
                      "deaths": 0, "boss": boss.key if boss else "", "killed": False})
    del c.eg_maps[:-MAX_RECORDS]
    if boss:
        b = c.eg_bosses.setdefault(boss.key, {"tries": 0, "kills": 0, "deaths": 0})
        b["tries"] += 1


def _cur(c) -> Optional[dict]:
    if not c.eg_cur:
        return None
    return next((r for r in reversed(c.eg_maps[-50:]) if r["key"] == c.eg_cur), None)


def scene(c, name: str) -> None:
    if (r := _cur(c)) and not r["name"]:
        r["name"] = name


def death(c) -> None:
    if r := _cur(c):
        r["deaths"] += 1
        if r["boss"]:
            c.eg_bosses.setdefault(r["boss"], {"tries": 1, "kills": 0, "deaths": 0})["deaths"] += 1


def npc(c, who: str, text: str, bosses: EndgameBosses) -> None:
    r = _cur(c)
    if not r or not r["boss"] or r["killed"]:
        return
    boss = bosses.get(r["code"])
    if boss and any(who == s and t in text for s, t in boss.kill):
        r["killed"] = True
        c.eg_bosses.setdefault(boss.key, {"tries": 1, "kills": 0, "deaths": 0})["kills"] += 1


@dataclass
class Summary:
    maps: int  # 이번 세션 지도 판 수
    avg_secs: float
    deaths: int
    total_maps: int  # 이 캐릭터 누적
    cur_name: str  # 지금 있는 판 (지도/보스), 없으면 ""
    cur_secs: float  # 지금 판에 머문 시간 (이번 입장 포함)
    bosses: list[tuple[str, int, int, int, bool]]  # (이름, 도전, 처치, 사망, 처치를 셀 수 있는지)


def summary(c, bosses: EndgameBosses, now: Optional[datetime] = None) -> Optional[Summary]:
    recs = c.eg_maps
    if not recs:
        return None
    # 세션: 끝에서부터 판 시작 간격이 SESSION_GAP 이내로 이어진 구간
    sess = [recs[-1]]
    for r in reversed(recs[:-1]):
        a, b = _ts(r["start"]), _ts(sess[0]["start"])
        if a is None or b is None or (b - a).total_seconds() > SESSION_GAP:
            break
        sess.insert(0, r)
    last = _ts(recs[-1]["start"])
    if now and last and (now - last).total_seconds() > SESSION_GAP and not c.eg_cur:
        sess = []  # 마지막 판이 오래전: 이번 세션은 아직 없음
    maps = [r for r in sess if not r["boss"]]
    done = [r for r in maps if r["key"] != c.eg_cur]
    avg = sum(r["secs"] for r in done) / len(done) if done else 0.0
    cur = _cur(c)
    cur_secs = 0.0
    if cur:
        cur_secs = cur["secs"]
        if (t := _ts(c.eg_since)) and now:
            cur_secs += max(0.0, min((now - t).total_seconds(), MAX_STAY))
    blist = []
    for key, v in c.eg_bosses.items():
        b = bosses.get(key)
        blist.append((b.label if b else key, v["tries"], v["kills"], v["deaths"], bool(b and b.kill)))
    cur_name = ""
    if cur:
        b = bosses.get(cur["code"])
        cur_name = b.label if b else (cur["name"] or cur["code"])
    return Summary(len(maps), avg, sum(r["deaths"] for r in sess), sum(1 for r in recs if not r["boss"]),
                   cur_name, cur_secs, blist)
