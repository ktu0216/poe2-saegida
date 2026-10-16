import json
from pathlib import Path

import pytest

from poe2_overlay.trade import (Query, RateLimited, RateLimiter, TradeClient, TradeData, build_query, price_text,
                                summary)
from test_items import BOOTS_EQUIPPED_KO, CROSSBOW, RING

# 카카오 거래소 /data/stats·static·items 에서 테스트 아이템에 필요한 것만 뽑은 것 (2026-10-17)
DATA = TradeData.from_json(json.loads((Path(__file__).parent / "fixtures" / "trade_ko_min.json").read_text(encoding="utf-8")))

SLIVERTONGUE = """아이템 종류: 활
아이템 희귀도: 고유
슬리버텅
맹신자 활
--------
물리 피해: 78-113 (augmented)
화염 피해: 13-16 (fire)
치명타 명중 확률: 10.20% (augmented)
초당 공격 횟수: 1.20
--------
요구 사항: 레벨 39, 70 민첩
--------
홈: S S
--------
아이템 레벨: 81
--------
화염 피해 13~16 추가 (rune)
민첩 +12 (rune)
--------
{ 고유 속성 부여 — 피해, 물리, 공격 }
물리 피해 47(40-48)~66(65-72) 추가
{ 고유 속성 부여 — 공격, 치명타 }
치명타 확률 +5.2(4-6)%
{ 고유 속성 부여 — 공격 }
화살이 갈라짐 — 변경이 불가능한 값
--------
백 개의 눈먼 머리가 공기 속 사냥감의 냄새를 맡다.
"""


def on(q: Query) -> dict:
    return {f.key: (f.min, f.max) for f in q.filters if f.enabled}


def test_boots_search_uses_pseudo_totals_and_level():
    q = build_query(BOOTS_EQUIPPED_KO, DATA, char_level=45)
    assert q.category == "armour.boots" and q.rarity == "rare" and q.base == "도마뱀비늘 장화"
    assert on(q) == {"pseudo.pseudo_increased_movement_speed": (18.0, None),
                     "pseudo.pseudo_total_attributes": (17.0, None), "lvl": (None, 45.0)}
    body = q.body()["query"]
    assert "name" not in body and "type" not in body  # 희귀는 이름이 아니라 카테고리·옵션으로
    assert body["filters"]["type_filters"]["filters"]["rarity"] == {"option": "nonunique"}
    assert body["filters"]["req_filters"]["filters"]["lvl"] == {"max": 45.0}
    assert {"id": "pseudo.pseudo_increased_movement_speed", "value": {"min": 18.0}} in body["stats"][0]["filters"]


def test_magic_weapon_base_and_dps_filter():
    q = build_query(CROSSBOW, DATA)
    assert q.base == "팽팽한 석궁" and q.category == "weapon.crossbow"
    assert on(q) == {"dps": (23.0, None)}  # 냉기 피해·공격 속도 옵션은 DPS 에 들어 있어 끔
    labels = {f.label: f.enabled for f in q.filters}
    assert labels["공격 속도 5% 증가"] is False and labels["냉기 피해 3~5 추가"] is False


def test_ring_resist_line_maps_to_total_resistance():
    q = build_query(RING, DATA)
    assert on(q) == {"pseudo.pseudo_total_resistance": (6.3, None)}
    assert any(f.label == "화염 저항 +7%" and not f.enabled for f in q.filters)


def test_unique_searches_by_name_with_mods_listed_off():
    q = build_query(SLIVERTONGUE, DATA, char_level=45, profile="attack")
    body = q.body()["query"]
    assert body["name"] == "슬리버텅" and body["type"] == "맹신자 활"
    assert body["filters"]["type_filters"]["filters"]["rarity"] == {"option": "unique"}
    assert on(q) == {}
    groups = {f.label: f.ids[0].split(".")[0] for f in q.filters}
    assert groups["민첩 +12"] == "rune" and groups["화살이 갈라짐"] == "explicit"


def test_not_gear_is_unsupported():
    q = build_query("아이템 종류: 화폐\n아이템 희귀도: 화폐\n엑잘티드 오브\n--------\n", DATA)
    assert q.unsupported


def test_rate_limiter_follows_headers():
    rl = RateLimiter()
    assert rl.wait_time("search", now=0) == 0
    rl.record("search", now=0)
    assert rl.wait_time("search", now=1) == pytest.approx(4)  # 규칙을 모를 때: 5초에 1번
    rl.update("search", {"X-Rate-Limit-Rules": "Ip", "X-Rate-Limit-Ip": "5:10:60,15:60:300",
                         "X-Rate-Limit-Ip-State": "5:10:0,5:60:0"}, now=1)
    assert rl.wait_time("search", now=2) > 5  # 서버가 센 5번이 10초 창을 채움
    rl.update("search", {"X-Rate-Limit-Rules": "Ip", "X-Rate-Limit-Ip": "5:10:60",
                         "X-Rate-Limit-Ip-State": "6:10:60"}, now=3)
    assert rl.wait_time("search", now=4) >= 59  # 차단 중


def test_client_search_fetch_cache_and_limit():
    calls = []

    def opener(url, data):
        calls.append(url)
        head = {"X-Rate-Limit-Rules": "Ip", "X-Rate-Limit-Ip": "5:10:60", "X-Rate-Limit-Ip-State": "1:10:0"}
        if "/search/" in url:
            return 200, head, json.dumps({"id": "Q1", "total": 3, "result": ["a", "b", "c"]}).encode()
        listing = lambda amt, cur: {"listing": {"price": {"amount": amt, "currency": cur}, "indexed": "2026-10-16T00:00:00Z",
                                                "account": {"name": "x"}}}
        return 200, head, json.dumps({"result": [listing(1, "chaos"), listing(4, "chaos"), listing(4, "chaos")]}).encode()

    client = TradeClient("kakao", opener=opener)
    q = build_query(BOOTS_EQUIPPED_KO, DATA, char_level=45)
    res = client.search("HC Forbidden Rites", q)
    assert res.total == 3 and [l.amount for l in res.listings] == [1, 4, 4]
    assert calls[0].endswith("/api/trade2/search/poe2/HC%20Forbidden%20Rites")
    assert calls[1].endswith("/api/trade2/fetch/a,b,c?query=Q1")
    assert res.url == "https://poe.kakaogames.com/trade2/search/poe2/HC%20Forbidden%20Rites/Q1"
    low, mid, groups = summary(res)
    assert (low.amount, mid.amount) == (1, 4) and groups == [("chaos", 1, 4, 3)]
    assert price_text(4, "chaos") == "4 카오스" and price_text(1, "exalted", lang="en") == "1 ex"
    assert client.search("HC Forbidden Rites", q) is res and len(calls) == 2  # 같은 검색은 캐시
    q.filters[0].min = 10
    with pytest.raises(RateLimited):  # 방금 보낸 검색 뒤 바로 또 → 기다려야 하면 보내지 않음
        client.limiter.policies["search"] = client.limiter.policies["search"][:0] or []
        client.limiter.blocked_until = 10 ** 9
        client.search("HC Forbidden Rites", q)
