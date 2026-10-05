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
