from poe2_overlay.xp import full_xp_areas, safe_range, xp_multiplier


def test_safe_range_and_full_xp():
    assert safe_range(1) == 3 and safe_range(16) == 4 and safe_range(36) == 5
    assert full_xp_areas(36) == (31, 41)
    assert xp_multiplier(36, 40) == 1.0  # 이번 사망 지역 (물에 잠긴 도시)
    assert xp_multiplier(36, 41) == 1.0


def test_penalty_grows_with_gap():
    a, b, c = xp_multiplier(20, 27), xp_multiplier(20, 30), xp_multiplier(20, 40)
    assert 1.0 > a > b > c >= 0.01
    assert round(xp_multiplier(20, 27) * 100) == 48  # 차이 7, 안전 범위 4 → d=3: (25/(25+3^2.5))^1.5
    assert xp_multiplier(40, 30) < 1.0  # 과레벨도 줄어든다
