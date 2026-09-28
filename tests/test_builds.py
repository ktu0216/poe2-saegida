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
