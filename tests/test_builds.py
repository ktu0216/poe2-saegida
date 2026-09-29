import json

from poe2_overlay.builds import GemNames, families, pick_stage, plan, scan


def write(folder, fname, name, skills):
    (folder / f"{fname}.build").write_text(json.dumps({"name": name, "ascendancy": "Mercenary3",
                                                       "skills": skills}), encoding="utf-8")


def gem(gid, lo, hi=100, sup=()):
    return {"id": f"Metadata/Items/Gem/{gid}", "level_interval": [lo, hi],
            "support_skills": [{"id": f"Metadata/Items/Gems/{s}"} for s in sup]}


def test_stage_selection_and_plan(tmp_path):
    write(tmp_path, "a1", "Act 1 - [0.5.5] TWISTER GEMLING Legionna", [gem("SkillGemTwister", 1)])
    write(tmp_path, "a2", "Act 2 - [0.5.5] TWISTER GEMLING Legionna", [gem("SkillGemTwister", 1)])
    write(tmp_path, "i", "Interludes - [0.5.5] TWISTER GEMLING Leg", [gem("SkillGemTwister", 1)])
    write(tmp_path, "t", "Endgame Tankier - [0.5.5] TWISTER GEMLIN", [])
    write(tmp_path, "b", "Budget Endgame - [0.5.5] TWISTER GEMLING", [])
    write(tmp_path, "g", "LvL 1~42 - [POE2 0.5.5] 젬링 유탄",
          [gem("SkillGemExplosiveGrenade", 1, sup=["SupportGemScattershotTwo"]),
           gem("SkillGemHeraldOfAsh", 10), gem("SkillGemGasGrenade", 14)])
    fam = families(scan(tmp_path))
    assert len(fam) == 2
    tw = next(f for f in fam.values() if "TWISTER" in f[0].label)
    assert tw[0].label == "[0.5.5] TWISTER GEMLING Legionna"
    assert pick_stage(tw, "액트 2", 20).stage == "Act 2"
    assert pick_stage(tw, "막간 3", 50).stage == "Interludes"
    assert pick_stage(tw, "엔드게임", 70).stage == "Budget Endgame"
    gr = next(f for f in fam.values() if "유탄" in f[0].label)
    p = plan(pick_stage(gr, "액트 1", 10), 10)
    assert [g.id.rsplit("/", 1)[-1] for g in p.now] == ["SkillGemExplosiveGrenade", "SkillGemHeraldOfAsh"]
    assert [g.lo for g in p.upcoming] == [14] and [g.lo for g in p.unlocked_at] == [10]


def test_gem_names_korean_and_fallback(tmp_path):
    (tmp_path / "ko_names.json").write_text(json.dumps(
        {"gems": {"Explosive Grenade": "폭발 유탄", "Scattershot": "산탄"}}), encoding="utf-8")
    names = GemNames.load(tmp_path)
    assert names("Metadata/Items/Gem/SkillGemExplosiveGrenade") == "폭발 유탄"
    assert names("Metadata/Items/Gems/SupportGemScattershotTwo") == "산탄 II"
    assert names("Metadata/Items/Gem/SupportGemExpedite") == "Expedite (한글명 미확인)"


def test_numbered_names_group_and_pick(tmp_path):
    write(tmp_path, "a", "젬링 유탄 0. 액트 올인원", [gem("SkillGemExplosiveGrenade", 1)])
    write(tmp_path, "b", "젬링 유탄 1. Lv 1-42", [gem("SkillGemExplosiveGrenade", 1)])
    write(tmp_path, "c", "젬링 유탄 2. Lv 43-62", [gem("SkillGemExplosiveGrenade", 1)])
    write(tmp_path, "d", "젬링 유탄 3. 엔드 초기", [])
    write(tmp_path, "e", "젬링 유탄 4. 엔드 후기", [])
    fam = families(scan(tmp_path))
    assert list(fam) == ["젬링 유탄"] and len(fam["젬링 유탄"]) == 5
    files = fam["젬링 유탄"]
    assert pick_stage(files, "액트 3", 34).stage == "LvL 1~42"
    assert pick_stage(files, "막간 2", 50).stage == "LvL 43~62"
    assert pick_stage(files, "엔드게임", 70).stage == "Early Endgame"


def test_family_for_class_only_when_unique(tmp_path):
    from poe2_overlay.builds import family_for_class
    (tmp_path / "s.build").write_text(json.dumps({"name": "Act 1 - Navira", "ascendancy": "Sorceress3", "skills": []}),
                                      encoding="utf-8")
    write(tmp_path, "m1", "젬링 유탄 1. Lv 1-42", [])
    write(tmp_path, "m2", "Act 1 - TWISTER", [])
    b = scan(tmp_path)
    assert family_for_class(b, "소서리스") == "Navira"
    assert family_for_class(b, "머서너리") is None  # 두 묶음 → 모름
    assert family_for_class(b, "젬링 리저네어") is None
    assert family_for_class(b, "워리어") is None


def test_uncut_gem_parse_and_advice(tmp_path):
    from poe2_overlay.builds import parse_uncut, uncut_advice
    ko = "아이템 종류: 미가공 스킬 젬\n아이템 희귀도: 화폐\n미가공 스킬 젬\n--------\n레벨: 5\n--------\n아이템 레벨: 30\n"
    assert parse_uncut(ko) == ("skill", 5)
    assert parse_uncut("Item Class: Uncut Gems\nRarity: Currency\nUncut Support Gem (Level 2)\n") == ("support", 2)
    assert parse_uncut("아이템 종류: 반지\n") is None
    write(tmp_path, "g", "LvL 1~42 - 젬링 유탄",
          [gem("SkillGemExplosiveGrenade", 1, sup=["SupportGemScattershotTwo", "SupportGemExpedite"]),
           gem("SkillGemHeraldOfAsh", 10), gem("SkillGemGasGrenade", 14, sup=["SupportGemDeliberation"])])
    b = scan(tmp_path)[0]
    names = lambda i: i.rsplit("/", 1)[-1]
    skill = uncut_advice(b, "skill", 5, 12, names)
    assert "SkillGemExplosiveGrenade" in skill and "SkillGemGasGrenade (Lv 14)" in skill
    assert "HeraldOfAsh" not in skill  # 정신력 젬은 따로
    assert "SkillGemHeraldOfAsh" in uncut_advice(b, "spirit", 8, 12, names)
    sup = uncut_advice(b, "support", 1, 12, names)
    assert "SupportGemExpedite" in sup and "더 높은 등급 필요: SupportGemScattershotTwo" in sup


def test_numbered_act_split_by_level(tmp_path):
    for i, stage in enumerate(["액트 1", "액트 2 Lv 1-21", "액트 2 Lv 22+", "액트 3", "막간", "엔드 초기"], 1):
        (tmp_path / f"{i}.build").write_text(json.dumps(
            {"name": f"쉴드 스미스 {i}. {stage}", "ascendancy": "Warrior3", "skills": []}), encoding="utf-8")
    files = families(scan(tmp_path))["쉴드 스미스"]
    assert pick_stage(files, "액트 2", 18).name.endswith("Lv 1-21")
    assert pick_stage(files, "액트 2", 24).name.endswith("Lv 22+")
    assert pick_stage(files, "액트 1", 24).name.endswith("액트 1")
    assert pick_stage(files, "막간 1", 55).name.endswith("막간")


def test_gem_names_pob_ids_and_spirit():
    from pathlib import Path
    from poe2_overlay.config import resource_dir
    g = resource_dir() / "guides"
    names = GemNames.load(None, g / "gem_names_ko.json", g / "gem_names_trade.json", g / "gem_ids_pob.json")
    assert names("Metadata/Items/Gems/SupportGemMartialTempo") == "빠른 공격 I"  # 내부 이름 → Rapid Attacks I
    assert names("Metadata/Items/Gem/SkillGemPlayerDefault2HMace") == "기본 공격 (젬 아님)"
    assert names("Metadata/Items/Gem/SkillGemAscendancyVirtuousBarrier").startswith("전직 스킬")
    assert names("Metadata/Items/Gems/SupportGemScattershotTwo") == "다중 사격 II"
    assert names("Metadata/Items/Gems/SupportGemUulNetolsEmbrace") == "울네톨의 포옹"
    assert names.spirit("Metadata/Items/Gem/SkillGemHeraldOfAsh")
    assert not names.spirit("Metadata/Items/Gem/SkillGemExplosiveGrenade")
