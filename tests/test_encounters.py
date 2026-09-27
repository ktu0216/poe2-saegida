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
