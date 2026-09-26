from poe2_overlay.logparse import Afk, AreaEntered, LevelUp, LoginConnect, parse_line
from poe2_overlay.timing import personal_bests, timer_view
from poe2_overlay.tracker import Tracker

from test_core import GUIDE


def ev_area(ts, code, pid="1"):
    return AreaEntered(f"2026/09/27 {ts}", pid, code, 1)


def test_parse_afk():
    line = "2026/09/27 00:58:20 1 a [INFO Client 26920] : 자리 비움 모드를 설정했습니다. \"x\"을(를) 자동으로 답신합니다."
    assert parse_line(line) == Afk("2026/09/27 00:58:20", "26920", True)


def test_play_time_excludes_afk_and_logout():
    t = Tracker(GUIDE)
    t.feed(ev_area("01:00:00", "G1_1"))
    t.feed(LevelUp("2026/09/27 01:05:00", "1", "a", "워리어", 2))       # +5분
    t.feed(Afk("2026/09/27 01:06:00", "1", True))                         # +1분
    t.feed(Afk("2026/09/27 01:36:00", "1", False))                        # 자리 비움 30분 제외
    t.feed(ev_area("01:40:00", "G1_town"))                                # +4분
    t.feed(LoginConnect("2026/09/27 01:41:00", "1"))                      # +0 (세션 끊김)
    t.feed(ev_area("02:41:00", "G1_town"))                                # 로그아웃 1시간 제외
    assert t.chars["a"].play_seconds == 10 * 60


def test_act_splits_and_pb():
    t = Tracker(GUIDE)
    t.feed(ev_area("01:00:00", "G1_1"))
    t.feed(LevelUp("2026/09/27 01:01:00", "1", "old", "워리어", 2))
    t.feed(ev_area("01:20:00", "G1_town"))
    t.feed(ev_area("01:40:00", "G2_1"))       # 액트 1 = 40분
    t.feed(ev_area("02:00:00", "G1_1", pid="2"))
    t.feed(LevelUp("2026/09/27 02:01:00", "2", "new", "워리어", 2))
    t.feed(ev_area("02:30:00", "G1_town", pid="2"))
    pbs = personal_bests(t.chars.values(), exclude="new")
    assert pbs == {"액트 1": 40 * 60}
    view = timer_view(t.chars["new"], pbs, live_extra=60)
    assert view.act == "액트 1" and view.act_time == 31 * 60 and view.pb == 40 * 60
