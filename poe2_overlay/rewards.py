"""캠페인 영구 보상 체크리스트. 캐릭터가 로그에서 받은 보상 문구로 자동 체크한다."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Slot:
    act: str
    zone: str
    source: str
    options: tuple[tuple[str, ...], ...]

    @property
    def label(self) -> str:
        return " 또는 ".join(", ".join(o) for o in self.options)


@dataclass
class SlotState:
    slot: Slot
    got: list[str]  # 이 칸에 배정된 실제 받은 문구

    @property
    def done(self) -> bool:
        return bool(self.got)


@dataclass(frozen=True)
class PassiveSource:
    """퀘스트 패시브(+2)를 주는 곳. match 가 있으면 그 말이 들어간 단계에만 표시한다."""
    zone: str
    match: str
    label: str

    def on(self, zone: str, text: str) -> bool:
        return zone == self.zone and (not self.match or self.match in text)


def load_passive_sources(path: Path) -> list[PassiveSource]:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [PassiveSource(s["zone"].lower(), s.get("match", ""), s["label"]) for s in d.get("sources", [])]


class RewardTable:
    def __init__(self, slots: list[Slot], quest_passive_total: int):
        self.slots = slots
        self.quest_passive_total = quest_passive_total

    @classmethod
    def load(cls, path: Path) -> "RewardTable":
        d = json.loads(path.read_text(encoding="utf-8"))
        slots = [Slot(s["act"], s["zone"].lower(), s["source"],
                      tuple(tuple(o) for o in s["options"])) for s in d["slots"]]
        return cls(slots, int(d.get("quest_passive_total", 0)))

    def evaluate(self, received: list[str]) -> list[SlotState]:
        """받은 순서대로 아직 비어 있는 칸 중 문구가 맞는 첫 칸에 배정한다.
        같은 보상이 두 번 나오는 경우(정신력 +30)는 앞 칸부터 채워진다.
        여러 줄짜리 선택지(저항 3종)는 같은 칸에 이어서 모은다."""
        states = [SlotState(s, []) for s in self.slots]
        for text in received:
            target = None
            for st in states:  # 이미 시작된 여러 줄 선택지를 먼저 채운다
                if st.got and any(text in o and st.got[0] in o and text not in st.got
                                  for o in st.slot.options):
                    target = st
                    break
            if target is None:
                target = next((st for st in states if not st.got
                               and any(text in o for o in st.slot.options)), None)
            if target is not None:
                target.got.append(text)
        return states
