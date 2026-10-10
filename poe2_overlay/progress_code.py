"""PC 를 옮겨 다닐 때(PC방 등) 진행 기록 옮기기.

- 진행 코드: 캐릭터 하나의 기록을 텍스트 한 줄로 (클립보드 → 카톡 나에게 보내기 등에 붙여 두고 다른 PC 에서 붙여넣기)
- 이전 보상 채우기: 기록 없이 중간부터 잡힌 캐릭터는 지나온 단계의 영구 보상·퀘스트 패시브를 받았다고 표시
서버·계정 없이 사용자 손으로만 옮긴다 (기록이 밖으로 나가지 않는다).
"""
from __future__ import annotations

import base64
import json
import zlib
from typing import Optional

from .tracker import Character

PREFIX = "SAEGIDA1:"


def encode(c: Character, build: str = "") -> str:
    """캐릭터 기록 → 진행 코드 (압축 + base64, 한 줄)."""
    d = {"char": c.to_dict(), "build": build}
    raw = json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return PREFIX + base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode("ascii")


def decode(text: str) -> tuple[Character, str]:
    """진행 코드 → (캐릭터, 연결된 빌드 이름). 코드가 아니면 ValueError."""
    s = "".join(text.split())  # 메신저에 붙였다가 복사하면 줄바꿈·공백이 섞일 수 있다
    i = s.find(PREFIX)
    if i < 0:
        raise ValueError("no code")
    try:
        raw = zlib.decompress(base64.urlsafe_b64decode(s[i + len(PREFIX):] + "=="))
        d = json.loads(raw.decode("utf-8"))
        c = Character.from_dict(d["char"])
    except (ValueError, KeyError, TypeError, zlib.error) as e:
        raise ValueError("broken code") from e
    if not c.name:
        raise ValueError("broken code")
    return c, str(d.get("build") or "")


def merge(imported: Character, local: Optional[Character]) -> Character:
    """가져온 기록을 기준으로, 이 PC 에서 코드를 붙이기 전에 이미 한 플레이(기록 없이 중간부터 잡힌 캐릭터)를 이어 붙인다.
    이 PC 의 기록이 원래 있던 온전한 기록이면 이어 붙이지 않는다 (가져온 기록으로 바꾼다)."""
    c = Character.from_dict(imported.to_dict())
    c.partial_ack = True
    if local is None or not local.partial_from or local.last_seen <= imported.last_seen:
        return c
    base = c.play_seconds
    c.play_seconds += local.play_seconds
    for act, at in local.splits.items():
        c.splits.setdefault(act, base + at)
    c.rewards += local.rewards
    c.passive_points += local.passive_points
    c.weapon_set_points += local.weapon_set_points
    c.deaths += local.deaths
    for k, f in local.step_flags.items():
        c.step_flags.setdefault(k, {}).update(f)
    c.flag_zones.update(local.flag_zones)
    c.gear.update(local.gear)
    c.ascendancy += [a for a in local.ascendancy if a not in c.ascendancy]
    c.level = max(c.level, local.level)
    if local.cursor > c.cursor:
        c.cursor, c.cursor_zone = local.cursor, local.cursor_zone
    for attr in ("zone", "area_name", "area_level", "last_seen", "last_field_zone", "cls", "league"):
        if getattr(local, attr):
            setattr(c, attr, getattr(local, attr))
    return c


def fill_previous(c: Character, steps, slots, passive_sources, done: frozenset = frozenset()) -> tuple[int, int]:
    """지나온 단계(현재 단계 앞)의 영구 보상 칸과 퀘스트 패시브를 받았다고 표시한다. (보상 칸 수, 패시브 포인트) 를 돌려준다.
    택1 보상은 무엇을 골랐는지 모르니 칸만 채운다. done: 이미 받은(로그로 확인된) 보상 칸 번호."""
    before = steps[:max(0, c.cursor)]
    zones = {s.zone for s in before}
    n_slots = 0
    for i, slot in enumerate(slots):
        if slot.zone in zones and i not in c.assumed_slots and i not in done:
            c.assumed_slots.append(i)
            n_slots += 1
    points = 0
    for s in before:
        if any(src.on(s.zone, s.text) for src in passive_sources):
            f = c.step_flags.setdefault(str(s.index), {})
            c.flag_zones[str(s.index)] = s.zone
            if not f.get("passive"):
                f["passive"] = True
                points += 2
    c.passive_points += points
    c.weapon_set_points += points
    c.partial_ack = True
    return n_slots, points
