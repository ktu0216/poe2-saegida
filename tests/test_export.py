import xml.etree.ElementTree as ET

from poe2_overlay import export, updater
from poe2_overlay.timing import TimerView


def test_lss_is_cumulative_and_valid_xml():
    tv = TimerView("막간 1", 100.0, 1000.0, None,
                   [("액트 1", 600.0, True, None), ("액트 2", 1200.0, True, None),
                    ("액트 3", 300.0, False, None), ("캠페인 전체", 1800.0, True, None)])
    root = ET.fromstring(export.to_lss("Exile", tv, {"액트 1": 500.0}))
    segs = list(root.iter("Segment"))
    assert [s.find("Name").text for s in segs] == ["액트 1", "액트 2"]  # 끝난 구간만, 캠페인 합계 제외
    pb = [s.find("SplitTimes/SplitTime/RealTime").text for s in segs]
    assert pb == ["00:10:00.0000000", "00:30:00.0000000"]  # 누적
    assert segs[0].find("BestSegmentTime/RealTime").text == "00:08:20.0000000"  # 더 빠른 기록이 골드


def test_update_version_compare_and_release_parsing():
    assert updater.is_newer("0.1.1", "0.1.0") and not updater.is_newer("0.1.0", "0.1.0")
    assert updater.is_newer("v1.0.0", "0.9.9")
    rel = updater.parse_release({"tag_name": "v0.2.0", "html_url": "u", "assets": [
        {"name": "poe2-saegida-0.2.0-portable.zip", "browser_download_url": "z", "size": 5},
        {"name": "poe2-saegida-setup-0.2.0.exe", "browser_download_url": "s", "size": 9, "digest": "sha256:ab"}]})
    assert (rel.version, rel.setup_url, rel.setup_size, rel.sha256) == ("0.2.0", "s", 9, "ab")
    assert updater.parse_release({"tag_name": "v9", "prerelease": True}) is None


def test_league_for_mode_strips_wrong_hc():
    from poe2_overlay.tracker import league_for_mode
    assert league_for_mode("HC Forbidden Rites", "소프트코어") == "Forbidden Rites"
    assert league_for_mode("HC Forbidden Rites", "하드코어") == "HC Forbidden Rites"
    assert league_for_mode("HC Forbidden Rites", "") == "HC Forbidden Rites"  # 모드를 모르면 그대로


def test_card_date_is_campaign_finish_not_last_played():
    from poe2_overlay.export import finished_on
    from poe2_overlay.tracker import Character
    c = Character("me", last_seen="2026/10/05 19:30:02",
                  eg_maps=[{"start": "2026/09/07 10:00:00"}, {"start": "2026/09/06 20:32:22"}])
    assert finished_on(c) == "2026/09/06"  # 첫 엔드게임 지도
    c.campaign_done = "2026/09/06 20:30:00"
    assert finished_on(c) == "2026/09/06"
    assert finished_on(Character("x", last_seen="2026/10/01 01:00:00")) == "2026/10/01"  # 기록이 없으면 마지막 플레이


def test_tracker_records_campaign_done_time():
    from poe2_overlay.guide import Guide, parse_csv
    from poe2_overlay.logparse import AreaEntered, LevelUp
    from poe2_overlay.tracker import Tracker
    t = Tracker(Guide(parse_csv("p1_6,홀튼 영지,보스\ng_endgame_town,지구라트 피난처,끝\n"), "t"))
    for e in (AreaEntered("2026/09/06 20:00:00", "1", "P1_6", 60), LevelUp("2026/09/06 20:00:01", "1", "me", "머서너리", 60),
              AreaEntered("2026/09/06 20:32:22", "1", "MapFortress", 65),
              AreaEntered("2026/10/05 19:30:02", "1", "MapOasis", 66)):
        t.feed(e)
    assert t.chars["me"].campaign_done == "2026/09/06 20:32:22"


def test_campaign_ends_at_ziggurat_refuge():
    # 막간을 끝내고 지구라트 피난처에 들어가면 캠페인 시간이 멈춘다 (첫 지도까지 기다리지 않음)
    from poe2_overlay.guide import Guide, parse_csv
    from poe2_overlay.logparse import AreaEntered, LevelUp
    from poe2_overlay.tracker import Tracker
    t = Tracker(Guide(parse_csv("p1_town,피난처,복귀\ng4_town,킹스마치,두건 쓴 자\ng_endgame_town,지구라트 피난처,끝\n"), "t"))
    for e in (AreaEntered("2026/10/07 01:33:08", "1", "P1_Town", 64), LevelUp("2026/10/07 01:33:09", "1", "me", "머서너리", 59),
              AreaEntered("2026/10/07 01:33:48", "1", "G4_town", 53),
              AreaEntered("2026/10/07 01:34:42", "1", "G_Endgame_Town", 65)):
        t.feed(e)
    c = t.chars["me"]
    assert "엔드게임" in c.splits and c.campaign_done == "2026/10/07 01:34:42"
