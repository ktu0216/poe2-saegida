"""캠페인 기록 내보내기: 완주 카드(PNG), LiveSplit 스플릿 파일(.lss)."""
from __future__ import annotations

import html
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

from .i18n import act as tact, cls as tcls, t
from .timing import CAMPAIGN, ENDGAME, TimerView, fmt, fmt_delta
from .tracker import league_for_mode


def out_dir() -> Path:
    """사진 폴더 아래 POE2 Saegida (OneDrive 로 옮긴 사진 폴더도 Windows 가 알려주는 실제 위치로)."""
    try:
        from PySide6.QtCore import QStandardPaths
        pics = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
        if pics and Path(pics).is_dir():
            return Path(pics) / "POE2 Saegida"
    except Exception:
        pass
    home = Path(os.environ.get("USERPROFILE", Path.home()))
    for base in (home / "Pictures", home / "Documents", home):
        if base.is_dir():
            return base / "POE2 Saegida"
    return home / "POE2 Saegida"


def open_out_dir() -> Path:
    """내보내기 폴더를 (없으면 만들어서) 탐색기로 연다."""
    d = out_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.startfile(d)
    return d


def finished_on(c) -> str:
    """캠페인을 끝낸 날짜 (YYYY/MM/DD): 기록된 완주 시각 → 첫 엔드게임 지도 → 마지막 플레이 날짜."""
    starts = [m.get("start", "") for m in getattr(c, "eg_maps", []) if m.get("start")]
    ts = getattr(c, "campaign_done", "") or (min(starts) if starts else "") or c.last_seen
    return (ts or datetime.now().strftime("%Y/%m/%d"))[:10]


def safe_name(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", text).strip() or "character"


# ---------------------------------------------------------------- LiveSplit
def _lss_time(seconds: float) -> str:
    s = max(0.0, seconds)
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    frac = s - int(s)
    return f"{h:02d}:{m:02d}:{sec:02d}.{int(round(frac * 1e7)):07d}"


def to_lss(name: str, tv: TimerView, best: Optional[dict[str, float]] = None) -> str:
    """LiveSplit 스플릿 파일 (.lss). 구간 = 액트·막간, 이 캐릭터의 기록을 PB 로, best 는 구간별 최고 기록(골드)."""
    best = best or {}
    rows = [r for r in tv.rows if r[0] != CAMPAIGN and r[2]]  # 끝난 구간만
    seg = []
    total = 0.0
    for act, dur, _done, _pb in rows:
        total += dur
        gold = min(dur, best.get(act, dur))
        seg.append(
            "    <Segment>\n"
            f"      <Name>{escape(tact(act))}</Name>\n"
            "      <Icon />\n"
            "      <SplitTimes>\n"
            '        <SplitTime name="Personal Best">\n'
            f"          <RealTime>{_lss_time(total)}</RealTime>\n"
            f"          <GameTime>{_lss_time(total)}</GameTime>\n"
            "        </SplitTime>\n"
            "      </SplitTimes>\n"
            "      <BestSegmentTime>\n"
            f"        <RealTime>{_lss_time(gold)}</RealTime>\n"
            f"        <GameTime>{_lss_time(gold)}</GameTime>\n"
            "      </BestSegmentTime>\n"
            "      <SegmentHistory />\n"
            "    </Segment>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Run version="1.7.0">\n'
            "  <GameIcon />\n"
            "  <GameName>Path of Exile 2</GameName>\n"
            f"  <CategoryName>{escape(t('캠페인'))} ({escape(name)})</CategoryName>\n"
            "  <LayoutPath />\n"
            "  <Metadata>\n    <Run id=\"\" />\n    <Platform usesEmulator=\"False\">PC</Platform>\n"
            "    <Region />\n    <Variables />\n  </Metadata>\n"
            "  <Offset>00:00:00</Offset>\n"
            "  <AttemptCount>1</AttemptCount>\n"
            "  <AttemptHistory />\n"
            "  <Segments>\n" + "\n".join(seg) + "\n  </Segments>\n"
            "  <AutoSplitterSettings />\n"
            "</Run>\n")


def save_lss(name: str, tv: TimerView, best: Optional[dict[str, float]] = None) -> Path:
    d = out_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{safe_name(name)}.lss"
    p.write_text(to_lss(name, tv, best), encoding="utf-8")
    return p


# ---------------------------------------------------------------- 완주 카드
def card_html(c, tv: TimerView, league: str = "") -> str:
    """완주 카드 내용 (HTML, QLabel 로 그린다)."""
    camp = next((r for r in tv.rows if r[0] == CAMPAIGN), None)
    total = camp[1] if camp else sum(r[1] for r in tv.rows if r[0] != CAMPAIGN)
    pb = camp[3] if camp else None
    when = finished_on(c)
    who = html.escape(c.name)
    sub = " · ".join(x for x in (html.escape(tcls(c.cls)), f"Lv {c.level}",
                                 html.escape(league_for_mode(league or c.league, c.mode)), html.escape(t(c.mode)) if c.mode else "") if x)
    rows = []
    for act, dur, done, apb in tv.rows:
        if act == CAMPAIGN or act == ENDGAME:
            continue
        diff = (f'<span style="color:{"#8fd18b" if dur - apb <= 0 else "#ff8a65"}">{fmt_delta(dur - apb)}</span>'
                if apb else "")
        # 시간·PB 차이를 따로 칸으로: 차이가 없는 줄(첫 기록)도 시간이 같은 자리에 오게
        rows.append(f'<tr><td style="color:#c8bfae;padding-right:18px">{html.escape(tact(act))}</td>'
                    f'<td align="right" style="color:#ece6da"><b>{fmt(dur)}</b></td>'
                    f'<td style="padding-left:10px">{diff}</td></tr>')
    pb_line = (f'<span style="color:{"#8fd18b" if total - pb <= 0 else "#ff8a65"}">PB {fmt_delta(total - pb)}</span> · '
               if pb else "")
    return (f'<div style="color:#e8b04a;font-size:13px;letter-spacing:2px">POE2 SAEGIDA · {html.escape(t("캠페인 완주"))}</div>'
            f'<div style="color:#ece6da;font-size:26px;font-weight:bold;margin-top:6px">{who}</div>'
            f'<div style="color:#9a9284;font-size:13px">{sub}</div>'
            f'<div style="color:#e8b04a;font-size:40px;font-weight:bold;margin-top:12px">{fmt(total)}</div>'
            f'<div style="color:#9a9284;font-size:13px">{pb_line}☠ {c.deaths} · {when}</div>'
            f'<table style="margin-top:14px;font-size:15px" cellspacing="0" cellpadding="3">{"".join(rows)}</table>'
            f'<div style="color:#6f685c;font-size:11px;margin-top:14px">github.com/ktu0216/poe2-saegida</div>')


def render_card(c, tv: TimerView, league: str = ""):
    """완주 카드 QImage (Qt 가 떠 있어야 한다)."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen
    from PySide6.QtWidgets import QLabel

    lb = QLabel()
    lb.setTextFormat(Qt.RichText)
    lb.setFont(QFont("Malgun Gothic", 11))
    lb.setStyleSheet("background:transparent")
    lb.setText(card_html(c, tv, league))
    lb.setFixedWidth(420)
    lb.adjustSize()
    w, h = 420 + 72, lb.height() + 64
    scale = 2  # 공유용이라 선명하게
    img = QImage(w * scale, h * scale, QImage.Format_ARGB32)
    img.setDevicePixelRatio(scale)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0, QColor(40, 31, 22))
    g.setColorAt(1, QColor(14, 12, 10))
    p.fillRect(0, 0, w, h, g)
    p.setPen(QPen(QColor(232, 176, 74, 150), 2))
    p.drawRoundedRect(6, 6, w - 12, h - 12, 10, 10)
    lb.render(p, QPoint(36, 32))
    p.end()
    return img


def save_card(c, tv: TimerView, league: str = "") -> Path:
    d = out_dir()
    d.mkdir(parents=True, exist_ok=True)
    stamp = finished_on(c).replace("/", "-")
    p = d / f"{safe_name(c.name)}_{stamp}.png"
    render_card(c, tv, league).save(str(p))
    return p
