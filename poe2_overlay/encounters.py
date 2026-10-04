"""지역별 보스/진행 대사 데이터 (guides/encounters_ko.json)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Marker:
    speaker: str
    text: str
    label: str
    engage: bool = False  # 이 대사부터 보스 전투 시작
    phase: bool = False  # 전투 중 진행 표시 (2페이즈 등)
    kill: bool = False  # 보스 처치 대사
    soon: bool = False  # 곧 보스 등장


@dataclass(frozen=True)
class SubZone:
    boss: str
    label: str


@dataclass
class ZoneEncounter:
    bosses: tuple[str, ...] = ()
    markers: tuple[Marker, ...] = ()
    subzones: dict[str, SubZone] = field(default_factory=dict)  # 하위 지역 코드 -> 보스
    engage_after_soon: tuple[str, ...] = ()  # 곧 보스 신호 뒤에는 전투로 보는 화자
    book_kill: str = ""  # 특화의 서 사용 = 처치: "engaged"(전투 중일 때만) / "any"
    label: str = ""  # 표시용 보스 이름 (대사 없는 보스)
    silent: bool = False  # 보스가 말하지 않음: "곧 보스" 뒤에 지역을 떠나면 처치로 본다 (지코아틀 등)


@dataclass
class Encounters:
    zones: dict[str, ZoneEncounter] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "Encounters":
        d = json.loads(path.read_text(encoding="utf-8"))
        zones = {}
        for code, z in d.get("zones", {}).items():
            zones[code.lower()] = ZoneEncounter(
                tuple(z.get("bosses", [])),
                tuple(Marker(m["speaker"], m["text"], m["label"], bool(m.get("engage")), bool(m.get("phase")),
                             bool(m.get("kill")), bool(m.get("soon"))) for m in z.get("markers", [])),
                {k.lower(): SubZone(v["boss"], v["label"]) for k, v in z.get("subzones", {}).items()},
                tuple(z.get("engage_after_soon", [])), z.get("book_kill", ""), z.get("label", ""),
                bool(z.get("silent")))
        return cls(zones)

    def get(self, zone: str) -> Optional[ZoneEncounter]:
        return self.zones.get(zone.lower())

    def boss_name(self, zone: str) -> str:
        z = self.get(zone)
        if not z:
            return ""
        return z.label or (z.bosses[0] if z.bosses else "")
