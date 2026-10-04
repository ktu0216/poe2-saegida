from datetime import datetime

from poe2_overlay import endgame
from poe2_overlay.config import resource_dir
from poe2_overlay.encounters import Encounters
from poe2_overlay.guide import Guide, parse_csv
from poe2_overlay.logparse import AreaEntered, Death, LevelUp, NpcLine
from poe2_overlay.tracker import Tracker

BOSSES = endgame.EndgameBosses.load(resource_dir() / "guides" / "endgame_bosses_ko.json")


def tracker():
    t = Tracker(Guide(parse_csv("g_endgame_town,지구라트 피난처,맵핑\n"), "t"),
                encounters=Encounters.load(resource_dir() / "guides" / "encounters_ko.json"))
    t.endgame = BOSSES
    t.feed(AreaEntered("2026/10/04 20:00:00", "1", "HideoutShoreline", 65, "1"))
    t.feed(LevelUp("2026/10/04 20:00:01", "1", "me", "리저네어", 90))
    return t


def test_map_runs_same_seed_is_one_run_and_time_adds_up():
    t = tracker()
    for ts, code, seed in (("20:01:00", "MapCrypt", "11"), ("20:05:00", "HideoutShoreline", "1"),
                           ("20:06:00", "MapCrypt", "11"), ("20:08:00", "HideoutShoreline", "1"),
                           ("20:10:00", "MapWillow", "22")):
        t.feed(AreaEntered("2026/10/04 " + ts, "1", code, 80, seed))
    t.feed(Death("2026/10/04 20:11:00", "1", "me"))
    c = t.chars["me"]
    s = endgame.summary(c, BOSSES, datetime(2026, 10, 4, 20, 12, 0))
    assert s.maps == 2 and s.total_maps == 2 and s.deaths == 1
    assert s.avg_secs == 6 * 60  # 크립트: 4분 + 2분 (윌로는 진행 중이라 평균에서 뺌)
    assert s.cur_name == "mapwillow" and s.cur_secs == 120


def test_pinnacle_tries_kills_deaths():
    t = tracker()
    t.feed(AreaEntered("2026/10/04 21:00:00", "1", "MapUberBoss_Monolith", 82, "5"))
    t.feed(Death("2026/10/04 21:01:00", "1", "me"))
    t.feed(AreaEntered("2026/10/04 21:01:10", "1", "MapUberBoss_Monolith", 82, "6"))
    t.feed(NpcLine("2026/10/04 21:03:00", "1", "도리아니", "살아남았군. 잘했다."))
    t.feed(NpcLine("2026/10/04 21:03:05", "1", "도리아니", "살아남았군. 잘했다."))
    s = endgame.summary(t.chars["me"], BOSSES)
    assert s.bosses == [("재의 중재자", 2, 1, 1, True)]
    assert s.maps == 0  # 보스 판은 지도 수에 넣지 않는다


def test_old_runs_are_not_this_session():
    t = tracker()
    t.feed(AreaEntered("2026/10/04 20:01:00", "1", "MapCrypt", 80, "11"))
    t.feed(AreaEntered("2026/10/04 20:05:00", "1", "HideoutShoreline", 65, "1"))
    s = endgame.summary(t.chars["me"], BOSSES, datetime(2026, 10, 5, 9, 0, 0))
    assert s.maps == 0 and s.total_maps == 1
