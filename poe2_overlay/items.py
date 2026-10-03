"""게임에서 Ctrl+C 로 복사한 아이템 텍스트를 분석하고, 장착 아이템과 비교한다.

한국어 클라이언트 예:
    아이템 종류: 쇠뇌
    아이템 희귀도: 마법
    서리 내린 팽팽한 석궁 - 스킬
    --------
    물리 피해: 8-15
    냉기 피해: 3-5 (cold)
    치명타 명중 확률: 5.00%
    초당 공격 횟수: 1.68 (augmented)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

HEADERS = ("아이템 종류:", "Item Class:")
ELEMENTS = ("화염", "냉기", "번개")

_RANGE = re.compile(r"^(물리|화염|냉기|번개|혼돈) 피해: (\d+)-(\d+)")
_NUM = re.compile(r"^([^:{]+): ([\d.]+)")
_RES = re.compile(r"(?:\+(\d+)% (화염|냉기|번개|혼돈|모든 원소) 저항|(화염|냉기|번개|혼돈|모든 원소) 저항 \+(\d+)%)")
_LIFE = re.compile(r"(?:\+(\d+) 최대 생명력|최대 생명력 \+(\d+))")
_MOVE = re.compile(r"이동 속도 (\d+)% 증가")
# 장신구 등: 공격 시 피해 추가 (무기 공격에 더해진다)
_ADDED = re.compile(r"공격 시 (물리|화염|냉기|번개|혼돈) 피해 (\d+)~(\d+) 추가")
# 옵션 수치 뒤의 등급 범위 표기 제거: "화염 저항 +7(6-10)%" -> "화염 저항 +7%"
_ROLL = re.compile(r"\(\d+(?:\.\d+)?-\d+(?:\.\d+)?\)")


@dataclass
class Item:
    item_class: str
    rarity: str = ""
    name: str = ""
    damage: dict[str, tuple[int, int]] = field(default_factory=dict)  # 물리/화염/냉기/번개/혼돈
    crit: float = 0.0
    aps: float = 0.0
    armour: int = 0
    evasion: int = 0
    energy_shield: int = 0
    life: int = 0
    move_speed: int = 0
    res: dict[str, int] = field(default_factory=dict)
    added: dict[str, tuple[int, int]] = field(default_factory=dict)  # 공격 시 피해 추가 (장신구 등)
    item_level: int = 0

    @property
    def is_weapon(self) -> bool:
        return self.aps > 0

    @property
    def slot(self) -> str:
        """비교 기준 부위. 무기는 종류가 달라도 서로 비교한다."""
        return "무기" if self.is_weapon else self.item_class

    def avg(self, kind: str) -> float:
        lo, hi = self.damage.get(kind, (0, 0))
        return (lo + hi) / 2

    @property
    def phys_dps(self) -> float:
        return self.avg("물리") * self.aps

    @property
    def ele_dps(self) -> float:
        return sum(self.avg(k) for k in ELEMENTS) * self.aps

    @property
    def dps(self) -> float:
        return sum(self.avg(k) for k in self.damage) * self.aps

    @property
    def added_avg(self) -> float:
        return sum((lo + hi) / 2 for lo, hi in self.added.values())

    @property
    def res_total(self) -> int:
        total = 0
        for k, v in self.res.items():
            total += v * 3 if k == "모든 원소" else v
        return total


def is_gear(item: "Item") -> bool:
    """장착 장비인지: 젬(미가공 포함)·화폐·지도 등은 장비 비교·장착 기준에서 뺀다."""
    if "젬" in item.item_class or "gem" in item.item_class.lower():
        return False
    return item.rarity not in ("화폐", "Currency")


def is_item_text(text: str) -> bool:
    return text.lstrip().startswith(HEADERS)


def parse_item(text: str) -> Optional[Item]:
    if not is_item_text(text):
        return None
    lines = [ln.strip() for ln in text.strip().splitlines()]
    item = Item(item_class=lines[0].split(":", 1)[1].strip())
    header = []
    for ln in lines[1:]:
        if ln.startswith("--------"):
            break
        if ln.startswith("아이템 희귀도:") or ln.startswith("Rarity:"):
            item.rarity = ln.split(":", 1)[1].strip()
        else:
            header.append(ln)
    item.name = " / ".join(header)
    for ln in lines:
        if m := _RANGE.match(ln):
            item.damage[m[1]] = (int(m[2]), int(m[3]))
            continue
        if m := _NUM.match(ln):
            key, val = m[1].strip(), float(m[2])
            if key == "치명타 명중 확률":
                item.crit = val
            elif key == "초당 공격 횟수":
                item.aps = val
            elif key == "방어도":
                item.armour = int(val)
            elif key in ("회피", "회피력"):
                item.evasion = int(val)
            elif key == "에너지 보호막":
                item.energy_shield = int(val)
            elif key == "아이템 레벨":
                item.item_level = int(val)
            continue
        if ln.startswith("{"):
            continue  # 옵션 등급 설명 줄
        ln = _ROLL.sub("", ln)
        if not item.is_weapon and (m := _ADDED.search(ln)):  # 무기의 같은 문구는 이미 피해 줄에 포함
            lo, hi = item.added.get(m[1], (0, 0))
            item.added[m[1]] = (lo + int(m[2]), hi + int(m[3]))
        for m in _RES.finditer(ln):
            kind = m[2] or m[3]
            item.res[kind] = item.res.get(kind, 0) + int(m[1] or m[4])
        if m := _LIFE.search(ln):
            item.life += int(m[1] or m[2])
        if m := _MOVE.search(ln):
            item.move_speed += int(m[1])
    return item


SLOT_COUNT = {"반지": 2}  # 같은 종류를 두 개 끼는 부위


def slot_keys(slot: str) -> list[str]:
    """저장 키: 반지 -> ["반지", "반지#2"]."""
    n = SLOT_COUNT.get(slot, 1)
    return [slot] + [f"{slot}#{k}" for k in range(2, n + 1)]


def defense_score(it: Item) -> float:
    """방어구·장신구 비교 점수 (compare 의 판정과 같은 가중치)."""
    return (it.life + it.res_total + it.move_speed + it.added_avg) * 2 + \
        (it.armour + it.evasion + it.energy_shield) / 10


def _pct(new: float, old: float) -> str:
    if old <= 0:
        return ""
    return f" ({(new - old) / old * 100:+.0f}%)"


def compare(new: Item, old: Optional[Item]) -> tuple[str, list[str], int]:
    """(제목, 변화 목록, 판정 +1 좋음 / -1 나쁨 / 0 비슷·기준 없음)."""
    if new.is_weapon:
        title = f"DPS {new.dps:.1f}"
        if old is None or not old.is_weapon:
            return title, [], 0
        title = f"DPS {old.dps:.1f} → {new.dps:.1f}{_pct(new.dps, old.dps)}"
        diffs = []
        for label, a, b, fmt in (("물리", old.phys_dps, new.phys_dps, "{:+.1f}"),
                                 ("원소", old.ele_dps, new.ele_dps, "{:+.1f}"),
                                 ("공속", old.aps, new.aps, "{:+.2f}"),
                                 ("치명", old.crit, new.crit, "{:+.2f}%")):
            if abs(b - a) > 1e-6:
                diffs.append(f"{label} {fmt.format(b - a)}")
        verdict = 1 if new.dps > old.dps * 1.02 else (-1 if new.dps < old.dps * 0.98 else 0)
        return title, diffs, verdict

    def rows(it: Item):
        return {"방어도": it.armour, "회피": it.evasion, "에너지 보호막": it.energy_shield,
                "생명력": it.life, "저항 합": it.res_total, "이동 속도": it.move_speed,
                "공격 추가 피해": round(it.added_avg, 1)}

    cur = rows(new)
    if old is None:
        parts = [f"{k} {v}" for k, v in cur.items() if v]
        return " · ".join(parts) or new.item_class, [], 0
    prev = rows(old)
    diffs = [f"{k} {cur[k] - prev[k]:+g}" for k in cur if cur[k] != prev[k]]
    score = sum(cur[k] - prev[k] for k in ("생명력", "저항 합", "이동 속도", "공격 추가 피해")) * 2 + \
        sum(cur[k] - prev[k] for k in ("방어도", "회피", "에너지 보호막")) / 10
    verdict = 1 if score > 2 else (-1 if score < -2 else 0)
    return new.item_class, diffs, verdict
