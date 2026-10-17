"""거래소 시세 검색 (카카오 poe.kakaogames.com / 국제 www.pathofexile.com 의 trade2 API).

흐름: 게임에서 Ctrl+C 한 아이템 문구 → 검색 조건(build_query) → search 1번 + fetch 1번(매물 10개) → 요약.
화폐·룬·영혼 핵처럼 쌓이는 아이템은 교환소(exchange) 매물 수와 poe.ninja 시세(엑잘 기준)를 본다.
- 엑잘 환산은 poe.ninja (카카오 거래소도 같은 poe2 시장 — 귓속말이 여러 나라 말, 2026-10-17 확인).
  하드코어 교환소는 매물이 적고 미끼가 많아 교환소 중간값은 크게 틀렸다 (1 신성 = 11 엑잘). ninja 가 없을 때만 교환소.
- 요청은 사용자가 시세 키를 누르거나 조건을 바꿀 때만 (자동 반복 없음). 요청 제한은 응답 헤더(X-Rate-Limit-*)를 따르고,
  기다려야 하면 보내지 않고 "N초 후" 를 돌려준다 (Awakened PoE Trade 방식). 같은 검색은 5분, 환율은 30분 캐시.
- 옵션 문구 → 거래소 stat id 는 거래소 /data/stats 에서 만든다 (하드코딩 없음, 하루 캐시).
- 조건은 자동으로 완화하지 않는다: 사용자가 카드에서 켜고 끈다 (2026-10-17 사용자 결정).
계획·벤치마킹: notes/price-check-plan.md (저장소 밖)
"""
from __future__ import annotations

import json
import math
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import __version__
from .items import Item, parse_item

REALMS = {"kakao": "https://poe.kakaogames.com", "ggg": "https://www.pathofexile.com"}
UA = f"POE2-Saegida/{__version__} (github.com/ktu0216/poe2-saegida)"
DATA_KINDS = ("stats", "static", "filters", "items")
DATA_TTL = 24 * 3600
CACHE_TTL = 300  # 같은 검색 다시 보내지 않음 (APT 와 같은 5분)
RATE_TTL = 1800  # 화폐 → 엑잘 환율 (poe2tradesearch 와 같은 30분)
MAX_WAIT = 1.5  # 이보다 오래 기다려야 하면 보내지 않고 "N초 후" (요청이 쌓이지 않게)
MIN_RATIO = 0.9  # 옵션 최소값 = 지금 값의 90%
BASE_CURRENCY = "exalted"
NINJA = "https://poe.ninja/poe2/api/economy/exchange/current/overview"

# 아이템 종류(게임 문구) → 거래소 카테고리
CATEGORY = {
    "클로": "weapon.claw", "단검": "weapon.dagger", "한손 검": "weapon.onesword", "한손검": "weapon.onesword",
    "한손 도끼": "weapon.oneaxe", "한손 철퇴": "weapon.onemace", "창": "weapon.spear", "도리깨": "weapon.flail",
    "양손 검": "weapon.twosword", "양손검": "weapon.twosword", "양손 도끼": "weapon.twoaxe", "양손 철퇴": "weapon.twomace",
    "육척봉": "weapon.warstaff", "부적": "weapon.talisman", "활": "weapon.bow", "쇠뇌": "weapon.crossbow",
    "석궁": "weapon.crossbow", "마법봉": "weapon.wand", "셉터": "weapon.sceptre", "지팡이": "weapon.staff",
    "투구": "armour.helmet", "갑옷": "armour.chest", "장갑": "armour.gloves", "장화": "armour.boots", "신발": "armour.boots",
    "화살통": "armour.quiver", "방패": "armour.shield", "집중구": "armour.focus", "버클러": "armour.buckler",
    "목걸이": "accessory.amulet", "허리띠": "accessory.belt", "반지": "accessory.ring",
    "주얼": "jewel", "호신부": "flask.charm", "생명력 플라스크": "flask.life", "마나 플라스크": "flask.mana",
    "스킬 젬": "gem.activegem", "보조 젬": "gem.supportgem", "메타 젬": "gem.metagem",
    "경로석": "map.waystone", "서판": "map.tablet",
    "Claws": "weapon.claw", "Daggers": "weapon.dagger", "One Hand Swords": "weapon.onesword",
    "One Hand Axes": "weapon.oneaxe", "One Hand Maces": "weapon.onemace", "Spears": "weapon.spear",
    "Flails": "weapon.flail", "Two Hand Swords": "weapon.twosword", "Two Hand Axes": "weapon.twoaxe",
    "Two Hand Maces": "weapon.twomace", "Quarterstaves": "weapon.warstaff", "Talismans": "weapon.talisman",
    "Bows": "weapon.bow", "Crossbows": "weapon.crossbow", "Wands": "weapon.wand", "Sceptres": "weapon.sceptre",
    "Staves": "weapon.staff", "Helmets": "armour.helmet", "Body Armours": "armour.chest", "Gloves": "armour.gloves",
    "Boots": "armour.boots", "Quivers": "armour.quiver", "Shields": "armour.shield", "Foci": "armour.focus",
    "Bucklers": "armour.buckler", "Amulets": "accessory.amulet", "Belts": "accessory.belt", "Rings": "accessory.ring",
    "Jewels": "jewel", "Charms": "flask.charm", "Life Flasks": "flask.life", "Mana Flasks": "flask.mana",
    "Skill Gems": "gem.activegem", "Support Gems": "gem.supportgem", "Meta Gems": "gem.metagem",
    "Waystones": "map.waystone", "Tablet": "map.tablet", "Tablets": "map.tablet",
}
RARITY = {"일반": "normal", "마법": "magic", "희귀": "rare", "고유": "unique",
          "Normal": "normal", "Magic": "magic", "Rare": "rare", "Unique": "unique"}
# 옵션 줄 꼬리표 → 거래소 stat 묶음
TAGS = {"implicit": "implicit", "rune": "rune", "enchant": "enchant", "desecrated": "desecrated",
        "fractured": "fractured", "crafted": "crafted"}
# 짧은 화폐 이름 (거래소 static 의 긴 이름 대신)
CURRENCY_SHORT = {
    "ko": {"exalted": "엑잘", "divine": "신성", "chaos": "카오스", "regal": "제왕", "aug": "확장", "transmute": "진화",
           "alch": "연금", "vaal": "바알", "annul": "소멸", "mirror": "거울", "chance": "기회"},
    "en": {"exalted": "ex", "divine": "div", "chaos": "chaos", "regal": "regal", "aug": "aug", "transmute": "transmute",
           "alch": "alch", "vaal": "vaal", "annul": "annul", "mirror": "mirror", "chance": "chance"},
}
_NUM = re.compile(r"[+-]?\d+(?:\.\d+)?")
_RANGE = re.compile(r"(\d+(?:\.\d+)?)\((\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\)")  # 47(40-48): 값 47, 등급 40~48
_TAG = re.compile(r"\s*\((implicit|rune|enchant|desecrated|fractured|crafted)\)$")
_FIXED = re.compile(r"\s*—\s*(변경이 불가능한 값|Unscalable Value)$")
_LOCAL = re.compile(r"\s*\((특정|Local)\)$")
_REQ_LEVEL = re.compile(r"(?:레벨|Level)[: ]+(\d+)")
_PROP = re.compile(r"^([^:]+):\s*\+?(\d+(?:\.\d+)?)")  # "레벨: 20", "품질: +20%", "경로석 등급: 15"
_ARMOUR_LOCAL = ("방어도", "회피", "에너지 보호막", "막기", "Armour", "Evasion", "Energy Shield", "Block")
_GEM_LEVEL = ("레벨", "Level")
_QUALITY = ("품질", "Quality")
_TIER = ("경로석 등급", "Waystone Tier")
_ILVL = ("아이템 레벨", "Item Level")


def _skeleton(text: str) -> str:
    """숫자 자리를 # 로: "민첩 +12" → "민첩 #", "생명력 최대치 #" 그대로. 등급 범위는 먼저 지운다."""
    text = _RANGE.sub(r"\1", text)
    return _NUM.sub("#", text).strip()


@dataclass
class Stat:
    id: str
    text: str
    group: str  # explicit / implicit / rune / pseudo …
    local: bool = False
    slots: tuple[int, ...] = ()  # 숫자 자리 중 실제 값(#) 위치


@dataclass
class TradeData:
    stats: dict[tuple[str, str], list[Stat]] = field(default_factory=dict)  # (묶음, 뼈대) → 후보
    currency: dict[str, str] = field(default_factory=dict)  # id → 이름 (검색하는 거래소 언어)
    stack_ids: dict[str, str] = field(default_factory=dict)  # 아이템 이름 → 교환소 id (화폐·룬·영혼 핵 …)
    stack_group: dict[str, str] = field(default_factory=dict)  # 교환소 id → 묶음 (Currency / Runes … = poe.ninja type)
    bases: set[str] = field(default_factory=set)  # 베이스 이름 (매직 아이템 이름에서 찾기)
    translate: dict[str, str] = field(default_factory=dict)  # 문구 언어 이름 → 거래소 언어 이름 (영어 클라 + 카카오)

    @classmethod
    def from_json(cls, raw: dict[str, dict], text_raw: Optional[dict[str, dict]] = None) -> "TradeData":
        """raw: 검색하는 거래소의 데이터. text_raw: 아이템 문구 언어가 다르면 그 언어의 데이터 (id 는 같다)."""
        d = cls()
        src = text_raw or raw
        for g in src.get("stats", {}).get("result", []):
            group = g["id"]
            for e in g["entries"]:
                text = e["text"].split("\n")[0]
                local = bool(_LOCAL.search(text))
                plain = _LOCAL.sub("", text)
                toks = re.findall(r"#|[+-]?\d+(?:\.\d+)?", plain)
                st = Stat(e["id"], plain, group, local, tuple(i for i, tk in enumerate(toks) if tk == "#"))
                d.stats.setdefault((group, _skeleton(plain.replace("#", "0"))), []).append(st)
        for g in raw.get("static", {}).get("result", []):
            for e in g.get("entries", []):
                if e.get("id") and e.get("text"):
                    d.currency[e["id"]] = e["text"]
                    d.stack_group[e["id"]] = g["id"]
        for g in src.get("static", {}).get("result", []):
            for e in g.get("entries", []):
                if e.get("id") and e.get("text") and e["id"] != "sep":  # sep = 목록의 소제목 줄
                    d.stack_ids[e["text"]] = e["id"]
        for g in src.get("items", {}).get("result", []):
            for e in g.get("entries", []):
                if e.get("type"):
                    d.bases.add(e["type"])
        if text_raw:  # 같은 순서로 나오는 두 언어 목록을 맞대어 이름을 옮긴다
            mine = {g["id"]: g["entries"] for g in raw.get("items", {}).get("result", [])}
            for g in text_raw.get("items", {}).get("result", []):
                other = mine.get(g["id"], [])
                if len(other) != len(g["entries"]):
                    continue
                for a, b in zip(g["entries"], other):
                    for k in ("type", "name"):
                        if a.get(k) and b.get(k):
                            d.translate[a[k]] = b[k]
        return d

    @classmethod
    def load(cls, folder: Path, realm: str, text_lang: str = "",
             fetch: Optional[Callable[[str], bytes]] = None) -> "TradeData":
        """하루 지난 캐시는 다시 받는다. 받기에 실패하면 예전 캐시라도 쓴다.
        text_lang="en" 이고 카카오면 영어 문구용으로 국제 거래소 데이터도 받는다."""
        def get(r: str) -> dict:
            out = {}
            for kind in DATA_KINDS:
                path = folder / f"{r}_{kind}.json"
                fresh = path.exists() and time.time() - path.stat().st_mtime < DATA_TTL
                if not fresh:
                    try:
                        path.write_bytes((fetch or _http_get)(f"{REALMS[r]}/api/trade2/data/{kind}"))
                    except (OSError, urllib.error.URLError):
                        if not path.exists():
                            raise
                out[kind] = json.loads(path.read_text(encoding="utf-8"))
            return out
        folder.mkdir(parents=True, exist_ok=True)
        raw = get(realm)
        other = get("ggg") if realm == "kakao" and text_lang == "en" else None
        return cls.from_json(raw, other)

    def match(self, line: str, group: str, item_kind: str = "") -> Optional[tuple[list[Stat], list[float], Optional[float]]]:
        """옵션 한 줄 → (후보 stat, 값, 등급 최소). item_kind: weapon / armour / "" (장신구 등)."""
        cands = self.stats.get((group, _skeleton(line)))
        if not cands:
            return None
        nums = [float(n) for n in _NUM.findall(_RANGE.sub(r"\1", line))]
        tier = _RANGE.search(line)
        vals = [abs(nums[i]) for i in cands[0].slots if i < len(nums)]

        def ok(s: Stat) -> bool:  # 지역(특정) 옵션: 무기·방어구 자체에 붙은 것만 (장신구의 회피 +50 은 전역)
            if not s.local:
                return True
            return item_kind == ("armour" if any(k in s.text for k in _ARMOUR_LOCAL) else "weapon")
        locals_ = [s for s in cands if s.local and ok(s)]
        cands = locals_ or [s for s in cands if not s.local] or cands
        return cands, vals, float(tier[2]) if tier else None

    def name(self, text: str) -> str:
        return self.translate.get(text, text)


@dataclass
class Filter:
    key: str  # 화면·저장용 이름
    label: str
    kind: str  # stat / equip / req / type(베이스) / typef(type_filters) / misc / map
    ids: tuple[str, ...] = ()  # stat 후보 (둘 이상이면 count 묶음)
    min: Optional[float] = None
    max: Optional[float] = None
    enabled: bool = True
    unit: str = ""  # 화면 표시용 ("%")
    text: str = ""  # type 필터: 거래소에 보낼 베이스 이름


@dataclass
class Query:
    item_class: str
    rarity: str
    name: str
    base: str
    category: str = ""
    filters: list[Filter] = field(default_factory=list)
    status: str = "securable"  # securable = 즉시 구매, available = 즉시 구매 + 직접 거래
    indexed: str = "1week"  # "" = 기간 상관없음
    unsupported: str = ""  # 비어 있지 않으면 검색하지 않는 이유
    exchange: str = ""  # 화폐 등: 교환소 id (이때는 search 대신 교환소)
    exchange_group: str = "Currency"  # poe.ninja type
    trade_name: str = ""  # 거래소 언어의 이름 (고유)
    trade_base: str = ""

    def body(self) -> dict:
        q: dict = {"status": {"option": self.status}, "stats": [{"type": "and", "filters": []}], "filters": {}}
        f = q["filters"]
        if self.rarity == "unique":
            q["name"], q["type"] = self.trade_name or self.name, self.trade_base or self.base
        type_f = {}
        if self.category:
            type_f["category"] = {"option": self.category}
        if self.rarity:
            type_f["rarity"] = {"option": "unique" if self.rarity == "unique" else "nonunique"}
        trade = {"collapse": {"option": "true"}}
        if self.indexed:
            trade["indexed"] = {"option": self.indexed}
        f["trade_filters"] = {"filters": trade}
        for flt in self.filters:
            if not flt.enabled:
                continue
            val = {k: v for k, v in (("min", flt.min), ("max", flt.max)) if v is not None}
            if flt.kind == "stat":
                if len(flt.ids) == 1:
                    q["stats"][0]["filters"].append({"id": flt.ids[0], "value": val})
                else:  # 같은 문구가 여러 id (지역·전역 구분 없는 옵션): 하나만 맞으면 된다
                    q["stats"].append({"type": "count", "value": {"min": 1},
                                       "filters": [{"id": i, "value": val} for i in flt.ids]})
            elif flt.kind == "type":
                q["type"] = flt.text
            elif flt.kind == "typef":
                type_f[flt.key] = val
            else:
                group = {"equip": "equipment_filters", "req": "req_filters", "misc": "misc_filters",
                         "map": "map_filters"}[flt.kind]
                f.setdefault(group, {"filters": {}})["filters"][flt.key] = val
        f["type_filters"] = {"filters": type_f}
        return {"query": q, "sort": {"price": "asc"}}


def _floor(v: float) -> float:
    return float(math.floor(v * MIN_RATIO * 10) / 10) if v < 10 else float(math.floor(v * MIN_RATIO))


def _base_of(header: list[str], rarity: str, bases: set[str]) -> tuple[str, str]:
    """(이름, 베이스). 희귀·고유는 두 줄, 일반은 베이스 한 줄, 매직은 접사가 붙은 한 줄에서 베이스를 찾는다."""
    if len(header) >= 2:
        return header[0], header[-1]
    line = header[0] if header else ""
    if rarity == "magic":
        found = [b for b in bases if b in line]
        if found:
            return line, max(found, key=len)
    return line, line


def _props(lines: list[str]) -> dict[str, float]:
    """속성 줄 "키: 숫자" (레벨·품질·경로석 등급·아이템 레벨 …). 첫 값만."""
    out: dict[str, float] = {}
    for ln in lines:
        if m := _PROP.match(ln):
            out.setdefault(m[1].strip(), float(m[2]))
    return out


def _prop(props: dict[str, float], keys: tuple[str, ...]) -> Optional[float]:
    return next((props[k] for k in keys if k in props), None)


def build_query(text: str, data: TradeData, char_level: int = 0, profile: str = "") -> Query:
    """아이템 문구 → 검색 조건. 주요 옵션만 켜고(생명력·저항 합·이동 속도·능력치 합·스킬 레벨·DPS), 나머지는 꺼 둔다."""
    lines = [ln.strip() for ln in text.strip().splitlines()]
    cls = lines[0].split(":", 1)[1].strip() if lines and ":" in lines[0] else ""
    rarity_txt, header = "", []
    for ln in lines[1:]:
        if ln.startswith("--------"):
            break
        if ln.startswith(("아이템 희귀도:", "Rarity:")):
            rarity_txt = ln.split(":", 1)[1].strip()
        else:
            header.append(ln)
    rarity = RARITY.get(rarity_txt, "")
    name, base = _base_of(header, rarity, data.bases)
    q = Query(cls, rarity, name, base, CATEGORY.get(cls, ""))
    q.trade_name, q.trade_base = data.name(name), data.name(base)
    props = _props(lines)
    if name in data.stack_ids and not q.category.startswith(("gem", "map", "jewel", "flask")):
        q.exchange = data.stack_ids[name]  # 화폐·룬·영혼 핵·징조 …: 교환소
        q.exchange_group = data.stack_group.get(q.exchange, "Currency")
        q.rarity = ""
        return q
    if q.category.startswith("gem"):  # 젬: 이름 + 젬 레벨 + 품질
        q.rarity = ""
        q.filters.append(Filter("type", name, "type", text=q.trade_name))
        if (lv := _prop(props, _GEM_LEVEL)) is not None:
            q.filters.append(Filter("gem_level", "젬 레벨", "misc", min=lv))
        if (ql := _prop(props, _QUALITY)):
            q.filters.append(Filter("quality", "품질", "typef", min=ql, unit="%"))
        return q
    item = parse_item(text)
    if item is None or not q.category:
        q.unsupported = "아직 이 종류는 시세를 찾지 못합니다"
        return q
    unique = rarity == "unique"  # 고유: 이름으로 찾고 옵션은 사용자가 켤 때만
    if q.category.startswith("map"):  # 경로석·서판: 등급 + 옵션
        if (tier := _prop(props, _TIER)) is not None:
            q.filters.append(Filter("map_tier", "등급", "map", min=tier))
        if q.category == "map.tablet" and not unique:
            q.filters.append(Filter("type", base, "type", text=q.trade_base))
        _add_mod_filters(q, lines, data, item, "", profile, auto=False)
        return q
    kind = "weapon" if item.is_weapon else ("armour" if q.category.startswith("armour") else "")
    plain = rarity in ("normal", "magic")  # 제작 베이스: 베이스 이름 (일반은 아이템 레벨까지)
    if plain:
        q.filters.append(Filter("type", base, "type", text=q.trade_base))
        if (ilvl := _prop(props, _ILVL)) is not None:
            q.filters.append(Filter("ilvl", "아이템 레벨", "typef", min=ilvl, enabled=rarity == "normal"))
    if item.is_weapon and not unique:
        dps_on = rarity != "normal"  # 일반 무기는 베이스가 곧 DPS
        if item.ele_dps > 0:
            q.filters.append(Filter("dps", "DPS", "equip", min=_floor(item.dps), enabled=dps_on))
        else:
            q.filters.append(Filter("pdps", "물리 DPS", "equip", min=_floor(item.phys_dps), enabled=dps_on))
    pseudo = (("pseudo.pseudo_total_life", "생명력 합", item.life, ""),
              ("pseudo.pseudo_total_resistance", "저항 합", item.res_total, "%"),
              ("pseudo.pseudo_increased_movement_speed", "이동 속도", item.move_speed, "%"),
              ("pseudo.pseudo_total_attributes", "능력치 합", item.attributes, ""))
    for sid, label, v, unit in pseudo:
        if v > 0:
            q.filters.append(Filter(sid, label, "stat", (sid,), _floor(v), enabled=not unique, unit=unit))
    _add_mod_filters(q, lines, data, item, kind, profile, auto=not unique)
    req = next((m for ln in lines if ln.startswith(("요구 사항", "Requires")) and (m := _REQ_LEVEL.search(ln))), None)
    if char_level and not unique:  # 레벨링: 지금 낄 수 있는 것만
        q.filters.append(Filter("lvl", "착용 레벨", "req", max=float(max(char_level, int(req[1]) if req else 0))))
    return q


# pseudo(합계) 로 이미 찾는 옵션: 생명력·저항·이동 속도·능력치
_PSEUDO_COVERED = re.compile(
    r"^(생명력 최대치 #|최대 생명력 #|.*저항 #%|이동 속도 #% 증가|힘 #|민첩 #|지능 #|모든 능력치 #|.* 및 .* #)$"
    r"|^(# to maximum Life|.*Resistances?|#% increased Movement Speed|# to (Strength|Dexterity|Intelligence|all Attributes)"
    r"|# to .* and .*)$")
# 자동으로 켜는 옵션 (pseudo 로 못 잡는 것): 스킬 레벨, 속도, 치명
_AUTO_ON = re.compile(r"스킬 레벨|Level of all|시전 속도|Cast Speed|공격 속도|Attack Speed|치명타|Critical|정신력|Spirit")
_WEAPON_DPS = re.compile(r"피해 #~# 추가|Adds # to # .*Damage|공격 속도|Attack Speed|치명타 확률|Critical Hit Chance")


def _add_mod_filters(q: Query, lines: list[str], data: TradeData, item: Item, kind: str, profile: str,
                     auto: bool) -> None:
    for ln in lines:
        if not ln or ln.startswith(("{", "--------")):
            continue
        tag = _TAG.search(ln)
        group = TAGS[tag[1]] if tag else "explicit"
        body = _FIXED.sub("", _TAG.sub("", ln))
        hit = data.match(body, group, kind)
        if not hit:  # 머리말·속성 줄·설명 문구 등
            continue
        stats, vals, tier = hit
        sk = _skeleton(body)
        on = auto and bool(_AUTO_ON.search(body)) and not _PSEUDO_COVERED.match(sk)
        if item.is_weapon and _WEAPON_DPS.search(sk):
            on = False  # 무기 자체의 피해·속도·치명은 DPS 필터에 이미 들어 있다
        if profile == "attack" and re.search(r"시전 속도|Cast Speed|주문|Spell", body):
            on = False
        if profile == "caster" and re.search(r"공격 속도|Attack Speed", body):
            on = False
        val = sum(vals) / len(vals) if vals else None
        # 고유는 굴림 범위가 있으면 "범위 아래쪽" 대신 지금 굴림 그대로를 최소로 (좋은 굴림 시세 보기)
        low = (val if q.rarity == "unique" else _floor(val)) if val else None
        q.filters.append(Filter(stats[0].id, _RANGE.sub(r"\1", body), "stat", tuple(s.id for s in stats),
                                low, enabled=on))


# ---------------------------------------------------------------- 요청 제한
@dataclass
class _Limit:
    max: int
    window: float
    hits: list[float] = field(default_factory=list)


class RateLimiter:
    """서버 헤더의 규칙(최대:기간:차단)을 따른다. 규칙을 알기 전에는 5초에 1번 (APT 기본값)."""

    def __init__(self) -> None:
        self.policies: dict[str, list[_Limit]] = {}
        self.blocked_until = 0.0

    def _limits(self, policy: str) -> list[_Limit]:
        return self.policies.setdefault(policy, [_Limit(1, 5.0)])

    def wait_time(self, policy: str, now: Optional[float] = None) -> float:
        now = time.monotonic() if now is None else now
        wait = max(0.0, self.blocked_until - now)
        for lim in self._limits(policy):
            lim.hits = [h for h in lim.hits if now - h < lim.window]
            if len(lim.hits) >= lim.max:
                wait = max(wait, lim.hits[-lim.max] + lim.window - now)
        return wait

    def record(self, policy: str, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        for lim in self._limits(policy):
            lim.hits.append(now)

    def update(self, policy: str, headers, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        rules = (headers.get("X-Rate-Limit-Rules") or "").split(",")
        new: list[_Limit] = []
        for rule in filter(None, (r.strip() for r in rules)):
            limits = (headers.get(f"X-Rate-Limit-{rule}") or "").split(",")
            states = (headers.get(f"X-Rate-Limit-{rule}-State") or "").split(",")
            for lim_s, st_s in zip(limits, states):
                try:
                    mx, win, _ = (int(x) for x in lim_s.split(":"))
                    count, _, blocked = (int(x) for x in st_s.split(":"))
                except ValueError:
                    continue
                if blocked:
                    self.blocked_until = max(self.blocked_until, now + blocked)
                old = next((l for l in self._limits(policy) if l.max == mx and l.window == win + 1), None)
                hits = [h for h in (old.hits if old else []) if now - h < win + 1]
                hits += [now] * max(0, count - len(hits))  # 서버가 센 횟수가 더 많으면 맞춘다
                new.append(_Limit(mx, win + 1.0, hits))  # 지연을 생각해 기간 1초 여유
        if new:
            self.policies[policy] = new
        if retry := headers.get("Retry-After"):
            try:
                self.blocked_until = max(self.blocked_until, now + float(retry))
            except ValueError:
                pass


class RateLimited(Exception):
    def __init__(self, wait: float):
        super().__init__(f"{wait:.0f}s")
        self.wait = wait


@dataclass
class Listing:
    amount: float
    currency: str
    indexed: str
    seller: str
    ex: Optional[float] = None  # 엑잘 환산 (환율을 알 때)


@dataclass
class Result:
    total: int
    listings: list[Listing]
    url: str  # 브라우저로 같은 검색 열기
    unit_ex: Optional[float] = None  # 교환소: 1개 = 엑잘


def _http_get(url: str, data: Optional[bytes] = None, timeout: float = 8.0):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


class TradeClient:
    def __init__(self, realm: str, opener: Optional[Callable] = None):
        self.base = REALMS[realm]
        self.limiter = RateLimiter()
        self._cache: dict[str, tuple[float, Result]] = {}
        self._rates: dict[tuple[str, str], tuple[float, float]] = {}  # (리그, 화폐) → (시각, 1개 = 엑잘)
        self._ninja: dict[tuple[str, str], tuple[float, dict[str, float]]] = {}
        self._open = opener or self._urlopen

    @staticmethod
    def _urlopen(url: str, data: Optional[bytes]):
        req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=8.0) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def _call(self, policy: str, url: str, data: Optional[bytes] = None) -> dict:
        wait = self.limiter.wait_time(policy)
        if wait > MAX_WAIT:
            raise RateLimited(wait)
        if wait > 0:
            time.sleep(wait)
        self.limiter.record(policy)
        status, headers, body = self._open(url, data)
        self.limiter.update(policy, headers)
        if status == 429:
            raise RateLimited(max(1.0, self.limiter.blocked_until - time.monotonic()))
        d = json.loads(body or b"{}")
        if status >= 400 or "error" in d:
            raise RuntimeError((d.get("error") or {}).get("message") or f"HTTP {status}")
        return d

    def search(self, league: str, query: Query) -> Result:
        if query.exchange:
            return self.exchange(league, query.exchange, query.exchange_group)
        body = query.body()
        key = json.dumps([league, body], ensure_ascii=False, sort_keys=True)
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL:
            return hit[1]
        lg = urllib.parse.quote(league)
        d = self._call("search", f"{self.base}/api/trade2/search/poe2/{lg}",
                       json.dumps(body, ensure_ascii=False).encode("utf-8"))
        ids, qid = d.get("result", [])[:10], d.get("id", "")
        listings = []
        if ids:
            f = self._call("fetch", f"{self.base}/api/trade2/fetch/{','.join(ids)}?query={qid}")
            for r in f.get("result", []):
                if not r:
                    continue
                lst = r.get("listing", {})
                price = lst.get("price") or {}
                if price.get("amount"):
                    listings.append(Listing(float(price["amount"]), price.get("currency", ""), lst.get("indexed", ""),
                                            (lst.get("account") or {}).get("name", "")))
        res = Result(int(d.get("total", 0)), listings, f"{self.base}/trade2/search/poe2/{lg}/{qid}")
        self._cache[key] = (time.monotonic(), res)
        return res

    def _offers(self, league: str, want: str, status: str = "online") -> tuple[dict, list[float]]:
        """교환소: 엑잘을 내고 want 를 받는 매물 → 1개당 엑잘 (싼 순).
        보여 주는 검색(거래소에서 열기)은 온라인만 — 오프라인 매물은 살 수 없다 (2026-10-17 사용자 요청).
        환율 추정에만 오프라인까지 (status="any": 하드코어 리그는 온라인 매물이 거의 없다)."""
        lg = urllib.parse.quote(league)
        body = {"query": {"status": {"option": status}, "have": [BASE_CURRENCY], "want": [want]},
                "sort": {"have": "asc"}, "engine": "new"}
        d = self._call("exchange", f"{self.base}/api/trade2/exchange/poe2/{lg}", json.dumps(body).encode("utf-8"))
        per = []
        res = d.get("result") or {}
        for x in (res.values() if isinstance(res, dict) else res):
            for o in ((x or {}).get("listing") or {}).get("offers", [])[:1]:
                pay, get = o.get("exchange", {}).get("amount"), o.get("item", {}).get("amount")
                if pay and get:
                    per.append(float(pay) / float(get))
        return d, per[:10]

    def ninja(self, league: str, group: str = "Currency") -> dict[str, float]:
        """poe.ninja: 교환소 id → 1개 = 엑잘 (30분 캐시). 실패하면 빈 dict."""
        key = (league, group)
        hit = self._ninja.get(key)
        if hit and time.monotonic() - hit[0] < RATE_TTL:
            return hit[1]
        out: dict[str, float] = {}
        try:
            url = f"{NINJA}?league={urllib.parse.quote(league)}&type={urllib.parse.quote(group)}"
            status, _, body = self._open(url, None)
            d = json.loads(body or b"{}") if status == 200 else {}
            ex_per_div = float((d.get("core") or {}).get("rates", {}).get("exalted") or 0)
            if ex_per_div:
                out["divine"] = ex_per_div
                for line in d.get("lines", []):
                    if line.get("id") and line.get("primaryValue"):
                        out[line["id"]] = float(line["primaryValue"]) * ex_per_div
                out[BASE_CURRENCY] = 1.0
        except (OSError, ValueError, urllib.error.URLError):
            out = {}
        self._ninja[key] = (time.monotonic(), out)
        return out

    def exchange(self, league: str, want: str, group: str = "Currency") -> Result:
        key = json.dumps(["exchange", league, want])
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL:
            return hit[1]
        d, per = self._offers(league, want)
        unit = self.ninja(league, group).get(want)
        if unit is None:
            unit = statistics.median(per) if per else None
        if unit is not None:
            self._rates[(league, want)] = (time.monotonic(), unit)
        res = Result(int(d.get("total", 0)), [], f"{self.base}/trade2/exchange/poe2/{urllib.parse.quote(league)}/{d.get('id', '')}",
                     unit)
        self._cache[key] = (time.monotonic(), res)
        return res

    def rate(self, league: str, currency: str) -> Optional[float]:
        """1 currency = ? 엑잘 (교환소 매물 중간값, 30분 캐시). 모르면 None."""
        if currency == BASE_CURRENCY:
            return 1.0
        if (v := self.ninja(league).get(currency)) is not None:
            return v
        hit = self._rates.get((league, currency))
        if hit and time.monotonic() - hit[0] < RATE_TTL:
            return hit[1]
        _, per = self._offers(league, currency, "any")
        if not per:
            return None
        unit = statistics.median(per)
        self._rates[(league, currency)] = (time.monotonic(), unit)
        return unit

    def add_rates(self, league: str, res: Result, limit: int = 3) -> None:
        """매물 가격에 엑잘 환산을 붙인다 (화폐 종류당 교환소 1번, 30분 캐시). 요청 제한이면 붙이지 않고 넘어간다."""
        seen: dict[str, Optional[float]] = {}
        for l in res.listings:
            if l.currency not in seen:
                if len(seen) >= limit + (BASE_CURRENCY in seen):
                    seen[l.currency] = None
                else:
                    try:
                        seen[l.currency] = self.rate(league, l.currency)
                    except (RateLimited, RuntimeError, OSError):
                        seen[l.currency] = None
            r = seen[l.currency]
            l.ex = l.amount * r if r is not None else None
        if res.listings and all(l.ex is not None for l in res.listings):
            # 거래소 정렬은 화폐 환산이 시세와 달라(1 카오스를 2 엑잘보다 싸게 봄) 엑잘 환산으로 다시 줄 세운다
            res.listings.sort(key=lambda l: l.ex)


def summary(res: Result) -> tuple[Optional[Listing], Optional[Listing], list[tuple[str, float, float, int]]]:
    """(최저, 중간, 화폐별 [(화폐, 최저, 최고, 개수)]). 엑잘 환산을 알면 add_rates 가 그 순서로 줄 세워 둔다."""
    if not res.listings:
        return None, None, []
    by: dict[str, list[float]] = {}
    for l in res.listings:
        by.setdefault(l.currency, []).append(l.amount)
    groups = [(cur, min(v), max(v), len(v)) for cur, v in by.items()]
    return res.listings[0], res.listings[len(res.listings) // 2], groups


def bait(res: Result) -> bool:
    """최저가가 중간 가격의 1/4 도 안 되면 미끼(낚시 매물)일 수 있다 (엑잘 환산을 알 때만)."""
    low, mid, _ = summary(res)
    return bool(low and mid and low.ex is not None and mid.ex and low.ex < mid.ex / 4)


def price_text(amount: float, currency: str, data: Optional[TradeData] = None, lang: str = "ko") -> str:
    name = CURRENCY_SHORT.get(lang, {}).get(currency) or (data.currency.get(currency) if data else "") or currency
    return f"{amount:g} {name}"


def ex_text(ex: float, lang: str = "ko") -> str:
    """엑잘 환산 표시: 10 이상은 정수, 그 아래는 소수 한 자리."""
    v = f"{ex:.0f}" if ex >= 10 else f"{ex:.1f}".rstrip("0").rstrip(".")
    return f"{v} {CURRENCY_SHORT[lang if lang in CURRENCY_SHORT else 'ko'][BASE_CURRENCY]}"
