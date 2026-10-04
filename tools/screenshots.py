"""문서용 스크린샷: 예시 진행 데이터를 실제 Tracker·Overlay 로 그려 docs/images/*.png 로 저장한다.

게임 화면을 찍지 않으므로 다른 창·채팅·개인 정보가 섞이지 않고, 기능이 바뀌면 다시 돌리면 된다.
사용: .venv\\Scripts\\python.exe tools\\screenshots.py   (한국어·영어 모두)
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from poe2_overlay import config, endgame, i18n  # noqa: E402
from poe2_overlay.builds import BuildFile, Gem, GemNames, GemPlan  # noqa: E402
from poe2_overlay.encounters import Encounters  # noqa: E402
from poe2_overlay.guide import Guide  # noqa: E402
from poe2_overlay.i18n import t  # noqa: E402
from poe2_overlay.items import compare, parse_item  # noqa: E402
from poe2_overlay.logparse import AreaEntered, LevelUp, NpcLine, PassivePoints, Reward, SceneName  # noqa: E402
from poe2_overlay.rewards import RewardTable, load_passive_sources  # noqa: E402
from poe2_overlay.timing import timer_view  # noqa: E402
from poe2_overlay.tracker import Character, Snapshot, Tracker  # noqa: E402
from poe2_overlay.ui import Overlay  # noqa: E402

OUT = ROOT / "docs" / "images"
SETTINGS = {"window": {"w": 420}, "opacity": 0.9, "font_size": 13}

TEXT = {
    "ko": {"cls": "머서너리", "name": "망령사냥꾼", "reward": "냉기 저항 +10%", "town": "클리어펠 야영지",
           "clearfell": "클리어펠", "grelwood": "그렐우드", "vale": "붉은 계곡",
           "ring_old": "아이템 종류: 반지\n아이템 희귀도: 희귀\n유황 유지\n루비 반지\n--------\n아이템 레벨: 41\n--------\n"
                       "화염 저항 +28%\n--------\n생명력 최대치 +15\n번개 저항 +13%\n",
           "ring_new": "아이템 종류: 반지\n아이템 희귀도: 희귀\n으스스한 띠\n토파즈 반지\n--------\n아이템 레벨: 50\n--------\n"
                       "번개 저항 +26%\n--------\n생명력 최대치 +29\n화염 저항 +25%\n이동 속도 5% 증가\n"},
    "en": {"cls": "Mercenary", "name": "WraithHunter", "reward": "+10% to Cold Resistance", "town": "Clearfell Encampment",
           "clearfell": "Clearfell", "grelwood": "The Grelwood", "vale": "The Red Vale",
           "ring_old": "Item Class: Rings\nRarity: Rare\nSulphur Grip\nRuby Ring\n--------\nItem Level: 41\n--------\n"
                       "+28% to Fire Resistance\n--------\n+15 to maximum Life\n+13% to Lightning Resistance\n",
           "ring_new": "Item Class: Rings\nRarity: Rare\nGrim Band\nTopaz Ring\n--------\nItem Level: 50\n--------\n"
                       "+26% to Lightning Resistance\n--------\n+29 to maximum Life\n+25% to Fire Resistance\n"
                       "5% increased Movement Speed\n"},
}


def ts(minute: int) -> str:
    return f"2026/10/05 {20 + minute // 60:02d}:{minute % 60:02d}:00"


def compose(name: str, overlay: Overlay, with_toast: bool = True, size=None) -> QImage:
    """패널(과 알림 카드)을 어두운 배경 위에 얹어 저장 (name 이 비면 저장하지 않고 이미지만)."""
    overlay.toast.adjustSize()
    panel = overlay.grab()
    toast = overlay.toast.grab() if with_toast and overlay.toast.cards else None
    dpr = panel.devicePixelRatio()
    pad = 18
    w = overlay.width() + pad * 2
    h = overlay.height() + pad * 2 + ((overlay.toast.height() + 6) if toast else 0)
    if size:  # GIF 프레임은 크기를 맞춘다
        w, h = size
    img = QImage(int(w * dpr), int(h * dpr), QImage.Format_ARGB32)
    img.setDevicePixelRatio(dpr)
    p = QPainter(img)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0, QColor(38, 30, 22))
    g.setColorAt(1, QColor(14, 12, 10))
    p.fillRect(0, 0, w, h, g)
    p.drawPixmap(QPoint(pad, pad), panel)
    if toast:
        p.drawPixmap(QPoint(pad, pad + overlay.height() + 6), toast)
    p.end()
    if name:
        OUT.mkdir(parents=True, exist_ok=True)
        img.save(str(OUT / f"{name}.png"))
        print("saved", name)
    return img


def save_gif(name: str, frames: list[QImage], durations: list[int]) -> None:
    """프레임들을 GIF 로 (Pillow 는 개발용 — 오버레이 실행에는 필요 없다)."""
    import io
    from PIL import Image
    from PySide6.QtCore import QBuffer, QIODevice
    pics = []
    for f in frames:
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        f.save(buf, "PNG")
        pics.append(Image.open(io.BytesIO(bytes(buf.data()))).convert("RGB"))
    pics[0].save(OUT / f"{name}.gif", save_all=True, append_images=pics[1:], duration=durations, loop=0, optimize=True)
    print("saved", name + ".gif")


def flow(lang: str, app: QApplication) -> None:
    """진행 흐름 GIF: 그렐우드 → 붉은 계곡 → (오벨리스크) → 보스 전투(간단 모드) → 처치 → 마을 단계."""
    tx = TEXT[lang]
    guide = Guide.load(ROOT / "guides" / f"default_{lang}.csv")
    enc = Encounters.load(config.data_file("encounters", lang))
    rewards = RewardTable.load(config.data_file("rewards", lang))
    tips = config.load_zone_tips(config.data_file("zone_tips", lang))
    tr = Tracker(guide, encounters=enc)
    tr.league = "Rise of the Abyssal"
    for ev in (AreaEntered(ts(0), "1", "G1_1", 1, "1"), LevelUp(ts(2), "1", tx["name"], tx["cls"], 2),
               AreaEntered(ts(4), "1", "G1_town", 15, "2"), AreaEntered(ts(5), "1", "G1_2", 2, "3"),
               Reward(ts(12), "1", tx["name"], tx["reward"]), LevelUp(ts(13), "1", tx["name"], tx["cls"], 4),
               AreaEntered(ts(16), "1", "G1_4", 4, "4")):
        tr.feed(ev)
    c = tr.chars[tx["name"]]
    c.mode = "소프트코어"
    o = Overlay(SETTINGS)
    o.zone_tips = tips
    o.move(-5000, -5000)
    o.show()
    frames, durs = [], []

    def shot(ms: int, compact_html: str = "") -> None:
        if compact_html:
            o.render_compact(compact_html)
        else:
            o.leave_compact()
            o.render(tr.snapshot(), "", rewards.evaluate(c.rewards), rewards.quest_passive_total,
                     timer_view(c, {}, 0.0))
        app.processEvents()
        frames.append(compose("", o, with_toast=False, size=(456, 470)))
        durs.append(ms)

    shot(1600)
    tr.feed(AreaEntered(ts(22), "1", "G1_5", 6, "5"))
    shot(1800)
    if lang == "ko":
        tr.feed(NpcLine(ts(25), "1", "귀신의 목소리", "우리 의지는 굳건하다..."))
        shot(1400)
    boss = enc.boss_name("g1_5")
    shot(1800, f'<span style="color:#ff8a65">{t("⚔ {name} 전투 중", name=boss)}</span>'
               f'<span style="color:#9a9284">{t(" · Lv {lv} · 지역 {area}", lv=6, area=6)}</span>'
               f' <b style="color:#e8b04a">{t("· Tab→미니맵")}</b>')
    tr.feed(NpcLine(ts(28), "1", boss, "..."))  # 보스 대사 → 전투 중
    tr.feed(AreaEntered(ts(31), "1", "G1_town", 15, "2"))  # 살아서 지역을 떠남 → 처치, 다음 단계
    shot(2400)
    o.close()
    save_gif(f"flow_{lang}", frames, durs)


def gem_plan(lang: str) -> tuple[GemPlan, GemNames]:
    names = GemNames.load(None, ROOT / "guides" / "gem_names_ko.json", ROOT / "guides" / "gem_names_trade.json",
                          ROOT / "guides" / "gem_ids_pob.json")
    names.english = lang == "en"
    build = BuildFile(Path("x.build"), "Gemling 1. Act 1", "Mercenary3", "액트 1", "gemling", [], label="Gemling")
    g = "Metadata/Items/Gems/"
    now = [Gem(g + "SkillGemExplosiveGrenade", 1, 100, [g + "SupportGemMuster", g + "SupportGemMagnifiedEffect"]),
           Gem(g + "SkillGemGasGrenade", 3, 100, [g + "SupportGemBiddingTwo"])]
    upcoming = [Gem(g + "SkillGemFlashGrenade", 7, 100, [])]
    return GemPlan(build, now, upcoming, []), names


def scenes(lang: str, app: QApplication) -> None:
    i18n.set_lang(lang)
    tx = TEXT[lang]
    guide = Guide.load(ROOT / "guides" / f"default_{lang}.csv")
    enc = Encounters.load(config.data_file("encounters", lang))
    rewards = RewardTable.load(config.data_file("rewards", lang))
    tips = config.load_zone_tips(config.data_file("zone_tips", lang))
    tr = Tracker(guide, encounters=enc)
    tr.passive_sources = load_passive_sources(config.data_file("quest_passives", lang))
    tr.league = "Rise of the Abyssal"
    feed = tr.feed
    feed(AreaEntered(ts(0), "1", "G1_1", 1, "11"))
    feed(LevelUp(ts(2), "1", tx["name"], tx["cls"], 2))
    feed(AreaEntered(ts(4), "1", "G1_town", 15, "1"))
    feed(SceneName(ts(4), "1", tx["town"]))
    feed(AreaEntered(ts(5), "1", "G1_2", 2, "12"))
    feed(Reward(ts(12), "1", tx["name"], tx["reward"]))
    feed(LevelUp(ts(13), "1", tx["name"], tx["cls"], 4))
    feed(AreaEntered(ts(16), "1", "G1_4", 4, "13"))
    feed(AreaEntered(ts(22), "1", "G1_5", 6, "14"))
    feed(SceneName(ts(22), "1", tx["vale"]))
    if lang == "ko":  # 붉은 계곡 오벨리스크 진행 대사 (한국어 로그로 확인한 것)
        feed(NpcLine(ts(25), "1", "귀신의 목소리", "우리 의지는 굳건하다..."))
    c = tr.chars[tx["name"]]
    c.mode = "소프트코어"
    plan, names = gem_plan(lang)

    def overlay() -> Overlay:
        o = Overlay(SETTINGS)
        o.passive_sources = tr.passive_sources
        o.zone_tips = tips
        o.move(-5000, -5000)
        o.show()
        return o

    def render(o: Overlay, **kw) -> None:
        snap = tr.snapshot()
        o.render(snap, "", rewards.evaluate(c.rewards), rewards.quest_passive_total,
                 timer_view(c, {}, 0.0), gems=plan, gem_names=names, **kw)
        app.processEvents()

    # 1. 캠페인 패널
    o = overlay()
    render(o)
    compose(f"panel_{lang}", o, with_toast=False)

    # 2. 오른쪽 위 아이콘 (마우스를 올렸을 때)
    o.tools.show()
    o._place_tools()
    app.processEvents()
    compose(f"tools_{lang}", o, with_toast=False)
    o.tools.hide()

    # 3. 아이템 비교 (Ctrl+C)
    title, diffs, verdict = compare(parse_item(tx["ring_new"]), parse_item(tx["ring_old"]))
    mark = t({1: "▲ 더 좋음", -1: "▼ 더 나쁨"}.get(verdict, "≈ 비슷"))
    item_msg = f'{mark} · {t("{slot} 대비", slot=t("반지 2"))}<br>' + " · ".join(diffs)
    render(o, item_msg=item_msg, item_color="#8fd18b")
    compose(f"item_compare_{lang}", o)

    # 4. 젬 카드 (Ctrl+Alt+G)
    render(o, gem_card=True)
    compose(f"gem_card_{lang}", o)

    # 5. 보상·구간 기록 (Ctrl+Alt+R)
    o.show_rewards = True
    render(o)
    compose(f"rewards_{lang}", o, with_toast=False)
    o.show_rewards = False

    # 6. 보스전 간단 모드
    boss = enc.boss_name("g1_5") or "The Rust King"
    o.render_compact(f'<span style="color:#ff8a65">{t("⚔ {name} 전투 중", name=boss)}</span>'
                     f'<span style="color:#9a9284">{t(" · Lv {lv} · 지역 {area}", lv=6, area=6)}</span>'
                     f' <b style="color:#e8b04a">{t("· Tab→미니맵")}</b>')
    app.processEvents()
    compose(f"boss_compact_{lang}", o, with_toast=False)
    o.close()

    # 7. 엔드게임 (캠페인을 끝낸 캐릭터)
    end = Character(name=tx["name"], cls="Gemling Legionnaire" if lang == "en" else "젬링 리저네어", level=91,
                    zone="mapcrypt", area_name="Crypt" if lang == "en" else "납골당", area_level=80,
                    league="Rise of the Abyssal", mode="소프트코어", deaths=12, play_seconds=40000.0,
                    ascendancy=["AscendancyMercenary3Notable1"] * 8,
                    splits={"액트 1": 0, "액트 2": 5800, "액트 3": 12200, "액트 4": 21000, "막간 1": 30200,
                            "막간 2": 33100, "막간 3": 35200, "엔드게임": 37900})
    eg = endgame.Summary(7, 262.0, 1, 130, "Crypt" if lang == "en" else "납골당", 154.0,
                         [("재의 중재자" if lang == "ko" else "The Arbiter of Ash", 2, 1, 0, True)])
    snap = Snapshot(end, True, guide.steps[-1], [], None, False, len(guide.steps), "Rise of the Abyssal")
    o = overlay()
    end.passive_points = 24
    got = [line for slot in rewards.slots for line in slot.options[0]]  # 보상을 다 받은 캐릭터
    o.render(snap, "", rewards.evaluate(got), rewards.quest_passive_total, timer_view(end, {}, 0.0), endgame=eg)
    app.processEvents()
    compose(f"endgame_{lang}", o, with_toast=False)
    o.close()


def main() -> int:
    app = QApplication(sys.argv)
    for lang in ("ko", "en"):
        i18n.set_lang(lang)
        scenes(lang, app)
        flow(lang, app)
    return 0


if __name__ == "__main__":
    sys.exit(main())
