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

from .i18n import t

HEADERS = ("아이템 종류:", "Item Class:")
ELEMENTS = ("화염", "냉기", "번개")

_RANGE = re.compile(r"^(물리|화염|냉기|번개|혼돈|Physical|Fire|Cold|Lightning|Chaos) (?:피해|Damage): (\d+)-(\d+)")
# 영어 클라이언트 → 내부 키(한국어)
_EN_KIND = {"Physical": "물리", "Fire": "화염", "Cold": "냉기", "Lightning": "번개", "Chaos": "혼돈",
            "all Elemental": "모든 원소", "Elemental": "모든 원소"}
_NUM = re.compile(r"^([^:{]+): ([\d.]+)")
# "모든 소환수 스킬 레벨 +1", "+1 to Level of all Minion Skills" (셉터·투구·목걸이 등)
_SKILL_LV = re.compile(r"모든 (.+?) 스킬 레벨 \+(\d+)|\+(\d+) to Level of all (.+?) Skills")
_RES = re.compile(r"(?:\+(\d+)% (화염|냉기|번개|혼돈|모든 원소) 저항|(화염|냉기|번개|혼돈|모든 원소) 저항 \+(\d+)%)")
_RES_EN = re.compile(r"\+(\d+)% to (Fire|Cold|Lightning|Chaos|all Elemental) Resistances?")
_LIFE = re.compile(r"(?:\+(\d+) 최대 생명력|(?:최대 생명력|생명력 최대치) \+(\d+)|^\+(\d+) to maximum Life$)")  # 게임 문구는 "생명력 최대치 +29"
_MOVE = re.compile(r"이동 속도 (\d+)% 증가|(\d+)% increased Movement Speed")
_SPIRIT_MOD = re.compile(r"^정신력 \+(\d+)$|^\+(\d+) to Spirit$")  # 목걸이 고정 옵션 등 (셉터는 속성 줄 "정신력: N")
# 장신구 등: 공격 시 피해 추가 (무기 공격에 더해진다)
_ADDED = re.compile(r"공격 시 (물리|화염|냉기|번개|혼돈) 피해 (\d+)~(\d+) 추가")
_ADDED_EN = re.compile(r"Adds (\d+) to (\d+) (Physical|Fire|Cold|Lightning|Chaos) Damage to Attacks")
# 주문 무기·장신구: "주문 피해 42% 증가" / "42% increased Spell Damage" (치명타 주문 피해 보너스는 제외)
_INC = re.compile(r"^(주문|카오스|혼돈|화염|냉기|번개|원소) 피해 (\d+)% 증가$|^(\d+)% increased (Spell|Chaos|Fire|Cold|Lightning|Elemental) Damage$")
_INC_KIND = {"Spell": "주문", "Chaos": "카오스", "혼돈": "카오스", "Fire": "화염", "Cold": "냉기", "Lightning": "번개",
             "Elemental": "원소"}
_CAST = re.compile(r"^시전 속도 (\d+)% 증가$|^(\d+)% increased Cast Speed$")
# 옵션 수치 뒤의 등급 범위 표기 제거: "화염 저항 +7(6-10)%" -> "화염 저항 +7%"
_ROLL = re.compile(r"\(\d+(?:\.\d+)?-\d+(?:\.\d+)?\)")


# 손에 드는 아이템: 아이템 종류(한/영) → 한 손 / 양손 / 보조 손 전용 (poe2db 아이템 분류)
ONE_HAND = {"클로", "단검", "마법봉", "한손 검", "한손 도끼", "한손 철퇴", "셉터", "창", "도리깨",
            "Claws", "Daggers", "Wands", "One Hand Swords", "One Hand Axes", "One Hand Maces", "Sceptres", "Spears",
            "Flails"}
TWO_HAND = {"활", "지팡이", "양손 검", "양손 도끼", "양손 철퇴", "육척봉", "쇠뇌", "덫", "부적",
            "Bows", "Staves", "Two Hand Swords", "Two Hand Axes", "Two Hand Maces", "Quarterstaves", "Crossbows",
            "Traps", "Talismans"}
OFF_HAND = {"화살통", "방패", "버클러", "집중구", "Quivers", "Shields", "Bucklers", "Foci"}
MAIN, OFF = "주 손", "보조 손"  # 손 칸 (저장 키)
# 방어구·장신구 부위: 게임 언어와 상관없는 저장 키 (예전에는 종류 이름 그대로라 언어를 바꾸면 기준이 사라졌다)
_SLOT = {"갑옷": "갑옷", "Body Armours": "갑옷", "투구": "투구", "Helmets": "투구", "장갑": "장갑", "Gloves": "장갑",
         "장화": "장화", "Boots": "장화", "허리띠": "허리띠", "Belts": "허리띠", "목걸이": "목걸이", "Amulets": "목걸이",
         "반지": "반지", "Rings": "반지"}
# 장착 기준으로 쓰지 않는 종류: 퀘스트 아이템·플라스크·호신부·주얼
_NOT_GEAR = ("퀘스트", "Quest", "플라스크", "Flask", "호신부", "Charm", "주얼", "Jewel")


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
    spirit: int = 0  # 셉터 등의 정신력 (속성 줄 "정신력: 132")
    skill_levels: dict[str, int] = field(default_factory=dict)  # 소환수/투사체/주문 … → +N
    inc_damage: dict[str, int] = field(default_factory=dict)  # 주문/카오스/화염 … 피해 N% 증가
    cast_speed: int = 0

    @property
    def is_weapon(self) -> bool:
        return self.aps > 0

    @property
    def hand(self) -> str:
        """"one" 한 손 / "two" 양손 / "off" 보조 손 전용 / "" 손에 들지 않음."""
        c = self.item_class
        if c in ONE_HAND:
            return "one"
        if c in TWO_HAND:
            return "two"
        if c in OFF_HAND:
            return "off"
        return "two" if self.is_weapon else ""  # 모르는 공격 무기: 양손으로 본다

    @property
    def slot(self) -> str:
        """비교 기준 부위: 손에 드는 건 모두 "손" (무기·방패·집중구를 서로 비교), 나머지는 언어와 상관없는 부위 이름."""
        return "손" if self.hand else _SLOT.get(self.item_class, self.item_class)

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
    if any(w in item.item_class for w in _NOT_GEAR):
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
            item.damage[_EN_KIND.get(m[1], m[1])] = (int(m[2]), int(m[3]))
            continue
        if m := _NUM.match(ln):
            key, val = m[1].strip(), float(m[2])
            if key in ("치명타 명중 확률", "Critical Hit Chance"):
                item.crit = val
            elif key in ("초당 공격 횟수", "Attacks per Second"):
                item.aps = val
            elif key in ("방어도", "Armour"):
                item.armour = int(val)
            elif key in ("회피", "회피력", "Evasion Rating"):
                item.evasion = int(val)
            elif key in ("에너지 보호막", "Energy Shield"):
                item.energy_shield = int(val)
            elif key in ("아이템 레벨", "Item Level"):
                item.item_level = int(val)
            elif key in ("정신력", "Spirit"):
                item.spirit = int(val)
            continue
        if ln.startswith("{"):
            continue  # 옵션 등급 설명 줄
        ln = _ROLL.sub("", ln)
        if not item.is_weapon and (m := _ADDED.search(ln)):  # 무기의 같은 문구는 이미 피해 줄에 포함
            lo, hi = item.added.get(m[1], (0, 0))
            item.added[m[1]] = (lo + int(m[2]), hi + int(m[3]))
        if not item.is_weapon and (m := _ADDED_EN.search(ln)):
            kind = _EN_KIND[m[3]]
            lo, hi = item.added.get(kind, (0, 0))
            item.added[kind] = (lo + int(m[1]), hi + int(m[2]))
        for m in _RES.finditer(ln):
            kind = m[2] or m[3]
            item.res[kind] = item.res.get(kind, 0) + int(m[1] or m[4])
        for m in _RES_EN.finditer(ln):
            kind = _EN_KIND[m[2]]
            item.res[kind] = item.res.get(kind, 0) + int(m[1])
        if m := _LIFE.search(ln):
            item.life += int(m[1] or m[2] or m[3])
        if m := _MOVE.search(ln):
            item.move_speed += int(m[1] or m[2])
        if item.item_class not in ("셉터", "Sceptres", "Sceptre") and (m := _SPIRIT_MOD.match(ln)):
            item.spirit += int(m[1] or m[2])
        if m := _INC.match(ln):
            kind = m[1] or m[4]
            kind = _INC_KIND.get(kind, kind)
            item.inc_damage[kind] = item.inc_damage.get(kind, 0) + int(m[2] or m[3])
        if m := _CAST.match(ln):
            item.cast_speed += int(m[1] or m[2])
        for m in _SKILL_LV.finditer(ln):
            kind = (m[1] or m[4]).strip()
            item.skill_levels[kind] = item.skill_levels.get(kind, 0) + int(m[2] or m[3])
    return item


SLOT_COUNT = {"반지": 2, "Rings": 2, "Ring": 2}  # 같은 종류를 두 개 끼는 부위


def hand_keys(item: Item, gear: dict[str, str]) -> list[str]:
    """손 아이템을 놓을 수 있는 칸: 보조 손 전용 → 보조 손, 양손 → 주 손 (양손을 한 손에 드는 캐릭터면 두 칸), 한 손 → 두 칸."""
    if item.hand == "off":
        return [OFF]
    if item.hand == "two" and not giant_grip(gear):
        return [MAIN]
    return [MAIN, OFF]


def giant_grip(gear: dict[str, str]) -> bool:
    """양손 무기를 한 손에 드는 캐릭터인지 (거인의 피 등): 등록된 장비로 판단한다.
    양손 무기를 주 손에 등록하면 보조 손 기준을 비우므로, 양손 무기 + 보조 손이 함께 있거나 보조 손에 양손 무기가 있으면 그런 캐릭터다."""
    main, off = (parse_item(gear[k]) if k in gear else None for k in (MAIN, OFF))
    return off is not None and (off.hand == "two" or (main is not None and main.hand == "two"))


def weapon_score(it: Item) -> float:
    """손 칸 두 개 중 약한 쪽을 고를 때: 공격 무기는 DPS, 주문 무기는 주문 피해·스킬 레벨, 방패·집중구는 방어 점수."""
    if it.is_weapon:
        return it.dps
    return defense_score(it)


def hand_plan(new: Item, gear: dict[str, str]) -> tuple[list[str], list[tuple[str, dict]]]:
    """손 아이템 비교: (비교할 칸 목록 — 약한 쪽이 앞, 안내 [(문구, 값)]).
    무기는 무기끼리(방패·집중구와는 비교하지 않음), 보조 손 전용은 보조 손과. 양손 ↔ 한 손 + 보조 손 바뀜은 안내로 알린다."""
    keys = hand_keys(new, gear)
    main, off = (parse_item(gear[k]) if k in gear else None for k in (MAIN, OFF))
    giant = giant_grip(gear)
    notes: list[tuple[str, dict]] = []
    if new.hand == "off":
        cands = [OFF] if off is not None else []
        if main is not None and main.hand == "two" and not giant:
            notes.append(("양손 무기를 들고 있음 — 한 손 무기로 바꿔야 함께 들 수 있음", {}))
    else:
        cands = [k for k, it in ((MAIN, main), (OFF, off)) if k in keys and it is not None and it.hand != "off"]
        if new.hand == "two" and not giant and off is not None:
            title, _, _ = compare(off, None)
            notes.append(("양손 무기: 보조 손이 빠짐 ({name} · {stats})", {"name": off.item_class, "stats": title}))
        elif new.hand == "one" and main is not None and main.hand == "two" and not giant:
            notes.append(("한 손 무기: 보조 손에 방패·집중구를 함께 들 수 있음", {}))
    cands.sort(key=lambda k: weapon_score(parse_item(gear[k])))
    return cands, notes


def equip_key(item: Item, gear: dict[str, str], target: str = "") -> str:
    """장착 기준으로 등록할 칸. 손: 보조 손 전용 → 보조 손, 양손 → 주 손, 한 손 → 주 손
    (두 손에 무기를 들고 있으면 마지막으로 비교한 약한 쪽). 다른 칸에 꼈다면 한 번 더 등록해 옮긴다."""
    if not item.hand:
        keys = slot_keys(item.slot)
        empty = [k for k in keys if k not in gear]
        return empty[0] if empty else (target if target in keys else keys[0])
    keys = hand_keys(item, gear)
    if len(keys) == 1:
        return keys[0]
    off = parse_item(gear[OFF]) if OFF in gear else None
    if MAIN in gear and off is not None and off.hand != "off":  # 두 손에 무기
        return target if target in keys else MAIN
    return MAIN


def normalize_gear(gear: dict[str, str]) -> dict[str, str]:
    """예전 저장본(종류 이름 키, 무기 한 칸, 지팡이·스태프·셉터가 따로)을 손 칸 두 개·언어 무관 키로 옮긴다.
    무기(또는 보조 손 아이템)가 여럿 저장돼 있으면 어느 것을 들고 있는지 알 수 없으니 버린다 — 잘못된 기준보다
    다시 등록(두 번 복사)하는 편이 낫다. 하나뿐이면 그대로 옮긴다."""
    out: dict[str, str] = {}
    hands: list[Item] = []
    texts: dict[int, str] = {}
    for key, text in gear.items():
        it = parse_item(text)
        if it is None or not is_gear(it):
            continue
        if key in (MAIN, OFF):
            out[key] = text
            continue
        if it.hand:
            hands.append(it)
            texts[id(it)] = text
            continue
        slot = it.slot
        if slot == "반지" and (key.endswith("#2") or "반지" in out):
            slot = "반지#2"
        out.setdefault(slot, text)
    if hands and MAIN not in out and OFF not in out:
        weapons = [h for h in hands if h.hand != "off"]
        offs = [h for h in hands if h.hand == "off"]
        main = weapons[0] if len(weapons) == 1 else None
        if main is not None:
            out[MAIN] = texts[id(main)]
        if len(offs) == 1 and not (main is not None and main.hand == "two"):
            out[OFF] = texts[id(offs[0])]
    return out


def slot_label(key: str, keys: list[str]) -> str:
    """칸 이름 표시: 반지#2 → "반지 2", 칸이 둘인 반지 → "반지 1", 손 칸은 그대로."""
    if key in (MAIN, OFF):
        return key
    if "#" in key:
        return key.replace("#", " ")
    return f"{key} 1" if len(keys) > 1 else key


def slot_keys(slot: str) -> list[str]:
    """저장 키: 반지 -> ["반지", "반지#2"]."""
    n = SLOT_COUNT.get(slot, 1)
    return [slot] + [f"{slot}#{k}" for k in range(2, n + 1)]


def defense_score(it: Item) -> float:
    """방어구·장신구 비교 점수 (compare 의 판정과 같은 가중치)."""
    return (it.life + it.res_total * 3 + it.move_speed * 3 + it.added_avg * 2
            + (it.armour + it.evasion + it.energy_shield) / 10 + it.spirit / 2
            + sum(it.skill_levels.values()) * 30 + caster_score(it))


def caster_score(it: Item) -> float:
    """주문 피해·시전 속도: 주문 피해 증가 1% = 1점, 피해 종류별 증가는 빌드에 따라 달라 절반, 시전 속도 1% = 2점."""
    return (it.inc_damage.get("주문", 0) + sum(v for k, v in it.inc_damage.items() if k != "주문") / 2
            + it.cast_speed * 2)


def _pct(new: float, old: float) -> str:
    if old <= 0:
        return ""
    return f" ({(new - old) / old * 100:+.0f}%)"


def _label(key: str) -> str:
    """비교 줄 이름 (내부 키는 한국어) → 화면 언어."""
    if key.endswith(" 스킬 레벨"):
        return t("{kind} 스킬 레벨", kind=key[:-len(" 스킬 레벨")])
    if key.endswith(" 피해 증가"):
        kind = key[:-len(" 피해 증가")]
        en = {v: k for k, v in _INC_KIND.items() if k.isascii()}.get(kind, kind)
        return t("{kind} 피해 증가", kind=kind if t("시전 속도") == "시전 속도" else en)
    return t(key)


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
                diffs.append(f"{t(label)} {fmt.format(b - a)}")
        verdict = 1 if new.dps > old.dps * 1.02 else (-1 if new.dps < old.dps * 0.98 else 0)
        return title, diffs, verdict

    def rows(it: Item):
        r = {"방어도": it.armour, "회피": it.evasion, "에너지 보호막": it.energy_shield,
             "생명력": it.life, "저항 합": it.res_total, "이동 속도": it.move_speed,
             "공격 추가 피해": round(it.added_avg, 1), "정신력": it.spirit}
        for kind in set(new.skill_levels) | set(old.skill_levels if old else {}):
            r[f"{kind} 스킬 레벨"] = it.skill_levels.get(kind, 0)
        for kind in set(new.inc_damage) | set(old.inc_damage if old else {}):
            r[f"{kind} 피해 증가"] = it.inc_damage.get(kind, 0)
        r["시전 속도"] = it.cast_speed
        return r

    cur = rows(new)
    if old is None:
        parts = [f"{_label(k)} {v}" for k, v in cur.items() if v]
        return " · ".join(parts) or new.item_class, [], 0
    prev = rows(old)
    diffs = [f"{_label(k)} {cur[k] - prev[k]:+g}" for k in cur if cur[k] != prev[k]]
    # 액트 진행 기준 가중치: 저항 1% 는 생명력 3 정도로 본다 (하드코어·저항 미달 구간에서 저항이 더 귀함)
    score = ((cur["생명력"] - prev["생명력"])
             + (cur["저항 합"] - prev["저항 합"]) * 3
             + (cur["이동 속도"] - prev["이동 속도"]) * 3
             + (cur["공격 추가 피해"] - prev["공격 추가 피해"]) * 2
             + sum(cur[k] - prev[k] for k in ("방어도", "회피", "에너지 보호막")) / 10
             + (cur["정신력"] - prev["정신력"]) / 2
             + sum(cur[k] - prev[k] for k in cur if k.endswith("스킬 레벨")) * 30  # 스킬 레벨 +1 은 매우 큼
             + caster_score(new) - caster_score(old))
    verdict = 1 if score > 2 else (-1 if score < -2 else 0)
    return new.item_class, diffs, verdict
