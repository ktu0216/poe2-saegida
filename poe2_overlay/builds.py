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
    m = _STAGE.match(name)
    stage, rest = (m["stage"], m["rest"]) if m else ("", name)
    gems = []
    for s in d.get("skills", []) or []:
        lo, hi = (s.get("level_interval") or [1, 100])[:2]
        gems.append(Gem(s.get("id", ""), int(lo), int(hi),
                        [x.get("id", "") for x in s.get("support_skills", []) or []]))
    rest = rest.replace("�", "").strip()  # 게임이 잘라 저장한 파일 이름의 깨진 글자
    name = name.replace("�", "").strip()
    return BuildFile(path, name, d.get("ascendancy", ""), stage, rest[:FAMILY_KEY_LEN].strip(), gems, rest)


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
    """젬 ID → 한국어 이름. 레임 가이드의 gems_ko.json 이 있으면 쓰고, 없으면 영어 이름."""

    def __init__(self, mapping: Optional[dict[str, str]] = None):
        self.map = mapping or {}

    @classmethod
    def load(cls, folder: Optional[Path]) -> "GemNames":
        """레임 가이드 pob_leveling 폴더: gems_ko.json (젬 ID→이름), ko_names.json (영어 이름→한국어)."""
        mapping: dict[str, str] = {}
        if folder and folder.is_dir():
            try:
                d = json.loads((folder / "ko_names.json").read_text(encoding="utf-8"))
                for en, ko in (d.get("gems") or {}).items():
                    mapping[en.lower()] = ko
            except (OSError, ValueError):
                pass
            try:
                d = json.loads((folder / "gems_ko.json").read_text(encoding="utf-8"))
                for key, v in d.items():
                    if isinstance(v, dict) and v.get("name"):
                        mapping[key.rsplit("/", 1)[-1]] = v["name"]
            except (OSError, ValueError):
                pass
        return cls(mapping)

    def __call__(self, gem_id: str) -> str:
        if ko := self.map.get(gem_id.rsplit("/", 1)[-1]):
            return ko
        en = _english(gem_id)
        base = re.sub(r" (II|III|IV)$", "", en)
        ko = self.map.get(en.lower()) or self.map.get(base.lower())
        return (ko + en[len(base):]) if ko and en != base and not self.map.get(en.lower()) else (ko or en)


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
