from poe2_overlay.config import resource_dir
from poe2_overlay.encounters import Encounters
from poe2_overlay.guide import Guide, parse_csv
from poe2_overlay.logparse import AreaEntered, Death, LevelUp, NpcLine, parse_line
from poe2_overlay.tracker import Tracker

ENC = Encounters.load(resource_dir() / "guides" / "encounters_ko.json")
GUIDE = Guide(parse_csv("""
g1_4,그렐우드,붉은 계곡 찾기
g1_5,붉은 계곡,오벨리스크 3개 찾고 녹왕 처치 → 마을
g1_town,클리어펠 야영지,렌리에게 보상 받고 그렐우드로 이동
g1_4,그렐우드,봉인 해제
"""), "t")


def feed(t, *events):
    for e in events:
        t.feed(e)


def start():
    t = Tracker(GUIDE, encounters=ENC)
    feed(t, AreaEntered("t", "1", "G1_4", 4), LevelUp("t", "1", "me", "머서너리", 4),
         AreaEntered("t", "1", "G1_5", 5))
    return t


def test_parse_npc_line():
    ln = "2026/09/27 12:00:57 1 a [INFO Client 1240] 녹왕: 일족을 위하여!"
    assert parse_line(ln) == NpcLine("2026/09/27 12:00:57", "1240", "녹왕", "일족을 위하여!")
    assert parse_line("2026/09/27 12:00:57 1 a [INFO Client 1240] Tile hash: 2124826808") is None


def test_town_before_boss_keeps_step_and_markers():
    t = start()
    feed(t, NpcLine("t", "1", "귀신의 목소리", "우리 의지는 굳건하다..."),
         AreaEntered("t", "1", "G1_town", 15))  # 정비하러 마을
    s = t.snapshot()
    assert s.step.zone == "g1_5" and s.flags["marker"] == "오벨리스크 2/3"


def test_boss_kill_then_town_advances():
    t = start()
    feed(t, AreaEntered("t", "1", "G1_town", 15), AreaEntered("t", "1", "G1_5", 5),
         NpcLine("t", "1", "귀신의 목소리", "여긴 우리 땅이다. 우린 하나 되어 싸운다!"),
         NpcLine("t", "1", "녹왕", "일족을 위하여!"))
    assert t.snapshot().flags["boss"] == "engaged"
    feed(t, AreaEntered("t", "1", "G1_town", 15))
    s = t.snapshot()
    assert s.step.zone == "g1_town" and t.chars["me"].step_flags["1"]["boss"] == "killed"


def test_death_to_boss_does_not_advance():
    t = start()
    feed(t, NpcLine("t", "1", "녹왕", "침입자!"), Death("t", "1", "me"),
         AreaEntered("t", "1", "G1_town", 15))
    s = t.snapshot()
    assert s.step.zone == "g1_5"
    assert t.chars["me"].step_flags["1"]["boss"] == "died"

GUIDE7 = Guide(parse_csv("""
g1_6,으스스한 덩굴,공동묘지 입구 찾기
g1_7,영원한 자의 공동묘지,배우자와 집정관 처치 → 사냥터
g1_11,사냥터,까마귀 종 처치
"""), "t")


def test_subzone_bosses_under_parent_step():
    t = Tracker(GUIDE7, encounters=ENC)
    feed(t, AreaEntered("t", "1", "G1_6", 6), LevelUp("t", "1", "me", "머서너리", 6),
         AreaEntered("t", "1", "G1_7", 7), AreaEntered("t", "1", "G1_8", 8))
    s = t.snapshot()
    assert s.step.zone == "g1_7" and not s.off_route
    feed(t, NpcLine("t", "1", "영원의 집정관 드레이븐", "무릎 꿇어라!"))
    assert t.snapshot().flags["sub"] == {"집정관": "engaged"}
    feed(t, AreaEntered("t", "1", "G1_7", 7), AreaEntered("t", "1", "G1_9", 8),
         NpcLine("t", "1", "집정관의 배우자 아시니아", "..."), Death("t", "1", "me"))
    assert t.snapshot().flags["sub"] == {"집정관": "killed", "배우자": "died"}


GUIDE12 = Guide(parse_csv("""
g1_11,사냥터,까마귀 종 처치
g1_12,프레이쏜,의식 3개 진행 후 연무 속의 왕 처치 → 마을 복귀
g1_town,클리어펠 야영지,핀과 대화
"""), "t")


def test_ritual_lines_are_progress_not_fight():
    t = Tracker(GUIDE12, encounters=ENC)
    feed(t, AreaEntered("t", "1", "G1_11", 10), LevelUp("t", "1", "me", "머서너리", 8),
         AreaEntered("t", "1", "G1_12", 11),
         NpcLine("t", "1", "연무 속의 왕", "<i>{코 로르}... 나그네여."))
    s = t.snapshot()
    assert s.flags == {"marker": "의식 1/3"}
    feed(t, AreaEntered("t", "1", "G1_town", 15))  # 의식 중 정비 → 단계 유지
    assert t.snapshot().step.zone == "g1_12"
    feed(t, AreaEntered("t", "1", "G1_12", 11), NpcLine("t", "1", "연무 속의 왕", "사라져라!"),
         NpcLine("t", "1", "연무 속의 왕", "들어줄 테니 말해 봐라, 나그네여!"),
         NpcLine("t", "1", "연무 속의 왕", "사라져라!"))
    assert t.snapshot().flags == {"marker": "의식 3/3", "boss": "engaged"}


def test_kill_line_marks_killed_immediately():
    t = Tracker(GUIDE12, encounters=ENC)
    feed(t, AreaEntered("t", "1", "G1_11", 10), LevelUp("t", "1", "me", "머서너리", 8),
         AreaEntered("t", "1", "G1_12", 11),
         NpcLine("t", "1", "연무 속의 왕", "들어줄 테니 말해 봐라, 나그네여!"),
         NpcLine("t", "1", "연무 속의 왕", "야생림의 힘은... 내 것이다!"))
    assert t.snapshot().flags == {"marker": "2페이즈", "boss": "engaged"}
    feed(t, NpcLine("t", "1", "연무 속의 왕", "우리는 다시 만나게 될 것이다..."))
    assert t.snapshot().flags["boss"] == "killed"


def test_soon_marker_before_rust_king():
    t = start()
    feed(t, NpcLine("t", "1", "귀신의 목소리", "여긴 우리 땅이다. 우린 하나 되어 싸운다!"))
    s = t.snapshot()
    assert s.flags.get("soon") and s.in_step_zone and s.boss == "녹왕"
    feed(t, AreaEntered("t", "1", "G1_town", 15))
    assert not t.snapshot().in_step_zone  # 마을로 나가면 간단 모드 조건에서 빠진다


def test_no_revert_to_step_whose_boss_is_killed():
    t = Tracker(GUIDE12, encounters=ENC)
    feed(t, AreaEntered("t", "1", "G1_11", 10), LevelUp("t", "1", "me", "머서너리", 10),
         AreaEntered("t", "1", "G1_12", 11),
         NpcLine("t", "1", "연무 속의 왕", "들어줄 테니 말해 봐라, 나그네여!"),
         NpcLine("t", "1", "연무 속의 왕", "우리는 다시 만나게 될 것이다..."),
         AreaEntered("t", "1", "G1_town", 15), AreaEntered("t", "1", "G1_12", 11))
    assert t.snapshot().step.zone == "g1_town"


GUIDE15 = Guide(parse_csv("""
g1_14,저택 성벽,오검 저택으로 이동
g1_15,오검 저택,양초 덩어리 → 지오너 백작 처치 → 마을
g1_town,클리어펠 야영지,액트 2
"""), "t")


def test_geonor_phase1_counts_only_after_countess():
    t = Tracker(GUIDE15, encounters=ENC)
    feed(t, AreaEntered("t", "1", "G1_14", 14), LevelUp("t", "1", "me", "머서너리", 12),
         AreaEntered("t", "1", "G1_15", 15),
         NpcLine("t", "1", "지오너 백작", "쉬는 건 죽은 다음에 하면 되지. 계속 파라!"))
    assert t.snapshot().flags.get("boss") is None
    feed(t, NpcLine("t", "1", "백작 부인", "여보, 이 침입자에겐 …"),
         NpcLine("t", "1", "지오너 백작", "이번엔 생포할 생각이 없다. 내가 직접 머리를 베어 주마!"))
    assert t.snapshot().flags["boss"] == "engaged"


GUIDE2 = Guide(parse_csv("""
g2_town,아르듀라 카라반,케스로 이동
g2_4_1,케스,카발라 처치 후 잃어버린 도시로 이동
g2_town,아르듀라 카라반,자르카 대화
"""), "t")


def test_book_counts_as_kill_only_during_fight():
    from poe2_overlay.logparse import PassivePoints
    t = Tracker(GUIDE2, encounters=ENC)
    feed(t, AreaEntered("t", "1", "G2_town", 32), LevelUp("t", "1", "me", "머서너리", 19),
         AreaEntered("t", "1", "G2_4_1", 23), PassivePoints("t", "1", 2, False))  # 예전 책을 보스 전에 사용
    assert t.snapshot().flags.get("boss") is None
    feed(t, NpcLine("t", "1", "위압자 여왕 카발라", "깨어난다!"), PassivePoints("t", "1", 2, False))
    assert t.snapshot().flags["boss"] == "killed"


def test_reward_while_boss_engaged_counts_as_kill():
    from poe2_overlay.logparse import Reward
    g = Guide(parse_csv("id,area_name,quest\ng3_6_1,지콰니의 기계실,검은 턱 처치\ng3_6_2,지콰니의 지성소,다음"), "t")
    t = Tracker(g, encounters=ENC)
    t.feed(AreaEntered("t", "9", "G3_6_1", 37))
    t.feed(LevelUp("t", "9", "hc", "머서너리", 32))
    t.feed(NpcLine("t", "9", "검은턱", "감히... 날 방해하느냐?"))
    assert t.chars["hc"].step_flags["0"]["boss"] == "engaged"
    t.feed(Reward("t", "9", "hc", "화염 저항 +10%"))
    assert t.chars["hc"].step_flags["0"]["boss"] == "killed"


def test_jiquani_sanctum_markers():
    g = Guide(parse_csv("id,area_name,quest\ng3_6_2,지콰니의 지성소,지코아틀\ng3_3,밀림 유적,다음"), "t")
    t = Tracker(g, encounters=ENC)
    feed(t, AreaEntered("t", "9", "G3_6_2", 38), LevelUp("t", "9", "a", "머서너리", 32))
    t.feed(NpcLine("t", "9", "알바", "이건 내가 지금껏 본 것 중에서 가장 큰 영혼 핵인데!"))
    assert t.chars["a"].step_flags["0"]["marker"] == "영혼 핵 발견"
    t.feed(NpcLine("t", "9", "알바", "영혼 핵이 충전됐어! 네가 가서 가져오지 않겠어?"))
    t.feed(NpcLine("t", "9", "알바", "이런. 이제 저 거대한 구조물에서 제거하기만 하면 되는데... 행운을 빌게!"))
    f = t.chars["a"].step_flags["0"]
    assert f["marker"] == "발전기 완료" and f["soon"]


def test_riverbank_mortimer_signals():
    g = Guide(parse_csv("id,area_name,quest\ng1_1,강둑,방아꾼 처치\ng1_town,클리어펠 야영지,렌리"), "t")
    t = Tracker(g, encounters=ENC)
    feed(t, AreaEntered("t", "9", "G1_1", 1), LevelUp("t", "9", "n", "소서리스", 2))
    t.feed(NpcLine("t", "9", "모티머", "거기 너! 도와다오!"))
    assert t.chars["n"].step_flags["0"].get("soon")
    t.feed(NpcLine("t", "9", "불어 터진 방아꾼", "반으로 잘라 주마!"))
    assert t.chars["n"].step_flags["0"]["boss"] == "engaged"
    t.feed(NpcLine("t", "9", "모티머", "잘했다! 안으로 들어와."))
    assert t.chars["n"].step_flags["0"]["boss"] == "killed"
