from poe2_overlay.guide import Guide, parse_csv
from poe2_overlay.logparse import (
    AreaEntered, Death, LevelUp, LoginConnect, PassivePoints, Reward, SceneName, parse_line,
)
from poe2_overlay.tracker import NEW_CHAR, UNKNOWN_CHAR, Tracker

P = "2026/09/26 22:57:03 947613015 2caa229f [DEBUG Client 26920] "
I = "2026/09/26 22:57:03 947613015 2caa229f [INFO Client 26920] "

GUIDE = Guide(parse_csv("""
# comment
id,area_name,quest
g1_1,강둑,방어꾼 처치
g1_town,클리어펠 야영지,렌리 대화
g1_2,클리어펠,베이라 처치
g1_4,그렐우드,붉은 계곡 찾기
g1_5,붉은 계곡,녹왕 처치
g1_town,클리어펠 야영지,보상
g1_4,그렐우드,봉인 해제
"""), "test")


def area(code, lvl=1, pid="26920"):
    return AreaEntered("t", pid, code, lvl)


def test_parse_lines():
    assert parse_line(P + 'Generating level 2 area "G1_2" with seed 1293246616') == AreaEntered(
        "2026/09/26 22:57:03", "26920", "G1_2", 2)
    assert parse_line(I + "[SCENE] Set Source [클리어펠]").name == "클리어펠"
    assert parse_line(I + "[SCENE] Set Source [(null)]") is None
    lv = parse_line(I + ": char_g(소서리스) 님이 2레벨이 되었습니다.")
    assert isinstance(lv, LevelUp) and (lv.name, lv.cls, lv.level) == ("char_g", "소서리스", 2)
    assert isinstance(parse_line(I + ": char_h 님이 사망했습니다."), Death)
    rw = parse_line(I + ": char_g 님이 [Resistances|냉기] 저항 +10%을(를) 획득했습니다.")
    assert isinstance(rw, Reward) and rw.text == "냉기 저항 +10%"
    pp = parse_line(I + ": 패시브 스킬 포인트 2포인트를 획득했습니다.")
    assert isinstance(pp, PassivePoints) and pp.points == 2 and not pp.weapon_set
    wp = parse_line(I + ": 무기 세트 패시브 스킬 포인트를 2 획득했습니다.")
    assert isinstance(wp, PassivePoints) and wp.weapon_set
    assert isinstance(parse_line(I + "Async connecting to seo.login.pathofexile2.com:21276"), LoginConnect)
    assert parse_line(I + ": 전체 채팅 채널 1 한국어에 참가했습니다.") is None


def test_navigation_rules():
    g = GUIDE
    assert g.next_position(0, "G1_1") is None              # 같은 지역
    assert g.next_position(0, "g1_town") == 1               # 마을이 바로 다음 단계
    assert g.next_position(2, "g1_town") is None            # 정비하러 들른 마을은 무시
    assert g.next_position(1, "g1_4") == 3                  # 건너뛴 단계 허용
    assert g.next_position(4, "g1_2") is None               # 뒤로 가지 않음
    assert g.next_position(5, "g1_4") == 6
    assert g.next_position(5, "g1_5") == 4                  # 보스 전 포탈로 마을 다녀옴


def test_new_character_session():
    t = Tracker(GUIDE)
    t.feed(LoginConnect("t", "1"))
    t.feed(area("G1_1", pid="1"))
    assert t.snapshot().character.name == NEW_CHAR
    t.feed(LevelUp("t", "1", "alice", "소서리스", 2))
    t.feed(area("G1_town", pid="1"))
    t.feed(area("G1_2", pid="1"))
    s = t.snapshot()
    assert s.confirmed and s.character.name == "alice" and s.step.zone == "g1_2"


def test_existing_character_is_guessed_then_confirmed():
    t = Tracker(GUIDE)
    for ev in (area("G1_1", pid="1"), LevelUp("t", "1", "alice", "소서리스", 2),
               area("G1_town", pid="1"), area("G1_2", pid="1")):
        t.feed(ev)
    for ev in (area("G1_1", pid="2"), LevelUp("t", "2", "bob", "머서너리", 2)):
        t.feed(ev)
    # 게임 재시작 후 alice 로 접속해서 그렐우드로 이동
    t.feed(area("G1_2", pid="3"))
    assert t.snapshot().character.name == "alice" and not t.confirmed
    t.feed(area("G1_4", pid="3"))
    t.feed(LevelUp("t", "3", "alice", "소서리스", 9))
    s = t.snapshot()
    assert s.confirmed and s.character.name == "alice" and s.step.zone == "g1_4"
    assert t.chars["alice"].level == 9 and t.chars["bob"].cursor == 0


def test_unknown_character_in_hideout_is_not_guessed():
    t = Tracker(GUIDE)
    t.feed(area("G1_1", pid="1"))
    t.feed(LevelUp("t", "1", "alice", "소서리스", 2))
    t.feed(area("G1_town", pid="1"))
    t.feed(LoginConnect("t", "1"))  # 캐릭터 선택 화면으로 나감
    assert t.snapshot().character.name == UNKNOWN_CHAR
    t.feed(area("HideoutShoreline", 65, pid="1"))
    s = t.snapshot()
    assert s.character.name == UNKNOWN_CHAR and s.step is None
    t.feed(area("MapBluff", 70, pid="1"))
    t.feed(Death("t", "1", "carol"))
    s = t.snapshot()
    assert s.confirmed and s.character.name == "carol" and s.step.index == len(GUIDE) - 1
    assert t.chars["alice"].cursor == 1


def test_new_character_even_if_old_one_stuck_on_riverbank():
    t = Tracker(GUIDE)
    t.feed(area("G1_1", pid="1"))
    t.feed(LevelUp("t", "1", "old", "워리어", 2))  # 강둑에 머문 옛 캐릭터 (cursor 0)
    t.league = "Forbidden Rites"
    t.feed(area("G1_1", pid="2"))
    assert t.snapshot().character.name == NEW_CHAR
    t.feed(LevelUp("t", "2", "char_i", "소서리스", 2))
    s = t.snapshot()
    assert s.character.name == "char_i" and s.league == "Forbidden Rites"
    assert t.chars["old"].league == ""


def test_guess_skips_other_league():
    t = Tracker(GUIDE)
    t.feed(area("G1_1", pid="1"))
    t.feed(LevelUp("t", "1", "std", "워리어", 2))
    t.feed(area("G1_town", pid="1"))
    t.chars["std"].league = "Standard"
    t.league = "Forbidden Rites"
    t.feed(area("G1_town", pid="2"))
    assert t.snapshot().character.name == UNKNOWN_CHAR


def test_party_member_levelup_ignored():
    t = Tracker(GUIDE)
    t.feed(area("G1_1"))
    t.feed(LevelUp("t", "26920", "alice", "소서리스", 2))
    t.feed(LevelUp("t", "26920", "partyguy", "워리어", 30))
    assert t.current == "alice" and "partyguy" not in t.chars
