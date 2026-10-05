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


def test_passive_points_mark_step():
    from poe2_overlay.logparse import PassivePoints
    from poe2_overlay.rewards import PassiveSource
    g = Guide(parse_csv("id,area_name,quest\ng1_11,사냥터,까마귀 종 처치"), "t")
    t = Tracker(g, encounters=ENC)
    t.passive_sources = [PassiveSource("g1_11", "", "까마귀 종")]
    feed(t, AreaEntered("t", "9", "G1_11", 10), LevelUp("t", "9", "a", "소서리스", 8))
    t.feed(PassivePoints("t", "9", 2, False))
    f = t.chars["a"].step_flags["0"]
    assert f["passive"] and f["boss"] == "killed"


def test_passive_in_town_marks_reward_step():
    from poe2_overlay.logparse import PassivePoints
    from poe2_overlay.rewards import PassiveSource
    g = Guide(parse_csv("id,area_name,quest\ng1_13_1,오검 농지,우나의 류트 찾기\ng1_13_2,오검 마을,도구\n"
                        "g1_town,클리어펠 야영지,우나와 렌리에게 보상 받기"), "t")
    t = Tracker(g, encounters=ENC)
    t.passive_sources = [PassiveSource("g1_town", "우나와 렌리", "우나의 류트")]
    feed(t, AreaEntered("t", "9", "G1_13_1", 12), LevelUp("t", "9", "a", "소서리스", 10),
         AreaEntered("t", "9", "G1_town", 15))  # 오검 마을 전에 마을로 가서 류트 전달
    t.feed(PassivePoints("t", "9", 2, False))
    c = t.chars["a"]
    assert c.cursor == 0 and c.step_flags["2"]["passive"] and "passive" not in c.step_flags.get("0", {})


def test_dialogue_after_kill_does_not_reengage():
    g = Guide(parse_csv("id,area_name,quest\ng1_15,오검 저택,지오너 처치\ng1_town,클리어펠 야영지,렌리"), "t")
    t = Tracker(g, encounters=ENC)
    feed(t, AreaEntered("t", "9", "G1_15", 15), LevelUp("t", "9", "a", "소서리스", 15))
    t.feed(NpcLine("t", "9", "악취 나는 늑대 지오너", "네 맥박이 빨라진다..."))
    t.feed(NpcLine("t", "9", "두건 쓴 자", "잠시나마 정신을 맑게 해 주지."))
    f = t.chars["a"].step_flags["0"]
    assert f["boss"] == "killed"
    for who, text in (("악취 나는 늑대 지오너", "광기가... 나의 존재를 삼켰다."), ("두건 쓴 자", "그 여자가 짐승을 어디로 데려갔지?"),
                      ("악취 나는 늑대 지오너", "그래... 그 여자를 찾아라.")):
        t.feed(NpcLine("t", "9", who, text))
        assert f["boss"] == "killed"


def test_rudja_kill_by_lisu_thanks():
    g = Guide(parse_csv("id,area_name,quest\ng2_10_2,모둔 광산,룻자 처치\ng2_town,아르듀라 카라반,마을"), "t")
    t = Tracker(g, encounters=ENC)
    feed(t, AreaEntered("t", "9", "G2_10_2", 18), LevelUp("t", "9", "a", "소서리스", 16))
    t.feed(NpcLine("t", "9", "공포의 기술자 룻자", "미쳤다고? 미친 게 뭔지 보여주지!"))
    t.feed(NpcLine("t", "9", "파리둔 탈주자 리수", "바람이 그대를 축복하길!"))
    assert t.chars["a"].step_flags["0"]["boss"] == "killed"


def test_silent_boss_killed_when_leaving_after_soon():
    g = Guide(parse_csv("id,area_name,quest\ng3_6_2,지콰니의 지성소,지코아틀\ng3_3,밀림 유적,다음"), "t")
    t = Tracker(g, encounters=ENC)
    feed(t, AreaEntered("t", "9", "G3_6_2", 38), LevelUp("t", "9", "a", "소서리스", 33))
    t.feed(NpcLine("t", "9", "알바", "이런. 이제 저 거대한 구조물에서 제거하기만 하면 되는데... 행운을 빌게!"))
    t.feed(AreaEntered("t", "9", "G3_town", 44))
    assert t.chars["a"].step_flags["0"]["boss"] == "killed"


def test_book_used_in_town_after_late_field_kill():
    from poe2_overlay.logparse import PassivePoints
    from poe2_overlay.rewards import PassiveSource
    g = Guide(parse_csv("id,area_name,quest\ng3_3,밀림 유적,은빛 주먹 처치\ng3_town,지구라트 야영지,정비\n"
                        "g3_16,아고라트,희생의 심장"), "t")
    t = Tracker(g, encounters=ENC)
    t.passive_sources = [PassiveSource("g3_3", "은빛 주먹", "은빛 주먹"), PassiveSource("g3_16", "", "희생의 심장")]
    feed(t, AreaEntered("t", "9", "G3_3", 34), LevelUp("t", "9", "a", "소서리스", 40))
    c = t.chars["a"]
    c.cursor = 2  # 이미 아고라트 단계까지 진행
    feed(t, AreaEntered("t", "9", "G3_3", 34), AreaEntered("t", "9", "G3_town", 44))
    t.feed(PassivePoints("t", "9", 2, False))
    assert c.step_flags["0"].get("passive") and not c.step_flags.get("2", {}).get("passive")


def test_doryani_signals():
    g = Guide(parse_csv("id,area_name,quest\ng3_17,검은 내실,도리아니 처치\ng3_town,지구라트 야영지,마을"), "t")
    t = Tracker(g, encounters=ENC)
    feed(t, AreaEntered("t", "9", "G3_17", 45), LevelUp("t", "9", "a", "소서리스", 42))
    t.feed(NpcLine("t", "9", "도리아니", "여기에 침입자가? 나푸앗지는...?"))
    f = t.chars["a"].step_flags["0"]
    assert "boss" not in f  # 입장 직후 대사는 전투가 아님
    t.feed(NpcLine("t", "9", "도리아니", "그래... 최후의 전야에 앗조아틀의 악마가 마침내 나를 찾아왔구나!"))
    assert f["boss"] == "engaged"
    t.feed(NpcLine("t", "9", "도리아니", "으윽... 어떻게 이런 일이... 그렇게 애썼는데. 그렇게 희생했는데..."))
    assert f["boss"] == "killed"


def test_tasks_count_trials_in_any_order():
    g = Guide(parse_csv("g4_4_1,히네코라의 눈,시험 3개\ng4_4_2,죽음의 전당,하얀 야마\n"), "t")
    t = Tracker(g, encounters=ENC)
    feed(t, AreaEntered("t", "1", "G4_4_1", 51), LevelUp("t", "1", "me", "머서너리", 47),
         NpcLine("t", "1", "마아타", "숲이 네 기개에 미소를 보낸다."),
         NpcLine("t", "1", "카옴", "나마후가 네 힘에 미소를 보낸다."),
         NpcLine("t", "1", "카옴", "나마후가 네 힘에 미소를 보낸다."))
    assert t.snapshot().flags["marker"] == "시험 2/3 (마아타 · 카옴)"
    feed(t, NpcLine("t", "1", "라키아타", "타살리오가 네 유연함에 미소를 보낸다."))
    assert t.snapshot().flags["marker"] == "시험 3/3 (마아타 · 카옴 · 라키아타)"
    assert "boss" not in t.snapshot().flags


def test_boss_line_after_death_does_not_reengage():
    g = Guide(parse_csv("g4_11_2,부족의 심장부,타바카이 처치\ng4_town,킹스마치,마을\n"), "t")
    t = Tracker(g, encounters=ENC)
    feed(t, AreaEntered("t", "1", "G4_11_2", 53), LevelUp("t", "1", "me", "머서너리", 51),
         NpcLine("t", "1", "타바카이", "또 네가 이해하지 못하는 일에 끼여드는군!"))
    assert t.snapshot().flags["boss"] == "engaged"
    feed(t, Death("t", "1", "me"), NpcLine("t", "1", "타바카이", "무로 돌아가라... 외지인..."))
    assert t.snapshot().flags["boss"] == "died"
    feed(t, AreaEntered("t", "1", "G4_town", 53), AreaEntered("t", "1", "G4_11_2", 53))
    assert t.snapshot().step.zone == "g4_11_2"  # 보스 전 마을 정비는 단계를 넘기지 않는다
    feed(t, NpcLine("t", "1", "타바카이", "또 네가 이해하지 못하는 일에 끼여드는군!"))
    assert t.snapshot().flags["boss"] == "engaged"  # 다시 들어와 싸우면 다시 전투 중


def test_unverified_boss_does_not_block_town_step():
    # 막간 보스(gate=false)는 말을 안 해도 마을에 가면 다음 단계로 넘어간다
    g = Guide(parse_csv("p2_1,카리 교차로,아크티 처치 후 마을\np2_town,카리 장터,리수 대화\n"), "t")
    t = Tracker(g, encounters=ENC)
    feed(t, AreaEntered("t", "1", "P2_1", 54), LevelUp("t", "1", "me", "머서너리", 54),
         AreaEntered("t", "1", "P2_town", 64))
    assert t.snapshot().step.zone == "p2_town"


def test_interlude_kill_line_and_death_taunt():
    g = Guide(parse_csv("p2_7,키마 저수지,아즈마디 처치\np2_town,카리 장터,마을\n"), "t")
    t = Tracker(g, encounters=ENC)
    feed(t, AreaEntered("t", "1", "P2_7", 56), LevelUp("t", "1", "me", "머서너리", 56),
         NpcLine("t", "1", "파리둔 왕자 아즈마디", "파리둔을 부흥시키리라!"),
         Death("t", "1", "me"), NpcLine("t", "1", "파리둔 왕자 아즈마디", "이렇게 내 유산이 시작한다."))
    assert t.snapshot().flags["boss"] == "died"
    feed(t, AreaEntered("t", "1", "P2_7", 56), NpcLine("t", "1", "파리둔 왕자 아즈마디", "나는 군단이다!"),
         NpcLine("t", "1", "파리둔 왕자 아즈마디", "왕위를 거부당한 왕자..."))
    assert t.snapshot().flags["boss"] == "killed"


def test_boss_outside_guide_step_tracked_for_compact():
    # 막간 단계 캐릭터가 액트 4 노래하는 암굴에 다시 가서 디아모라와 싸움 → 단계 상태는 그대로, 임시 상태로 전투 표시
    g = Guide(parse_csv("p3_town,풀숲,대화\np3_1,잿빛 수림,크리아 마을로\n"), "t")
    t = Tracker(g, encounters=ENC)
    feed(t, AreaEntered("t", "1", "P3_town", 50), LevelUp("t", "1", "me", "머서너리", 52),
         AreaEntered("t", "1", "G4_3_2", 52),
         NpcLine("t", "1", "죽음의 노래 디아모라", "내가 사랑하는 이들과 함께하러 왔니? 함께하게 될 거야!"))
    s = t.snapshot()
    assert s.step.zone == "p3_town" and not s.in_step_zone
    assert s.roam_flags.get("boss") == "engaged" and s.roam_boss == "죽음의 노래 디아모라"
    assert "boss" not in s.flags  # 가이드 단계의 상태는 건드리지 않는다
    feed(t, NpcLine("t", "1", "죽음의 노래 디아모라", "이렇게 끝날 우리가... 아니었는데."))
    assert t.snapshot().roam_flags.get("boss") == "killed"  # 디아모라의 마지막 대사 = 처치 (마티키 대사는 다시 잡을 때 안 나옴)
    feed(t, AreaEntered("t", "1", "G4_3_1", 52))
    assert t.snapshot().roam_flags == {}  # 지역을 옮기면 버린다


def test_english_boss_lines_parse_and_engage():
    # 영어 클라이언트: 화자 이름이 ASCII → 제목처럼 쓴 이름만 대사로 (기술 로그는 제외)
    p = "2026/10/05 19:13:47 1 a [INFO Client 1] "
    assert parse_line(p + "Beira of the Rotten Pack: Invader!") == NpcLine(
        "2026/10/05 19:13:47", "1", "Beira of the Rotten Pack", "Invader!")
    for tech in ("Tile hash: 1", "Queue file to download: x", "Abnormal disconnect: x", "Backup Web root: x"):
        assert parse_line(p + tech) is None
    enc = Encounters.load(resource_dir() / "guides" / "encounters_en.json")
    g = Guide(parse_csv("g1_2,Clearfell,Kill Beira\ng1_4,The Grelwood,next\n"), "t")
    t = Tracker(g, encounters=enc)
    feed(t, AreaEntered("t", "1", "G1_2", 2), LevelUp("t", "1", "me", "Mercenary", 2),
         parse_line(p + "Beira of the Rotten Pack: Invader!"))
    assert t.snapshot().flags["boss"] == "engaged"
