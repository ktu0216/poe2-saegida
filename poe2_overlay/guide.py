"""액트 가이드(네비게이션) 데이터와 진행 위치 계산.

가이드 CSV 형식 (레임의 PoE Act Guide act_guide_*.csv 와 호환):
    id,area_name,quest
    g1_1,강둑,불어터진 방어꾼 처치
'#' 으로 시작하는 줄과 빈 줄은 무시한다.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Step:
    index: int
    zone: str  # 소문자 지역 코드 (g1_2)
    area: str  # 지역 이름 (클리어펠)
    text: str  # 할 일

    @property
    def is_town(self) -> bool:
        return is_town(self.zone)

    @property
    def act(self) -> str:
        return act_label(self.zone)


def is_town(zone: str) -> bool:
    return zone.lower().endswith("_town")


_ACT = re.compile(r"^([gp])(\d+)_")


def act_label(zone: str) -> str:
    m = _ACT.match(zone.lower())
    if not m:
        return "엔드게임" if "endgame" in zone.lower() else ""
    kind, num = m.groups()
    return f"액트 {num}" if kind == "g" else f"막간 {num}"


class Guide:
    def __init__(self, steps: list[Step], source: str):
        self.steps = steps
        self.source = source

    def __len__(self) -> int:
        return len(self.steps)

    @classmethod
    def load(cls, path: Path) -> "Guide":
        raw = path.read_bytes()
        for enc in ("utf-8-sig", "cp949"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
        return cls(parse_csv(text), str(path))

    def contains(self, zone: str) -> bool:
        z = zone.lower()
        return any(s.zone == z for s in self.steps)

    def area_name(self, zone: str) -> Optional[str]:
        z = zone.lower()
        for s in self.steps:
            if s.zone == z:
                return s.area
        return None

    def next_position(self, cursor: int, zone: str) -> Optional[int]:
        """지역 진입 시 새 커서 위치. 움직이지 않아야 하면 None.

        - 현재 단계 지역이면 그대로.
        - 마을은 바로 다음 단계일 때만 전진 (정비하러 잠깐 들른 경우를 무시).
        - 그 외 지역은 앞쪽에서 처음 나오는 같은 지역으로 전진 (건너뛴 단계 허용).
        - 뒤로는 돌아가지 않는다. 단, 마을 단계에서 직전 지역으로 되돌아가면
          (보스 전에 포탈로 마을에 다녀온 경우) 한 단계 되돌린다.
        """
        z = zone.lower()
        if not self.steps:
            return None
        cursor = max(0, min(cursor, len(self.steps) - 1))
        if self.steps[cursor].zone == z:
            return None
        if self.steps[cursor].is_town and cursor + 1 < len(self.steps) and self.steps[cursor + 1].zone == z:
            return cursor + 1  # 마을 일을 마치고 다음 지역으로 (직전 지역과 같아도: 키메랄 습지대 → 마을 → 키메랄 습지대)
        if self.steps[cursor].is_town and cursor > 0 and self.steps[cursor - 1].zone == z:
            return cursor - 1
        if is_town(z):
            nxt = cursor + 1
            if nxt < len(self.steps) and self.steps[nxt].zone == z:
                return nxt
            return None
        for j in range(cursor + 1, len(self.steps)):
            if self.steps[j].zone == z:
                # 이미 지나온 지역에 되돌아간 경우(붉은 계곡 → 그렐우드), 그 지역의 다음 방문이
                # 아직 안 거친 마을 단계 뒤에 있으면 건너뛰지 않는다.
                revisit = any(s.zone == z for s in self.steps[:cursor])
                town_between = any(self.steps[k].is_town for k in range(cursor + 1, j))
                if revisit and town_between:
                    return None
                return j
        return None

    def first_index(self, zone: str) -> Optional[int]:
        z = zone.lower()
        for s in self.steps:
            if s.zone == z:
                return s.index
        return None


def parse_csv(text: str) -> list[Step]:
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    steps: list[Step] = []
    for row in csv.reader(io.StringIO("\n".join(lines))):
        if len(row) < 2:
            continue
        zone = row[0].strip().lower()
        if not zone or zone == "id":
            continue
        area = row[1].strip()
        body = ",".join(row[2:]).strip()
        steps.append(Step(len(steps), zone, area, body))
    return steps
