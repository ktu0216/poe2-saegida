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


@dataclass
class ZoneEncounter:
    bosses: tuple[str, ...] = ()
    markers: tuple[Marker, ...] = ()


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
                tuple(Marker(m["speaker"], m["text"], m["label"]) for m in z.get("markers", [])))
        return cls(zones)

    def get(self, zone: str) -> Optional[ZoneEncounter]:
        return self.zones.get(zone.lower())

    def boss_name(self, zone: str) -> str:
        z = self.get(zone)
        return z.bosses[0] if z and z.bosses else ""
