"""경험치 효율: 캐릭터 레벨과 지역 레벨 차이에 따른 경험치 배율.

PoE 공식(PoE2 도 같은 식으로 알려져 있음, 게임 안에서 확인한 값이 아니라 추정):
안전 범위 = 3 + 레벨/16 (내림). 차이가 안전 범위를 넘은 만큼 d 라 하면
배율 = ((레벨 + 5) / (레벨 + 5 + d^2.5))^1.5, 최소 1%.
"""
from __future__ import annotations


def safe_range(level: int) -> int:
    return 3 + level // 16


def xp_multiplier(level: int, area_level: int) -> float:
    d = max(abs(level - area_level) - safe_range(level), 0)
    if d == 0:
        return 1.0
    return max(((level + 5) / (level + 5 + d ** 2.5)) ** 1.5, 0.01)


def full_xp_areas(level: int) -> tuple[int, int]:
    """경험치 100% 를 받는 지역 레벨 범위."""
    r = safe_range(level)
    return max(1, level - r), level + r
