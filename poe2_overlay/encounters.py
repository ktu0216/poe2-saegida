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
    task: str = ""  # 지역 안의 할 일 하나 완료 (히네코라의 눈 시험 3개 등) → "시험 2/3"


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
    task_label: str = "할 일"  # 할 일 체크 표시 이름 ("시험 2/3")
    gate: bool = True  # 보스 처치 전 마을 방문은 단계를 넘기지 않음. 로그로 확인 안 된 보스(말을 안 할 수 있음)는 false

    @property
    def tasks(self) -> list[str]:
        return list(dict.fromkeys(m.task for m in self.markers if m.task))


@dataclass
class Encounters:
    zones: dict[str, ZoneEncounter] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "Encounters":
        d = json.loads(path.read_text(encoding="utf-8"))
        zones = {}
        for code, z in d.get("zones", {}).items():
            if code.startswith("_"):  # 설명 메모
                continue
            zones[code.lower()] = ZoneEncounter(
                tuple(z.get("bosses", [])),
                tuple(Marker(m["speaker"], m["text"], m["label"], bool(m.get("engage")), bool(m.get("phase")),
                             bool(m.get("kill")), bool(m.get("soon")), m.get("task", "")) for m in z.get("markers", [])),
                {k.lower(): SubZone(v["boss"], v["label"]) for k, v in z.get("subzones", {}).items()},
                tuple(z.get("engage_after_soon", [])), z.get("book_kill", ""), z.get("label", ""),
                bool(z.get("silent")), z.get("task_label", "할 일"), bool(z.get("gate", True)))
        return cls(zones)

    def get(self, zone: str) -> Optional[ZoneEncounter]:
        return self.zones.get(zone.lower())

    display: Optional["Encounters"] = None  # 화면 언어 이름표 (게임 로그 언어와 다를 때)

    def boss_name(self, zone: str) -> str:
        if self.display is not None and (name := self.display.boss_name(zone)):
            return name
        z = self.get(zone)
        if not z:
            return ""
        return z.label or (z.bosses[0] if z.bosses else "")
