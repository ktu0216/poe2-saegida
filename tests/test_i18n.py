from poe2_overlay import i18n
from poe2_overlay.i18n import t


def test_translate_and_fallback():
    i18n.set_lang("en")
    try:
        assert t("세션 지도 {n}판", n=3) == "Session maps 3"
        assert i18n.act("액트 2") == "Act 2" and i18n.act("막간 3") == "Interlude 3"
        assert t("사전에 없는 문구") == "사전에 없는 문구"  # 번역이 없으면 한국어 그대로
    finally:
        i18n.set_lang("ko")
    assert t("세션 지도 {n}판", n=3) == "세션 지도 3판"


def test_resolve_language_from_log(tmp_path):
    # 로그 내용(마지막 지역 이름)으로: 카카오판도 영어로 바꿀 수 있다
    log = tmp_path / "KakaoClient.txt"
    log.write_text("2026/10/05 00:46:42 1 a [INFO Client 1] [SCENE] Set Source [클리어펠]\n"
                   "2026/10/05 00:46:42 1 a [INFO Client 1] [SCENE] Set Source [The Glade]\n"
                   "2026/10/05 00:46:43 1 a [INFO Client 1] [SCENE] Set Source [(null)]\n", encoding="utf-8")
    assert i18n.resolve("auto", log) == "en"
    # 내용이 없으면 파일 이름으로
    assert i18n.resolve("auto", tmp_path / "none" / "KakaoClient.txt") == "ko"
    assert i18n.resolve("auto", tmp_path / "none" / "Client.txt") == "en"
    assert i18n.resolve("en", log) == "en"


def test_english_data_files_load():
    from poe2_overlay import config
    from poe2_overlay.encounters import Encounters
    from poe2_overlay.guide import Guide
    from poe2_overlay.rewards import RewardTable, load_passive_sources
    assert config.data_file("rewards", "en").name == "rewards_en.json"
    assert len(RewardTable.load(config.data_file("rewards", "en")).slots) == 15
    assert len(load_passive_sources(config.data_file("quest_passives", "en"))) == 12
    assert Encounters.load(config.data_file("encounters", "en")).get("p1_5").bosses == ("Oswin, the Dread Warden",)
    g = Guide.load(config.resource_dir() / "guides" / "default_en.csv")
    assert len(g) == len(Guide.load(config.resource_dir() / "guides" / "default_ko.csv"))
    assert len(config.load_zone_tips(config.data_file("zone_tips", "en"))) == 85


def test_rewards_from_korean_log_show_in_english():
    # 카카오(한국어) 로그로 받은 보상 → 화면 영어 표에서도 받은 것으로
    from poe2_overlay import config
    from poe2_overlay.rewards import RewardTable
    table = RewardTable.load(config.data_file("rewards", "en"), config.data_file("rewards", "ko"))
    states = table.evaluate(["냉기 저항 +10%", "민첩 +5", "지능 +5", "힘 +5"])
    done = {s.slot.zone: s.got for s in states if s.done}
    assert done["g1_2"] == ["+10% to Cold Resistance"]
    assert done["g4_4_2"] == ["+5 to Dexterity", "+5 to Intelligence", "+5 to Strength"]


def test_rewards_mixed_languages():
    # 게임 언어를 중간에 바꾼 캐릭터: 한국어·영어 보상 기록이 섞여도 모두 받음으로
    from poe2_overlay import config
    from poe2_overlay.rewards import RewardTable
    for ui in ("ko", "en"):
        table = RewardTable.load(config.data_file("rewards", ui), config.data_file("rewards", "ko"),
                                 config.data_file("rewards", "en"))
        states = table.evaluate(["냉기 저항 +10%", "+40 to Spirit"])
        assert sum(s.done for s in states) == 2


def test_class_names_follow_screen_language():
    i18n.set_lang("en")
    try:
        assert i18n.cls("디사이플 오브 바라시타") == "Disciple of Varashta"
        assert i18n.cls("Titan") == "Titan"
    finally:
        i18n.set_lang("ko")
    assert i18n.cls("Disciple of Varashta") == "디사이플 오브 바라시타"
    assert i18n.cls("젬링 리저네어") == "젬링 리저네어"


def test_speedrun_guides_match_and_keep_passive_steps():
    # 스피드런 가이드: 한국어·영어가 같은 경로, 퀘스트 패시브 단계 표시용 문구가 남아 있어야 한다
    from poe2_overlay import config
    from poe2_overlay.guide import Guide
    from poe2_overlay.rewards import load_passive_sources
    for lang in ("ko", "en"):
        assert config.bundled_guide("speedrun", lang) is not None
    ko = Guide.load(config.bundled_guide("speedrun", "ko"))
    en = Guide.load(config.bundled_guide("speedrun", "en"))
    assert [s.zone for s in ko.steps] == [s.zone for s in en.steps]
    for lang, g in (("ko", ko), ("en", en)):
        for src in load_passive_sources(config.data_file("quest_passives", lang)):
            assert any(s.zone == src.zone and src.match in s.text for s in g.steps), (lang, src.zone)
