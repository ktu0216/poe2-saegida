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
    assert BOOK.select("", "워리어", "액트 1") is None


def test_vendor_line():
    assert BOOK.vendor_spoke("2026/09/27 02:30:45 1 a [INFO Client 25804] 렌리: 둘러보게나.")
    assert not BOOK.vendor_spoke("2026/09/27 02:30:45 1 a [INFO Client 25804] 불어 터진 방아꾼: 죽어라!")
    assert not BOOK.vendor_spoke("2026/09/27 02:30:45 1 a [INFO Client 25804] #렌리: 채팅")
