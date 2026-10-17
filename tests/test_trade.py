import json
from pathlib import Path

import pytest

from poe2_overlay.trade import (Filter, Query, RateLimited, RateLimiter, TradeClient, TradeData, bait, build_query, ex_text,
                                price_text, summary)
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
    return {f.key: (f.min, f.max) for f in q.filters if f.enabled and f.kind != "opt"}


def test_boots_search_uses_pseudo_totals_and_level():
    q = build_query(BOOTS_EQUIPPED_KO, DATA, char_level=45)
    assert q.category == "armour.boots" and q.rarity == "rare" and q.base == "도마뱀비늘 장화"
    assert on(q) == {"pseudo.pseudo_increased_movement_speed": (20.0, None),  # 끼고 있는 수치 그대로
                     "pseudo.pseudo_total_attributes": (19.0, None), "lvl": (None, 45.0)}
    body = q.body()["query"]
    assert "name" not in body and "type" not in body  # 희귀는 이름이 아니라 카테고리·옵션으로
    assert body["filters"]["type_filters"]["filters"]["rarity"] == {"option": "nonunique"}
    assert body["filters"]["req_filters"]["filters"]["lvl"] == {"max": 45.0}
    assert {"id": "pseudo.pseudo_increased_movement_speed", "value": {"min": 20.0}} in body["stats"][0]["filters"]


def test_magic_weapon_base_and_dps_filter():
    q = build_query(CROSSBOW, DATA)
    assert q.base == "팽팽한 석궁" and q.category == "weapon.crossbow"
    # 마법: 베이스 이름 + DPS (냉기 피해·공격 속도 옵션은 DPS 에 들어 있어 끔), 아이템 레벨은 꺼 둠
    assert on(q) == {"type": (None, None), "dps": (26.0, None)}
    assert q.body()["query"]["type"] == "팽팽한 석궁"
    labels = {f.label: f.enabled for f in q.filters}
    assert labels["공격 속도 5% 증가"] is False and labels["냉기 피해 3~5 추가"] is False
    assert labels["아이템 레벨"] is False


def test_normal_base_uses_item_level_not_dps():
    white = CROSSBOW.replace("아이템 희귀도: 마법", "아이템 희귀도: 일반").replace("서리 내린 팽팽한 석궁 - 스킬", "팽팽한 석궁")
    q = build_query(white, DATA)
    assert on(q) == {"type": (None, None), "ilvl": (6.0, None)}  # 제작 베이스: 베이스 + 아이템 레벨
    assert q.body()["query"]["filters"]["type_filters"]["filters"]["ilvl"] == {"min": 6.0}


def test_toggling_filters_changes_body():
    q = build_query(BOOTS_EQUIPPED_KO, DATA, char_level=45)
    q.filters[0].enabled = False  # 이동 속도 끄기
    q.status, q.indexed = "available", ""
    body = q.body()["query"]
    ids = [f["id"] for f in body["stats"][0]["filters"]]
    assert "pseudo.pseudo_increased_movement_speed" not in ids
    assert body["status"] == {"option": "available"} and "indexed" not in body["filters"]["trade_filters"]["filters"]


def test_ring_resist_line_maps_to_total_resistance():
    q = build_query(RING, DATA)
    assert on(q) == {"type": (None, None), "pseudo.pseudo_total_resistance": (7.0, None)}
    assert any(f.label == "화염 저항 +7%" and not f.enabled for f in q.filters)


def test_unique_searches_by_name_with_mods_listed_off():
    q = build_query(SLIVERTONGUE, DATA, char_level=45, profile="attack")
    body = q.body()["query"]
    assert body["name"] == "슬리버텅" and body["type"] == "맹신자 활"
    assert body["filters"]["type_filters"]["filters"]["rarity"] == {"option": "unique"}
    assert on(q) == {}
    groups = {f.label: f.ids[0].split(".")[0] for f in q.filters if f.kind == "stat"}
    assert groups["민첩 +12"] == "rune" and groups["화살이 갈라짐"] == "explicit"


def test_currency_goes_to_exchange_and_gems_by_level():
    q = build_query("아이템 종류: 화폐\n아이템 희귀도: 화폐\n신성한 오브\n--------\n", DATA)
    assert q.exchange == "divine" and not q.unsupported
    gem = "아이템 종류: 스킬 젬\n아이템 희귀도: 젬\n얼음 화살\n--------\n레벨: 18\n품질: +20%\n"
    g = build_query(gem, DATA)
    assert on(g) == {"type": (None, None), "gem_level": (18.0, None), "quality": (20.0, None)}
    body = g.body()["query"]
    assert body["type"] == "얼음 화살" and body["filters"]["misc_filters"]["filters"]["gem_level"] == {"min": 18.0}
    assert build_query("아이템 종류: 퀘스트 아이템\n아이템 희귀도: 퀘스트\n무언가\n--------\n", DATA).unsupported


def test_english_text_on_kakao_translates_names():
    ko = {"items": {"result": [{"id": "weapon", "entries": [{"type": "맹신자 활"}, {"type": "맹신자 활", "name": "슬리버텅"}]}]}}
    en = {"items": {"result": [{"id": "weapon", "entries": [{"type": "Zealot Bow"}, {"type": "Zealot Bow", "name": "Slivertongue"}]}]},
          "stats": {"result": []}}
    d = TradeData.from_json(ko, en)
    assert d.name("Slivertongue") == "슬리버텅" and d.name("Zealot Bow") == "맹신자 활" and "Zealot Bow" in d.bases


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


def test_exchange_unit_price_and_rates_on_listings():
    def offer(pay, get):
        return {"listing": {"offers": [{"exchange": {"currency": "exalted", "amount": pay},
                                        "item": {"currency": "x", "amount": get}}]}}
    calls, sent = [], []

    def opener(url, data):
        calls.append(url)
        head = {"X-Rate-Limit-Rules": "Ip", "X-Rate-Limit-Ip": "5:15:60", "X-Rate-Limit-Ip-State": "1:15:0"}
        if "poe.ninja" in url:
            if "type=Runes" in url:
                return 200, {}, json.dumps({"core": {"rates": {"exalted": 300}}, "lines": [{"id": "rune_x", "primaryValue": 0.1}]}).encode()
            return 500, {}, b""  # Currency: 실패 → 교환소 중간값으로
        if "/api/trade2/exchange/" in url:
            sent.append(data)
            want = json.loads(data)["query"]["want"][0]
            pays = {"divine": [(300, 1), (320, 1), (400, 1)], "chaos": [(1, 1), (2, 1), (2, 1)]}.get(want, [])
            return 200, head, json.dumps({"id": "E1", "total": 3, "result": {str(i): offer(*o) for i, o in enumerate(pays)}}).encode()
        if "/search/" in url:
            return 200, head, json.dumps({"id": "Q1", "total": 3, "result": ["a", "b", "c"]}).encode()
        l = lambda amt, cur: {"listing": {"price": {"amount": amt, "currency": cur}, "indexed": "", "account": {"name": "x"}}}
        return 200, head, json.dumps({"result": [l(2, "chaos"), l(10, "exalted"), l(1, "divine")]}).encode()

    client = TradeClient("kakao", opener=opener)
    ex = client.exchange("L", "divine")
    assert ex.unit_ex == 320 and ex.url.endswith("/trade2/exchange/poe2/L/E1")
    assert json.loads(sent[0])["query"]["status"] == {"option": "online"}  # 거래소에서 열기는 온라인 매물만
    res = client.search("L", build_query(BOOTS_EQUIPPED_KO, DATA))
    client.add_rates("L", res)
    assert [l.ex for l in res.listings] == [4, 10, 320]  # 카오스 1 = 2 엑잘(중간값), 신성은 위에서 받은 환율 그대로
    assert sum("/api/trade2/exchange/" in c for c in calls) == 2  # 신성 환율은 캐시
    assert client.exchange("L", "rune_x", "Runes").unit_ex == 30  # ninja: 0.1 신성 × 300
    assert bait(res) is False and ex_text(320) == "320 엑잘" and ex_text(1.25) == "1.2 엑잘"
    res.listings[0].ex = 0.5
    assert bait(res) is True
    res.listings = [res.listings[2], res.listings[0], res.listings[1]]  # 신성 1개가 맨 앞이어도
    client.add_rates("L", res)
    assert [l.currency for l in res.listings] == ["chaos", "exalted", "divine"]  # 엑잘 환산 순


def test_wheel_nudges_value_and_turns_filter_on():
    q = build_query(BOOTS_EQUIPPED_KO, DATA, char_level=45)
    move = next(f for f in q.filters if f.key == "pseudo.pseudo_increased_movement_speed")
    dex = next(f for f in q.filters if f.label == "민첩 +19")
    assert move.nudge(+2) and move.min == 30 and move.orig == 20  # 이동 속도는 5 단위
    dex.enabled = False
    assert dex.nudge(-1) and dex.min == 18 and dex.enabled  # 옵션 한 줄: 19 의 약 5% = 1, 휠로 바꾸면 켠다
    lvl = next(f for f in q.filters if f.key == "lvl")
    assert lvl.nudge(+1) and lvl.max == 46  # 레벨은 1 단위
    assert Filter("x", "x", "stat", min=0.5).nudge(+1) and Filter("x", "x", "stat", min=0.5).nudge(-9)
    assert not Filter("type", "베이스", "type").nudge(1)  # 수치 없는 조건


def test_wheel_steps_per_filter():
    q = build_query(BOOTS_EQUIPPED_KO, DATA)
    attrs = next(f for f in q.filters if f.key == "pseudo.pseudo_total_attributes")
    assert attrs.nudge(+1) and attrs.min == 20  # 합계는 1 단위 (사용자 요청)
    dps = next(f for f in build_query(CROSSBOW, DATA).filters if f.key == "dps")
    assert dps.nudge(-1) and dps.min == 25


def test_reset_and_average_label():
    q = build_query(CROSSBOW, DATA)
    cold = next(f for f in q.filters if f.label == "냉기 피해 3~5 추가")
    assert cold.avg and cold.min == 4  # 두 값은 평균으로 비교
    cold.nudge(+3)
    assert cold.min == 7 and cold.enabled and cold.changed
    cold.reset()
    assert cold.min == 4 and not cold.enabled and not cold.changed


def test_sockets_level_and_corrupted_filters():
    q = build_query(SLIVERTONGUE + "--------" + chr(10) + "타락" + chr(10), DATA)
    f = {x.key: x for x in q.filters}
    assert f["rune_sockets"].min == 2 and not f["rune_sockets"].enabled  # 홈: S S
    assert f["lvl"].max == 39 and not f["lvl"].enabled  # 레벨링이 아니면 꺼 둠
    cor = f["corrupted"]
    assert cor.text == "true"  # 타락한 아이템은 타락만으로 시작
    assert q.body()["query"]["filters"]["misc_filters"]["filters"]["corrupted"] == {"option": "true"}
    cor.cycle()
    assert cor.text == "" and "misc_filters" not in q.body()["query"]["filters"] and cor.changed
    cor.cycle()
    assert cor.text == "false"
    cor.reset()
    assert cor.text == "true"


def test_socketless_armour_still_offers_socket_filter():
    f = next(x for x in build_query(BOOTS_EQUIPPED_KO, DATA).filters if x.key == "rune_sockets")
    assert f.min == 0 and not f.enabled
    assert f.nudge(+1) and f.min == 1 and f.enabled  # 휠로 1개 이상
    assert not any(x.key == "rune_sockets" for x in build_query(RING, DATA).filters)  # 장신구는 홈이 있을 때만
    holed = RING.replace("아이템 레벨: 7", chr(10).join(["홈: S", "--------", "아이템 레벨: 7"]))
    assert any(x.key == "rune_sockets" and x.min == 1 for x in build_query(holed, DATA).filters)


def test_league_display_names():
    d = TradeData.from_json({"leagues": {"result": [{"id": "Forbidden Rites", "text": "금단의 의식"},
                                                    {"id": "HC Forbidden Rites", "text": "HC Forbidden Rites"}]}})
    assert d.leagues["Forbidden Rites"] == "금단의 의식" and d.leagues["HC Forbidden Rites"] == "HC Forbidden Rites"


def test_ssf_leagues_use_trade_league():
    from poe2_overlay.trade import trade_league
    assert trade_league("HC Forbidden Rites") == ("HC Forbidden Rites", False)
    assert trade_league("SSF Forbidden Rites") == ("Forbidden Rites", True)
    assert trade_league("HC SSF Forbidden Rites") == ("HC Forbidden Rites", True)
    assert trade_league("SSF Hardcore") == ("Hardcore", True) and trade_league("SSF Standard") == ("Standard", True)
