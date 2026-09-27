from poe2_overlay.items import compare, is_item_text, parse_item

CROSSBOW = """아이템 종류: 쇠뇌
아이템 희귀도: 마법
서리 내린 팽팽한 석궁 - 스킬
--------
물리 피해: 8-15
냉기 피해: 3-5 (cold)
치명타 명중 확률: 5.00%
초당 공격 횟수: 1.68 (augmented)
재장전 시간: 0.81 (augmented)
--------
요구 사항: 8 힘, 8 민첩
--------
아이템 레벨: 6
--------
{ 고정 속성 부여 }
볼트 속도 22(20-30)% 증가
--------
{ 접두어 속성 부여 "서리 내린" (등급: 10) — 피해, 원소, 냉기, 공격 }
냉기 피해 3(2-3)~5(4-6) 추가
{ 접미어 속성 부여 "- 스킬" (등급: 5) — 공격, 속도 }
공격 속도 5(5-7)% 증가
"""


def test_parse_crossbow():
    it = parse_item(CROSSBOW)
    assert is_item_text(CROSSBOW) and it.item_class == "쇠뇌" and it.rarity == "마법"
    assert it.damage == {"물리": (8, 15), "냉기": (3, 5)}
    assert it.aps == 1.68 and it.crit == 5.0 and it.item_level == 6
    assert round(it.dps, 2) == round((11.5 + 4) * 1.68, 2) and it.slot == "무기"


def test_compare_weapons():
    old = parse_item(CROSSBOW)
    new = parse_item(CROSSBOW.replace("물리 피해: 8-15", "물리 피해: 14-22"))
    title, diffs, verdict = compare(new, old)
    assert verdict == 1 and "DPS 26.0 → 37.0" in title and diffs[0].startswith("물리 +")


def test_armour_resists():
    boots = "아이템 종류: 신발\n아이템 희귀도: 희귀\n--------\n회피: 40\n--------\n+12% 화염 저항\n+20 최대 생명력\n이동 속도 10% 증가\n"
    it = parse_item(boots)
    assert it.evasion == 40 and it.res == {"화염": 12} and it.life == 20 and it.move_speed == 10
    assert parse_item("그냥 텍스트") is None


RING = """아이템 종류: 반지
아이템 희귀도: 마법
서리 내린 철제 반지 - 새끼용
--------
아이템 레벨: 7
--------
{ 고정 속성 부여 — 피해, 물리, 공격 }
공격 시 물리 피해 1~4 추가
--------
{ 접두어 속성 부여 "서리 내린" (등급: 9) — 피해, 원소, 냉기, 공격 }
공격 시 냉기 피해 1~2(2-3) 추가
{ 접미어 속성 부여 "- 새끼용" (등급: 8) — 원소, 화염, 저항 }
화염 저항 +7(6-10)%
"""


def test_ring_with_roll_ranges():
    it = parse_item(RING)
    assert it.res == {"화염": 7} and it.added == {"물리": (1, 4), "냉기": (1, 2)}
    title, _, _ = compare(it, None)
    assert "저항 합 7" in title and "공격 추가 피해 4" in title
    assert parse_item(CROSSBOW).added == {}  # 무기의 피해 추가 문구는 피해 줄에 이미 포함


def test_ring_slots_and_score():
    from poe2_overlay.items import defense_score, slot_keys
    assert slot_keys("반지") == ["반지", "반지#2"] and slot_keys("투구") == ["투구"]
    weak = parse_item(RING.replace("화염 저항 +7(6-10)%", "화염 저항 +1%"))
    assert defense_score(weak) < defense_score(parse_item(RING))
