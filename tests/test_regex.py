from poe2_overlay.config import resource_dir
from poe2_overlay.regex import RegexBook

BOOK = RegexBook.load(resource_dir() / "guides" / "regex_ko.json")


def test_build_name_wins_over_class():
    r = BOOK.select("Act 1 & 2 (Pre-Ascend) - [0.5.5] Navira'", "머서너리", "액트 1")
    assert r.name == "바라시타"
    r = BOOK.select("LvL 1~42 - [POE2 0.5.5] 젬링 유탄 ��", "소서리스", "액트 1")
    assert r.name == "유탄 스타터"


def test_class_fallback_and_none():
    assert BOOK.select("", "머서너리", "액트 2").name == "유탄 스타터"
    assert BOOK.select("", "워리어", "액트 1").name == "쉴드 스미스"
    assert BOOK.select("", "몽크", "액트 1") is None


def test_vendor_line():
    assert BOOK.vendor_spoke("2026/09/27 02:30:45 1 a [INFO Client 25804] 렌리: 둘러보게나.")
    assert not BOOK.vendor_spoke("2026/09/27 02:30:45 1 a [INFO Client 25804] 불어 터진 방아꾼: 죽어라!")
    assert not BOOK.vendor_spoke("2026/09/27 02:30:45 1 a [INFO Client 25804] #렌리: 채팅")


def test_english_regex_rules_and_vendors():
    from poe2_overlay.config import data_file
    book = RegexBook.load(data_file("regex", "en"))
    assert data_file("regex", "en").name == "regex_en.json"
    assert book.select("", "Mercenary", "Act 1").name == "Grenade starter"
    assert book.select("Gemling Twister", "Mercenary", "Act 1").name == "Gemling Twister"
    assert book.vendor_spoke("2026/10/05 19:12:13 1 a [INFO Client 26348] Renly: Take a look.")
    ko = RegexBook.load(data_file("regex", "ko"))
    assert [r.build for r in book.rules] == [r.build for r in ko.rules]  # 한·영 같은 규칙


def test_search_text_quotes_regex_with_spaces():
    # 띄어쓰기가 있으면 게임이 조각마다 AND 로 찾으므로 따옴표로 감싼다 (2026-10-09 신발 이동 속도가 안 잡힘)
    from poe2_overlay.config import data_file
    book = RegexBook.load(data_file("regex", "en"))
    lich = book.select("전염 리치 1. 액트 1", "Witch", "Act 1")
    assert lich.search_text == r'"\d.+life|\d+% i.+mov|d Spell D|os D|ell s|m En"'
    assert book.select("", "Mercenary", "Act 1").search_text.startswith('"!quiver" ')  # 이미 따옴표
    assert book.select("Navira", "", "Act 1").search_text == '"spell sk|minion|allies|spirit|movement"'
    assert book.select("Shield Wall", "", "Act 1").search_text == "to.att|speed|melee|leech|tower"  # 띄어쓰기 없음


def test_deadeye_act1_and_later_rules():
    # Fubgun 레벨링 가이드: 액트 1과 액트 2부터 정규식이 다르다 (acts 로 고름), 전직 이름 Deadeye 로도 고름
    from poe2_overlay.config import data_file
    en = RegexBook.load(data_file("regex", "en"))
    assert en.select("얼음 데드아이 1. Lv 1-14", "Ranger", "액트 1").name == "Ice Shot Deadeye (Act 1)"
    assert en.select("얼음 데드아이 2. Lv 15-23", "Ranger", "액트 2").name == "Ice Shot Deadeye"
    assert en.select("", "Deadeye", "막간 1").name == "Ice Shot Deadeye"
    assert "Bow Skill" in en.select("", "Deadeye", "액트 3").regex  # 복사 원문의 'Bow 스위치'(자동 번역) 바로잡음
    assert BOOK.select("", "데드아이", "액트 2").name == "얼음 데드아이"
