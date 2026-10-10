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
    assert round(it.dps, 2) == round((11.5 + 4) * 1.68, 2) and it.slot == "손" and it.hand == "two"


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


def test_uncut_gem_is_not_gear():
    from poe2_overlay.items import is_gear, parse_item
    t = "아이템 종류: 미가공 보조 젬\n아이템 희귀도: 화폐\n미가공 보조 젬 (2레벨)\n--------\n보조 젬 생성하기\n"
    it = parse_item(t)
    assert it is None or not is_gear(it)


def test_sceptre_compares_spirit_and_minion_levels():
    from poe2_overlay.items import compare, parse_item
    old = parse_item("아이템 종류: 셉터\n아이템 희귀도: 마법\n남작의 덜컹대는 셉터 - 흥분\n--------\n정신력: 132 (augmented)\n"
                     "--------\n정신력 32(27-32)% 증가\n마나 재생 속도 15(10-19)% 증가\n")
    new = parse_item("아이템 종류: 셉터\n아이템 희귀도: 희귀\n어둠 지팡이\n덜컹대는 셉터\n--------\n정신력: 100\n"
                     "--------\n모든 소환수 스킬 레벨 +1\n")
    assert old.spirit == 132 and new.skill_levels == {"소환수": 1}
    title, diffs, verdict = compare(new, old)
    assert verdict == 1 and "소환수 스킬 레벨 +1" in diffs and "정신력 -32" in diffs


def test_amulet_resist_vs_life_and_spirit_mod():
    from poe2_overlay.items import compare, parse_item
    old = parse_item("아이템 종류: 목걸이\n아이템 희귀도: 희귀\n룬 문자 부적\n태양의 목걸이\n--------\n정신력 +14(10-15)\n--------\n"
                     "생명력 최대치 +62(60-69)\n치명타 확률 12(10-14)% 증가\n")
    new = parse_item("아이템 종류: 목걸이\n아이템 희귀도: 희귀\n피의 펜던트\n태양의 목걸이\n--------\n정신력 +15(10-15)\n--------\n"
                     "생명력 최대치 +15(10-19)\n번개 저항 +9(6-10)%\n화염 저항 +21(21-25)%\n")
    assert old.spirit == 14 and new.spirit == 15
    _, diffs, verdict = compare(new, old)
    assert verdict == 1 and "저항 합 +30" in diffs and "정신력 +1" in diffs


BONE_WAND = """Item Class: Wands
Rarity: Rare
Oblivion Barb
Bone Wand
--------
Requires: Level 6
--------
Item Level: 9
--------
Grants Skill: Level 3 Bone Blast
--------
{ Prefix Modifier "Adept's" (Tier: 7) — Damage, Caster }
42(35-44)% increased Spell Damage
{ Prefix Modifier "Cobalt" (Tier: 10) — Mana }
+18(15-24) to maximum Mana
{ Suffix Modifier "of Ire" (Tier: 6) — Caster, Critical }
11(10-14)% increased Critical Spell Damage Bonus
{ Suffix Modifier "of Warmth" (Tier: 3) — Mana }
9(8-12)% increased Mana Regeneration Rate
5% increased Light Radius
"""

FIRE_WAND = """Item Class: Wands
Rarity: Magic
Fervent Withered Wand
--------
Requires: Level 4
--------
Item Level: 6
--------
Grants Skill: Level 3 Chaos Bolt
--------
{ Prefix Modifier "Fervent" (Tier: 6) — Damage, Elemental, Fire }
Gain 14(13-15)% of Damage as Extra Fire Damage
"""


def test_caster_wand_compares_spell_damage():
    # 지팡이는 공격 속도가 없어 방어구처럼 비교됨 → 주문 피해 증가가 없으면 '비슷'으로 나오던 문제 (2026-10-09)
    new, old = parse_item(BONE_WAND), parse_item(FIRE_WAND)
    assert new.inc_damage == {"주문": 42} and new.cast_speed == 0  # 치명타 주문 피해 보너스는 제외
    _, diffs, verdict = compare(new, old)
    assert verdict == 1 and "주문 피해 증가 +42" in diffs
    _, _, back = compare(old, new)
    assert back == -1


def test_cast_speed_and_chaos_damage_parse():
    it = parse_item("Item Class: Wands\nRarity: Rare\nX\nWithered Wand\n--------\n"
                    "25% increased Chaos Damage\n35% increased Spell Damage\n9% increased Cast Speed\n")
    assert it.inc_damage == {"카오스": 25, "주문": 35} and it.cast_speed == 9


def _it(cls, extra=""):
    return f"Item Class: {cls}\nRarity: Rare\nX\nBase\n--------\n{extra}"


MACE_1H = _it("One Hand Maces", "Physical Damage: 10-20\nAttacks per Second: 1.50\n")
MACE_1H_B = _it("One Hand Maces", "Physical Damage: 5-10\nAttacks per Second: 1.40\n")
MACE_2H = _it("Two Hand Maces", "Physical Damage: 30-50\nAttacks per Second: 1.10\n")
SHIELD = _it("Shields", "Armour: 120\n--------\n+12% to Fire Resistance\n")
FOCUS = _it("Foci", "Energy Shield: 30\n")
STAFF = _it("Staves", "30% increased Spell Damage\n")


def test_hand_kinds_and_keys():
    from poe2_overlay.items import MAIN, OFF, hand_keys
    assert parse_item(MACE_1H).hand == "one" and parse_item(MACE_2H).hand == "two"
    assert parse_item(SHIELD).hand == "off" and parse_item(STAFF).hand == "two"
    assert parse_item(BONE_WAND).hand == "one" and parse_item(BONE_WAND).slot == "손"
    assert parse_item(_it("Body Armours")).slot == "갑옷"  # 언어와 상관없는 부위 키
    assert hand_keys(parse_item(MACE_2H), {}) == [MAIN]
    assert hand_keys(parse_item(MACE_1H), {}) == [MAIN, OFF]
    assert hand_keys(parse_item(SHIELD), {}) == [OFF]


def test_dual_wield_compares_weaker_hand():
    from poe2_overlay.items import MAIN, OFF, equip_key, hand_plan
    gear = {MAIN: MACE_1H, OFF: MACE_1H_B}
    cands, notes = hand_plan(parse_item(MACE_1H), gear)
    assert cands == [OFF, MAIN] and notes == []  # 약한 쪽(보조 손) 먼저
    assert equip_key(parse_item(MACE_1H), gear, OFF) == OFF


def test_two_hander_vs_one_hand_and_shield():
    from poe2_overlay.items import MAIN, OFF, equip_key, hand_plan
    gear = {MAIN: MACE_1H, OFF: SHIELD}
    cands, notes = hand_plan(parse_item(MACE_2H), gear)
    assert cands == [MAIN]  # 무기는 무기끼리
    assert notes and notes[0][0].startswith("양손 무기: 보조 손이 빠짐")
    assert equip_key(parse_item(MACE_2H), gear) == MAIN
    # 양손을 들고 있을 때 방패: 들 수 없다는 안내
    cands, notes = hand_plan(parse_item(SHIELD), {MAIN: MACE_2H})
    assert cands == [] and notes[0][0].startswith("양손 무기를 들고 있음")
    # 양손을 들고 있을 때 한 손 무기: 보조 손이 열린다는 안내
    _, notes = hand_plan(parse_item(MACE_1H), {MAIN: MACE_2H})
    assert notes[0][0].startswith("한 손 무기")


def test_giant_grip_two_handers_in_one_hand():
    # 보조 손에 양손 무기가 등록돼 있으면(거인의 피 등) 양손 무기도 두 칸 중 약한 쪽과 비교
    from poe2_overlay.items import MAIN, OFF, giant_grip, hand_keys, hand_plan
    gear = {MAIN: MACE_2H, OFF: MACE_2H.replace("30-50", "20-30")}
    assert giant_grip(gear)
    assert hand_keys(parse_item(MACE_2H), gear) == [MAIN, OFF]
    cands, notes = hand_plan(parse_item(MACE_2H), gear)
    assert cands == [OFF, MAIN] and notes == []
    assert giant_grip({MAIN: MACE_2H, OFF: SHIELD})  # 양손 + 방패도 한 손 취급
    assert not giant_grip({MAIN: MACE_1H, OFF: SHIELD})


def test_caster_weapons_share_main_hand():
    # 지팡이·스태프·셉터가 따로 저장되던 문제: 모두 주 손에서 비교
    from poe2_overlay.items import MAIN, hand_plan
    cands, notes = hand_plan(parse_item(BONE_WAND), {MAIN: STAFF})
    assert cands == [MAIN] and notes[0][0].startswith("한 손 무기")  # 스태프 → 지팡이: 집중구를 들 수 있게 됨
    _, diffs, verdict = compare(parse_item(BONE_WAND), parse_item(STAFF))
    assert verdict == 1 and "주문 피해 증가 +12" in diffs


def test_normalize_old_gear():
    from poe2_overlay.items import MAIN, OFF, normalize_gear
    old = {"Wands": BONE_WAND, "Boots": _it("Boots", "Energy Shield: 10\n"), "Staves": STAFF, "Foci": FOCUS,
           "퀘스트 아이템": "아이템 종류: 퀘스트 아이템\n아이템 희귀도: 퀘스트\nX\n", "Rings": _it("Rings"),
           "반지#2": "아이템 종류: 반지\n아이템 희귀도: 희귀\nY\n"}
    g = normalize_gear(old)
    # 무기가 둘(지팡이·스태프)이라 어느 것인지 몰라 버림, 집중구는 하나라 보조 손, 퀘스트 아이템 제외, 부위 키는 언어 무관
    assert set(g) == {OFF, "장화", "반지", "반지#2"} and g[OFF] == FOCUS
    g = normalize_gear({"무기": MACE_1H, "방패": SHIELD.replace("Item Class: Shields", "아이템 종류: 방패")})
    assert g[MAIN] == MACE_1H and OFF in g
    assert normalize_gear(g) == g  # 두 번 해도 같음


SCEPTRE = _it("Sceptres", "Spirit: 100\n")


def test_wand_and_sceptre_go_to_different_hands():
    # 지팡이 + 셉터: 주 손과 종류가 다른 한 손 무기는 보조 손으로, 비교는 같은 종류와 먼저
    from poe2_overlay.items import MAIN, OFF, equip_key, hand_plan
    assert equip_key(parse_item(SCEPTRE), {MAIN: BONE_WAND, OFF: FOCUS}) == OFF
    assert equip_key(parse_item(FIRE_WAND), {MAIN: BONE_WAND, OFF: SCEPTRE}) == MAIN
    cands, _ = hand_plan(parse_item(FIRE_WAND), {MAIN: BONE_WAND, OFF: SCEPTRE})
    assert cands[0] == MAIN
    cands, _ = hand_plan(parse_item(SCEPTRE), {MAIN: BONE_WAND, OFF: SCEPTRE})
    assert cands[0] == OFF
