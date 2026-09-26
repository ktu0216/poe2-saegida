"""상점 검색 정규식: 캐릭터의 빌드(없으면 직업)와 액트로 하나를 자동 선택한다."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class RegexRule:
    name: str
    build: str
    classes: tuple[str, ...]
    acts: tuple[str, ...]
    regex: str


class RegexBook:
    def __init__(self, rules: list[RegexRule], vendors: set[str]):
        self.rules = rules
        self.vendors = vendors

    @classmethod
    def load(cls, path: Path) -> "RegexBook":
        d = json.loads(path.read_text(encoding="utf-8"))
        rules = [RegexRule(r["name"], r.get("build", ""), tuple(r.get("classes", [])),
                           tuple(r.get("acts", [])), r["regex"]) for r in d.get("rules", [])]
        return cls(rules, set(d.get("vendors", [])))

    def select(self, build_name: str, cls: str, act: str) -> Optional[RegexRule]:
        """빌드 이름이 맞는 규칙이 우선, 빌드가 없거나 아무 규칙과도 안 맞으면 직업으로."""
        ok_act = [r for r in self.rules if not r.acts or act in r.acts]
        if build_name:
            for r in ok_act:
                if r.build and re.search(r.build, build_name, re.IGNORECASE):
                    return r
        for r in ok_act:
            if cls and cls in r.classes:
                return r
        return None

    def vendor_spoke(self, line: str) -> bool:
        """로그 한 줄이 마을 상인의 대사인지 (`[INFO Client 123] 렌리: 둘러보게나.`)."""
        return any(f"] {v}: " in line for v in self.vendors)
