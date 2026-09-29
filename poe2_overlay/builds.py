"""게임 빌드 플래너(.build) 파일로 캐릭터 레벨/액트에 맞는 젬을 안내한다.

.build 는 JSON: {"name", "ascendancy", "skills": [{"id", "level_interval": [lo, hi],
"support_skills": [{"id", ...}]}], "passives", "inventory_slots", ...}
빌드 사이트에서 구간별로 받은 파일("Act 1 - [0.5.5] X", "Act 2 - [0.5.5] X", "Interludes - …",
"Early Endgame - …")은 같은 '묶음'으로 보고, 현재 액트에 맞는 파일을 자동으로 고른다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# 구간 접두어: "Act 1 & 2 (Pre-Ascend) - ", "Act 4 to Endgame - ", "Interludes - ", "LvL 1~42 - " ...
_STAGE = re.compile(
    r"^(?P<stage>Act \d+(?: ?& ?\d+)?(?: to Endgame)?(?: \([^)]*\))?|Interludes?|"
    r"(?:Budget|Early|Mid|Late|Uber|Crit)[ -]?Endgame|Endgame(?: \w+)?|Crit|Imported|"
    r"LvL \d+ ?~ ?\d+)\s+-\s+(?P<rest>.+)$", re.IGNORECASE)
FAMILY_KEY_LEN = 14  # 파일 이름이 잘려 저장되므로 앞부분으로 묶는다

# 직접 정한 이름 규칙: "<빌드 이름> <번호>. <구간>" (예: "젬링 유탄 1. Lv 1-42", "젬링 유탄 3. 엔드 초기")
# 게임 목록에서 같은 빌드끼리 번호 순으로 모인다. 이름은 40바이트 안쪽 (게임이 잘라 저장한다).
_NUMBERED = re.compile(r"^(?P<family>.+?) (?P<n>\d+)\. (?P<stage>.+)$")
_STAGE_KO = {"엔드 초기": "Early Endgame", "엔드 중기": "Mid Endgame", "엔드 후기": "Late Endgame",
             "엔드": "Endgame", "막간": "Interludes", "액트 올인원": "All-In-One"}


def _numbered_stage(text: str) -> str:
    """'Lv 1-42' → 'LvL 1~42', '액트 1' → 'Act 1', '엔드 초기' → 'Early Endgame'. 모르면 그대로."""
    t = text.strip()
    if m := re.fullmatch(r"[Ll]v\.? ?(\d+) ?[-~] ?(\d+)", t):
        return f"LvL {m[1]}~{m[2]}"
    if m := re.fullmatch(r"액트 (\d+(?: ?[-~] ?\d+)?)", t):
        return "Act " + m[1].replace("-", " & ").replace("~", " & ")
    return _STAGE_KO.get(t, t)


@dataclass
class Gem:
    id: str
    lo: int
    hi: int
    supports: list[str] = field(default_factory=list)


@dataclass
class BuildFile:
    path: Path
    name: str
    ascendancy: str
    stage: str
    family: str
    gems: list[Gem]
    label: str = ""  # 화면 표시용 묶음 이름 (잘리지 않은 뒷부분)

    @property
    def acts(self) -> set[str]:
        """이 구간이 맡는 액트 라벨 (guide.act_label 형식)."""
        s = self.stage.lower()
        if not s:
            return set()
        if s.startswith("act"):
            nums = [int(n) for n in re.findall(r"\d+", s.split("(")[0])]
            out = {f"액트 {n}" for n in range(min(nums), max(nums) + 1)} if nums else set()
            if "endgame" in s:
                out |= {"막간 1", "막간 2", "막간 3", "엔드게임"}
            return out
        if s.startswith("interlude"):
            return {"막간 1", "막간 2", "막간 3"}
        if "endgame" in s or s in ("crit", "imported"):
            return {"엔드게임"}
        return set()

    @property
    def levels(self) -> Optional[tuple[int, int]]:
        m = re.match(r"lvl (\d+) ?~ ?(\d+)", self.stage.lower())
        return (int(m[1]), int(m[2])) if m else None

    @property
    def order(self) -> int:
        """엔드게임 변형이 여러 개면 입문용부터."""
        s = self.stage.lower()
        for i, k in enumerate(("early", "budget", "mid", "late", "crit", "uber")):
            if s.startswith(k):
                return i
        return 0 if s.startswith(("act", "interlude", "lvl")) else 9


def load_build(path: Path) -> Optional[BuildFile]:
    try:
        d = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    name = d.get("name") or path.stem
    if name.lower().startswith("unnamed"):  # poe.ninja 내보내기 등
        name = path.stem
    if n := _NUMBERED.match(name.replace("�", "").strip()):
        fam = n["family"].strip()
        gems = _gems(d)
        return BuildFile(path, name, d.get("ascendancy", ""), _numbered_stage(n["stage"]), fam, gems, fam)
    m = _STAGE.match(name)
    stage, rest = (m["stage"], m["rest"]) if m else ("", name)
    gems = _gems(d)
    rest = rest.replace("�", "").strip()  # 게임이 잘라 저장한 파일 이름의 깨진 글자
    name = name.replace("�", "").strip()
    return BuildFile(path, name, d.get("ascendancy", ""), stage, rest[:FAMILY_KEY_LEN].strip(), gems, rest)


def _gems(d: dict) -> list[Gem]:
    gems = []
    for s in d.get("skills", []) or []:
        lo, hi = (s.get("level_interval") or [1, 100])[:2]
        gems.append(Gem(s.get("id", ""), int(lo), int(hi),
                        [x.get("id", "") for x in s.get("support_skills", []) or []]))
    return gems


def scan(folder: Path) -> list[BuildFile]:
    if not folder.is_dir():
        return []
    return [b for p in sorted(folder.glob("*.build")) if (b := load_build(p))]


def families(builds: list[BuildFile]) -> dict[str, list[BuildFile]]:
    out: dict[str, list[BuildFile]] = {}
    for b in builds:
        out.setdefault(b.family, []).append(b)
    for files in out.values():  # 묶음 이름은 가장 긴(덜 잘린) 것으로
        label = max((f.label for f in files), key=len)
        for f in files:
            f.label = label
    return out


def family_of(builds: list[BuildFile], build_name: str) -> Optional[str]:
    """게임 설정 active_builds 의 빌드 이름 → 묶음."""
    for b in builds:
        if b.name == build_name or b.path.stem == build_name:
            return b.family
    return None


# 레벨업 줄의 직업 이름 → .build 의 ascendancy 앞부분 (전직 이름은 tracker.ASCENDANCY_KO 로 되짚는다)
CLASS_IDS = {"워리어": "Warrior", "머서너리": "Mercenary", "레인저": "Ranger", "헌트리스": "Huntress",
             "위치": "Witch", "소서리스": "Sorceress", "몽크": "Monk", "드루이드": "Druid"}


def family_for_class(builds: list[BuildFile], cls: str) -> Optional[str]:
    """직업(또는 전직)이 맞는 빌드 묶음이 딱 하나면 그 묶음."""
    from .tracker import ASCENDANCY_KO
    ids = [k for k, v in ASCENDANCY_KO.items() if v == cls]  # 전직 이름이면 정확히
    prefix = CLASS_IDS.get(cls)
    fams = {b.family for b in builds
            if b.ascendancy and (b.ascendancy in ids or (prefix and b.ascendancy.startswith(prefix)))}
    return fams.pop() if len(fams) == 1 else None


def pick_stage(files: list[BuildFile], act: str, level: int) -> Optional[BuildFile]:
    """현재 액트(없으면 레벨)에 맞는 구간 파일. 맞는 게 없으면 가장 가까운 앞 구간."""
    if not files:
        return None
    by_act = sorted((b for b in files if act in b.acts), key=lambda b: (b.order, len(b.acts)))
    if by_act:
        return by_act[0]
    by_lvl = [b for b in files if b.levels and b.levels[0] <= level <= b.levels[1]]
    if by_lvl:
        return by_lvl[0]
    return files[0] if len(files) == 1 else sorted(files, key=lambda b: (b.levels or (0, 0))[0])[0]


# ---------------------------------------------------------------- 젬 이름
def _english(gem_id: str) -> str:
    last = gem_id.rsplit("/", 1)[-1]
    last = re.sub(r"^(SkillGem|SupportGem)", "", last)
    roman = {"Two": " II", "Three": " III", "Four": " IV"}
    for k, v in roman.items():
        if last.endswith(k):
            last = last[: -len(k)] + v
            break
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", last).strip()


class GemNames:
    """젬 ID → 게임 검색용 한국어 이름.

    1) 보정 파일 names (게임에서 직접 확인) 2) 거래소 데이터(표시 영어 이름 → 한국어)
    3) 레임 가이드 이름 사전 4) 없으면 영어 이름 + 표시.
    빌드 파일의 ID 는 게임 내부 이름이라 표시 이름과 다를 수 있어(Scattershot → Multishot) 보정 파일 ids 로 바꾼다.
    """

    def __init__(self, mapping: Optional[dict[str, str]] = None):
        self.map = mapping or {}  # 레임: 소문자 영어 이름 / 젬 ID 끝부분 → 한국어
        self.trade: dict[str, str] = {}  # 거래소: 표시 영어 이름(등급 포함) → 한국어
        self.ids: dict[str, str] = {}  # 내부 이름 → 표시 영어 이름
        self.names: dict[str, str] = {}  # 게임에서 확인한 한국어 (소문자 영어 키)
        self.unknown_mark = ""  # 한국어 이름을 모를 때 영어 이름 뒤에 붙일 표시

    @staticmethod
    def _read(path: Optional[Path]) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else {}
        except (OSError, ValueError):
            return {}

    @classmethod
    def load(cls, folder: Optional[Path], overrides: Optional[Path] = None,
             trade: Optional[Path] = None) -> "GemNames":
        """folder: 레임 가이드 pob_leveling (gems_ko.json, ko_names.json)."""
        mapping: dict[str, str] = {}
        if folder and folder.is_dir():
            for en, ko in (cls._read(folder / "ko_names.json").get("gems") or {}).items():
                mapping[en.lower()] = ko
            for key, v in cls._read(folder / "gems_ko.json").items():
                if isinstance(v, dict) and v.get("name"):
                    mapping[key.rsplit("/", 1)[-1]] = v["name"]
        names = cls(mapping)
        ov = cls._read(overrides)
        names.ids = {k.lower(): v for k, v in (ov.get("ids") or {}).items()}
        names.names = {k.lower(): v for k, v in (ov.get("names") or {}).items()}
        names.trade = dict(cls._read(trade).get("names") or {})
        names.unknown_mark = " (한글명 미확인)"
        return names

    def __call__(self, gem_id: str) -> str:
        en = _english(gem_id)
        m = re.match(r"^(.*?)( (?:II|III|IV))?$", en)
        base, tier = m[1], m[2] or ""
        shown = self.ids.get(base.lower(), base)  # 게임 표시 영어 이름
        if ko := self.names.get(shown.lower()) or self.names.get(base.lower()):
            return ko + tier
        for key in ((f"{shown}{tier}",) if tier else (shown, f"{shown} I")):
            if ko := self.trade.get(key):
                return ko
        if ko := self.map.get(gem_id.rsplit("/", 1)[-1]):
            return ko
        if ko := self.map.get(en.lower()):
            return ko
        if ko := self.map.get(base.lower()):
            return ko + tier
        return shown + tier + self.unknown_mark

@dataclass
class GemPlan:
    build: BuildFile
    now: list[Gem]
    upcoming: list[Gem]  # 아직 레벨이 안 되는 젬 (가까운 순)
    unlocked_at: list[Gem]  # 정확히 이 레벨에 새로 쓰게 되는 젬


def plan(build: BuildFile, level: int) -> GemPlan:
    now = [g for g in build.gems if g.lo <= level <= g.hi]
    upcoming = sorted((g for g in build.gems if g.lo > level), key=lambda g: g.lo)
    return GemPlan(build, now, upcoming, [g for g in build.gems if g.lo == level])


# ---------------------------------------------------------------- 미가공 젬 도우미
_UNCUT = re.compile(r"미가공 (스킬|보조|정신력) 젬|Uncut (Skill|Support|Spirit) Gem")
_UNCUT_KIND = {"스킬": "skill", "보조": "support", "정신력": "spirit",
               "Skill": "skill", "Support": "support", "Spirit": "spirit"}
_UNCUT_LEVEL = (re.compile(r"\((\d+)레벨\)"), re.compile(r"\(Level (\d+)\)"),
                re.compile(r"^(?!아이템)(?:젬 )?레벨: ?(\d+)", re.M), re.compile(r"^(?!Item)Level: ?(\d+)", re.M))
# 정신력(지속 효과) 젬: 빌드 파일에는 종류가 없어서 이름으로 가린다
SPIRIT_HINTS = ("Herald", "Attrition", "Archmage", "Berserk", "Banner", "Invocation", "Ghost Dance", "Grim Feast",
                "Iron Ward", "Magma Barrier", "Mana Remnants", "Wind Dancer", "Scavenged Plating", "Presence",
                "Alchemist's Boon", "Arctic Armour", "Trinity", "Raging Spirits", "Sacrifice", "Time Of Need",
                "Combat Frenzy", "Charge Infusion", "Elemental Conflux", "Convalescence", "Plague Bearer",
                "Siphon Elements", "Lingering Illusion", "Cast On", "Blink", "Shard Scavenger")


def parse_uncut(text: str) -> Optional[tuple[str, int]]:
    """클립보드의 미가공 젬 → (skill|support|spirit, 레벨). 레벨을 못 읽으면 0."""
    m = _UNCUT.search(text)
    if not m:
        return None
    kind = _UNCUT_KIND[m[1] or m[2]]
    for rx in _UNCUT_LEVEL:
        if lv := rx.search(text):
            return kind, int(lv[1])
    return kind, 0


def is_spirit(gem_id: str) -> bool:
    return any(h.lower() in _english(gem_id).lower() for h in SPIRIT_HINTS)


def _tier(gem_id: str) -> int:
    t = _english(gem_id).rsplit(" ", 1)[-1]
    return {"II": 2, "III": 3, "IV": 4}.get(t, 1)


def uncut_advice(build: BuildFile, kind: str, level: int, char_level: int, names) -> str:
    """미가공 젬으로 무엇을 만들지 빌드 기준으로 (HTML 한 덩어리)."""
    import html
    esc = lambda s: html.escape(s)
    if kind == "support":
        rows = []
        for g in sorted(build.gems, key=lambda g: g.lo):
            ok = [names(s) for s in g.supports if not level or _tier(s) <= level]
            later = [names(s) for s in g.supports if level and _tier(s) > level]
            if ok or later:
                line = f"{esc(names(g.id))}: " + " · ".join(esc(n) for n in ok)
                if later:
                    line += f' <span style="color:#9a9284">(더 높은 등급 필요: {esc(" · ".join(later))})</span>'
                rows.append(line)
        return "<br>".join(rows) or "이 빌드에는 보조 젬이 없습니다"
    gems = [g for g in build.gems if is_spirit(g.id) == (kind == "spirit")]
    if not gems:
        return "이 빌드에서 만들 젬이 없습니다"
    now = [g for g in sorted(gems, key=lambda g: g.lo) if g.lo <= char_level]
    nxt = [g for g in sorted(gems, key=lambda g: g.lo) if g.lo > char_level]
    parts = []
    if now:
        parts.append("지금 쓰는 젬: " + " · ".join(f"<b>{esc(names(g.id))}</b>" for g in now))
    if nxt:
        parts.append("다음: " + " · ".join(f"{esc(names(g.id))} (Lv {g.lo})" for g in nxt))
    return "<br>".join(parts)
