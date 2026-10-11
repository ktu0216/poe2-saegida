import pytest

from poe2_overlay import progress_code
from poe2_overlay.config import resource_dir
from poe2_overlay.guide import Guide, parse_csv
from poe2_overlay.logparse import AreaEntered, LevelUp, NewCharacter, Played, parse_line
from poe2_overlay.rewards import RewardTable, load_passive_sources
from poe2_overlay.timing import CAMPAIGN, ENDGAME, personal_bests, timer_view
from poe2_overlay.tracker import Character, Tracker


def feed(t, *events):
    for e in events:
        t.feed(e)


def test_code_round_trip_and_messenger_whitespace():
    c = Character(name="tu_x", cls="Lich", level=43, cursor=75, play_seconds=24125.0,
                  splits={"액트 1": 0.0, "액트 2": 4998.0}, rewards=["+10% to Cold Resistance"],
                  gear={"주 손": "Item Class: Wands\nRarity: Rare\nX\n"}, step_flags={"74": {"boss": "killed"}})
    code = progress_code.encode(c, "전염 리치")
    assert code.startswith(progress_code.PREFIX)
    # 메신저에 붙였다가 다시 복사하면 앞뒤 글·줄바꿈이 섞인다
    pasted = "나에게: " + code[:40] + "\n" + code[40:] + " \n"
    got, build = progress_code.decode(pasted)
    assert got.to_dict() == c.to_dict() and build == "전염 리치"
    with pytest.raises(ValueError):
        progress_code.decode("그냥 글")
    with pytest.raises(ValueError):
        progress_code.decode(progress_code.PREFIX + "깨진코드")


def test_merge_appends_play_done_on_this_pc_before_paste():
    # 다른 PC 에서 액트 2까지 (플레이 1000초) → 이 PC 에서 코드 없이 액트 3 을 300초 하다가 붙여넣음
    imp = Character(name="tu_x", level=30, cursor=40, play_seconds=1000.0, splits={"액트 1": 0.0, "액트 2": 500.0},
                    rewards=["+10% to Cold Resistance"], passive_points=8, last_seen="2026/10/10 01:00:00")
    local = Character(name="tu_x", level=33, cursor=55, zone="g3_3", play_seconds=300.0, splits={"액트 3": 0.0},
                      rewards=["+10% to Fire Resistance"], passive_points=2, partial_from="액트 3",
                      last_seen="2026/10/11 01:00:00")
    c = progress_code.merge(imp, local)
    assert c.play_seconds == 1300.0 and c.splits == {"액트 1": 0.0, "액트 2": 500.0, "액트 3": 1000.0}
    assert c.rewards == ["+10% to Cold Resistance", "+10% to Fire Resistance"] and c.passive_points == 10
    assert c.level == 33 and c.cursor == 55 and c.zone == "g3_3" and not c.partial_from and c.partial_ack
    # 이 PC 기록이 없거나 코드보다 오래됐으면 코드 그대로
    assert progress_code.merge(imp, None).play_seconds == 1000.0


def test_fill_previous_rewards_and_quest_passives():
    g = Guide.load(resource_dir() / "guides" / "default_en.csv")
    rewards = RewardTable.load(resource_dir() / "guides" / "rewards_en.json")
    sources = load_passive_sources(resource_dir() / "guides" / "quest_passives_en.json")
    cursor = next(s.index for s in g.steps if s.zone == "g3_17")  # 도리아니 단계: 액트 1~3 을 지나옴
    c = Character(name="tu_x", cursor=cursor, rewards=["+10% to Cold Resistance"])  # 베이라 보상만 로그로 받음
    done = frozenset(i for i, st in enumerate(rewards.evaluate(c.rewards)) if st.got)
    n, pts = progress_code.fill_previous(c, g.steps, rewards.slots, sources, done)
    acts_1_3 = [i for i, s in enumerate(rewards.slots) if s.act in ("액트 1", "액트 2", "액트 3")]
    assert n == len(acts_1_3) - 1 and 0 not in c.assumed_slots  # 베이라 칸은 이미 받음
    assert pts == 12 and c.passive_points == 12 and c.weapon_set_points == 12  # 까마귀 종·류트·카발라·편지·실버피스트·피의 희생
    assert progress_code.fill_previous(c, g.steps, rewards.slots, sources, done) == (0, 0)  # 두 번 눌러도 그대로


def test_played_line():
    p = "2026/10/11 04:08:58 1 a [INFO Client 1] "
    assert parse_line(p + ": You have played for 8 hours, 31 minutes, and 47 seconds.") == Played(
        "2026/10/11 04:08:58", "1", 30707)
    assert parse_line(p + ": You have played for 1 day, 1 hour, 1 minute, and 1 second.").seconds == 90061
    assert parse_line(p + ": You have played for 12 seconds.").seconds == 12
    # 한국어 클라이언트 (2026-10-11 로그): "시" = 시간
    assert parse_line(p + ": 14시, 23분, 30초 동안 플레이했습니다.").seconds == 14 * 3600 + 23 * 60 + 30
    assert parse_line(p + ": 1일, 2시, 3분, 4초 동안 플레이했습니다.").seconds == 86400 + 7200 + 180 + 4


def test_mid_campaign_character_is_partial_and_skipped_for_pb():
    g = Guide(parse_csv("g1_1,riverbank,a\ng3_3,Jungle Ruins,b\ng3_town,camp,c\ng4_2_1,Kedge Bay,d\n"), "t")
    t = Tracker(g)
    feed(t, AreaEntered("2026/10/11 01:00:00", "1", "G3_3", 34), LevelUp("2026/10/11 01:00:05", "1", "tu_pc", "Lich", 35),
         Played("2026/10/11 01:00:10", "1", 30000))
    c = t.chars["tu_pc"]
    assert c.partial_from == "액트 3" and c.played_seconds == 30000
    # 새 캐릭터(튜토리얼 줄)나 강둑에서 시작한 캐릭터는 처음부터 잰 기록
    t2 = Tracker(g)
    feed(t2, AreaEntered("t", "2", "G1_1", 1), NewCharacter("t", "2"), LevelUp("t", "2", "fresh", "Witch", 2))
    assert t2.chars["fresh"].partial_from == ""
    # 중간부터 잡힌 액트와 캠페인 전체는 PB 로 쓰지 않는다 (다음 액트부터는 온전한 구간)
    c.splits = {"액트 3": 0.0, "액트 4": 3000.0, ENDGAME: 7000.0}
    c.play_seconds = 7000.0
    pbs = personal_bests([c])
    assert "액트 3" not in pbs and pbs["액트 4"] == 4000.0 and CAMPAIGN not in pbs
    assert all(r[0] != CAMPAIGN for r in timer_view(c, {}).rows)
