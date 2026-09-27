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
