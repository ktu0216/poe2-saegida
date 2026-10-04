from poe2_overlay.config import resource_dir
from poe2_overlay.rewards import RewardTable

TABLE = RewardTable.load(resource_dir() / "guides" / "rewards_ko.json")


def by_source(states, source):
    return [s for s in states if s.slot.source == source]


def test_duplicate_spirit_fills_two_slots():
    st = TABLE.evaluate(["정신력 +30", "정신력 +30"])
    assert by_source(st, "연무 속의 왕")[0].done
    assert by_source(st, "아자크 습지대")[0].done


def test_choice_and_multi_line_option():
    st = TABLE.evaluate(["마나 재생 속도 25% 증가", "힘 +5", "민첩 +5", "지능 +5"])
    assert by_source(st, "지구라트 야영지 (택1)")[0].got == ["마나 재생 속도 25% 증가"]
    trial = by_source(st, "죽음의 전당 (택1)")[0]
    assert trial.got == ["힘 +5", "민첩 +5", "지능 +5"]
    assert sum(s.done for s in st) == 2


def test_resist_plus_five_does_not_steal_other_slots():
    st = TABLE.evaluate(["냉기 저항 +5%", "냉기 저항 +10%"])
    assert by_source(st, "썩은 무리 베이라")[0].got == ["냉기 저항 +10%"]
    assert by_source(st, "죽음의 전당 (택1)")[0].got == ["냉기 저항 +5%"]


def test_passive_sources_cover_24_points_and_match_guide_steps():
    from poe2_overlay.config import resource_dir
    from poe2_overlay.guide import Guide
    from poe2_overlay.rewards import load_passive_sources
    for lang in ("ko", "en"):  # 동봉 가이드마다 각 출처가 가이드 단계 하나 이상에 붙는다
        srcs = load_passive_sources(resource_dir() / "guides" / f"quest_passives_{lang}.json")
        assert len(srcs) * 2 == 24
        steps = Guide.load(resource_dir() / "guides" / f"default_{lang}.csv").steps
        for s in srcs:
            assert any(s.on(st.zone, st.text) for st in steps), (lang, s)
