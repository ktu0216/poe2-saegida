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


def test_resolve_language_from_log():
    assert i18n.resolve("auto", r"C:\Daum Games\Path of Exile2\logs\KakaoClient.txt") == "ko"
    assert i18n.resolve("auto", r"C:\Steam\steamapps\common\Path of Exile 2\logs\Client.txt") == "en"
    assert i18n.resolve("en", r"KakaoClient.txt") == "en"


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
