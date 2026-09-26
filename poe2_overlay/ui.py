"""가이드 우선 오버레이 창."""
from __future__ import annotations

import html
import re
from typing import Callable, Optional

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu, QProgressBar, QVBoxLayout, QWidget,
)

from .guide import Step
from .rewards import SlotState
from .tracker import NEW_CHAR, UNKNOWN_CHAR, Snapshot

ACCENT = "#e8b04a"
TEXT = "#ece6da"
DIM = "#9a9284"
WARN = "#ff8a65"
OK = "#8fd18b"
GIFT = "#c9a0ff"
BG = QColor(18, 16, 14)

_EMPH = re.compile(r"「([^」]+)」|&quot;([^&]+?)&quot;")


def rich(text: str) -> str:
    """가이드 문구 강조: 「단어」, "단어", 화살표."""
    t = html.escape(text.strip())
    t = _EMPH.sub(lambda m: f'<b style="color:{ACCENT}">{m.group(1) or m.group(2)}</b>', t)
    t = t.replace("→", f'<span style="color:{ACCENT}">→</span>')
    return t


def _reward_list(rewards: list[SlotState]) -> str:
    """액트별 전체 보상 체크리스트."""
    out, act = [], None
    for r in rewards:
        if r.slot.act != act:
            act = r.slot.act
            out.append(f'<div style="color:{ACCENT};margin-top:4px"><b>{html.escape(act)}</b></div>')
        if r.done:
            out.append(f'<div style="color:{OK}">✓ {html.escape(", ".join(r.got))}'
                       f' <span style="color:{DIM}">— {html.escape(r.slot.source)}</span></div>')
        else:
            out.append(f'<div style="color:{TEXT}">○ {html.escape(r.slot.label)}'
                       f' <span style="color:{DIM}">— {html.escape(r.slot.source)}</span></div>')
    return "".join(out)


MODE_COLOR = {"하드코어": "#ff6b5b", "HC SSF": "#ff6b5b", "SSF": "#7fb8ff"}


def _league_line(league: str, mode: str) -> str:
    parts = []
    if league:
        parts.append(f"🏳 {html.escape(league)}")
    if mode:
        parts.append(f'<b style="color:{MODE_COLOR.get(mode, DIM)}">{html.escape(mode)}</b>')
    if not parts:
        return ""
    return f'<br><span style="color:{DIM};font-weight:normal;font-size:small">{" · ".join(parts)}</span>'


def make_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(30, 26, 22))
    p.setPen(QColor(ACCENT))
    p.drawEllipse(4, 4, 56, 56)
    path = QPainterPath()
    path.moveTo(32, 10)
    path.lineTo(40, 32)
    path.lineTo(32, 54)
    path.lineTo(24, 32)
    path.closeSubpath()
    p.setBrush(QColor(ACCENT))
    p.drawPath(path)
    p.end()
    return QIcon(pm)


def _label(size: int, color: str = TEXT, bold: bool = False, wrap: bool = True) -> QLabel:
    lb = QLabel()
    f = QFont("Malgun Gothic", size)
    f.setBold(bold)
    lb.setFont(f)
    lb.setStyleSheet(f"color:{color}; background:transparent;")
    lb.setWordWrap(wrap)
    lb.setTextFormat(Qt.RichText)
    return lb


class Overlay(QWidget):
    moved = Signal(int, int)

    def __init__(self, settings: dict):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("POE2 캠페인 가이드")
        self.setWindowIcon(make_icon())
        self.settings = settings
        self.opacity = float(settings.get("opacity", 0.88))
        self.click_through = False
        self._drag: Optional[QPoint] = None
        self.menu_builder: Optional[Callable[[QMenu], None]] = None

        fs = int(settings.get("font_size", 13))
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(6)

        head = QHBoxLayout()
        self.char_lbl = _label(fs - 1, TEXT, True)
        self.act_lbl = _label(fs - 2, ACCENT, True, wrap=False)
        head.addWidget(self.char_lbl, 1)
        head.addWidget(self.act_lbl, 0, Qt.AlignRight)
        root.addLayout(head)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(3)
        self.bar.setStyleSheet(
            f"QProgressBar{{background:#3a342c;border:none;border-radius:1px}}"
            f"QProgressBar::chunk{{background:{ACCENT};border-radius:1px}}")
        root.addWidget(self.bar)

        self.loc_lbl = _label(fs - 2, DIM)
        root.addWidget(self.loc_lbl)

        card = QFrame()
        card.setObjectName("card")  # QLabel 도 QFrame 이라 이름으로 한정해야 자식에 번지지 않는다
        card.setStyleSheet(
            f"QFrame#card{{background:rgba(232,176,74,28);border-left:3px solid {ACCENT};border-radius:4px}}")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(10, 6, 8, 8)
        cl.setSpacing(2)
        self.step_area = _label(fs - 1, ACCENT, True)
        self.step_text = _label(fs + 2, TEXT, True)
        self.step_gift = _label(fs - 1, GIFT, True)
        cl.addWidget(self.step_area)
        cl.addWidget(self.step_text)
        cl.addWidget(self.step_gift)
        root.addWidget(card)

        self.next_lbl = _label(fs - 1, DIM)
        root.addWidget(self.next_lbl)

        self.foot_lbl = _label(fs - 3, DIM)
        root.addWidget(self.foot_lbl)

        self.reward_lbl = _label(fs - 3, DIM)  # 전체 보상 목록 (Ctrl+Alt+R)
        self.reward_lbl.setVisible(False)
        root.addWidget(self.reward_lbl)
        self.show_rewards = False

        self.setFixedWidth(int(settings["window"].get("w", 420)))
        w = settings["window"]
        self.move(int(w.get("x", 40)), int(w.get("y", 120)))

    # ------------------------------------------------------------ 표시
    def render(self, s: Snapshot, notice: str = "", rewards: Optional[list[SlotState]] = None,
               passive_total: int = 0) -> None:
        rewards = rewards or []
        self.step_gift.setVisible(False)
        self.reward_lbl.setVisible(False)
        c = s.character
        if c is None:
            self.char_lbl.setText("캐릭터 없음")
            self.act_lbl.setText("")
            self.loc_lbl.setText("게임에서 지역을 이동하면 자동으로 인식합니다.")
            self.step_area.setText("")
            self.step_text.setText("대기 중…")
            self.next_lbl.setText("")
            self.foot_lbl.setText(notice)
            self.adjustSize()
            return

        if c.name == UNKNOWN_CHAR:
            self.char_lbl.setText("캐릭터 확인 중" + _league_line(s.league, c.mode))
            self.act_lbl.setText("")
            self.loc_lbl.setText(f"📍 {html.escape(c.area_name or c.zone or '접속 중')}")
            self.step_area.setText("")
            self.step_text.setText("레벨업·보상·사망 메시지가 나오면 자동으로 확정됩니다.")
            self.next_lbl.setText("우클릭 → 캐릭터 메뉴에서 직접 고를 수도 있습니다.")
            self.foot_lbl.setText(notice)
            self.foot_lbl.setVisible(bool(notice))
            self.adjustSize()
            return

        name = "새 캐릭터 (이름 확인 중)" if c.name == NEW_CHAR else html.escape(c.name)
        cls = f" · {html.escape(c.cls)}" if c.cls else ""
        tag = "" if s.confirmed else f' <span style="color:{DIM};font-weight:normal">(추정)</span>'
        league = _league_line(s.league, c.mode)
        self.char_lbl.setText(f"{name}{cls} · Lv {c.level}{tag}{league}")

        step = s.step
        if step:
            self.act_lbl.setText(f"{step.act}  {step.index + 1}/{s.total}")
            self.bar.setMaximum(max(1, s.total - 1))
            self.bar.setValue(step.index)

        loc = html.escape(c.area_name or c.zone or "-")
        loc_html = f"📍 {loc}"
        if c.area_level:
            gap = c.area_level - c.level
            color = WARN if gap >= 3 else (OK if gap <= 0 else DIM)
            loc_html += f' · <span style="color:{color}">지역 Lv {c.area_level}</span>'
            if gap >= 3:
                loc_html += f' <span style="color:{WARN}">(레벨 {gap} 부족)</span>'
        if s.off_route:
            loc_html += f' · <span style="color:{WARN}">가이드 경로 밖</span>'
        self.loc_lbl.setText(loc_html)

        if step:
            self.step_area.setText(html.escape(step.area))
            self.step_text.setText(rich(step.text) or "이동")
            gifts = [r.slot for r in rewards if not r.done and r.slot.zone == step.zone]
            if gifts:
                self.step_gift.setText("🎁 " + " · ".join(html.escape(g.label) for g in gifts))
                self.step_gift.setVisible(True)
        rows = []
        for i, st in enumerate(s.upcoming):
            size = "" if i == 0 else ' style="font-size:small"'
            rows.append(f'<div{size}><span style="color:{TEXT}">{html.escape(st.area)}</span>'
                        f" — {rich(st.text)}</div>")
        self.next_lbl.setText("".join(rows))

        foot = []
        if rewards:
            done = sum(r.done for r in rewards)
            line = (f'🏆 영구 보상 <b style="color:{TEXT}">{done}/{len(rewards)}</b>'
                    f' · 퀘스트 패시브 <b style="color:{TEXT}">{c.passive_points}/{passive_total}</b>')
            left = [r.slot for r in rewards if not r.done and step and r.slot.act == step.act]
            if left:
                line += f"<br>{html.escape(step.act)} 남음: " + " · ".join(
                    f'<span style="color:{GIFT}">{html.escape(sl.label)}</span>' for sl in left)
            foot.append(line)
            if self.show_rewards:
                self.reward_lbl.setText(_reward_list(rewards))
                self.reward_lbl.setVisible(True)
        if notice:
            foot.append(notice)
        if self.click_through:
            foot.append("🔒 클릭 통과 중 (Ctrl+Alt+T 해제)")
        self.foot_lbl.setText("<br>".join(foot))
        self.foot_lbl.setVisible(bool(foot))
        self.adjustSize()

    # ------------------------------------------------------------ 그리기/조작
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg = QColor(BG)
        bg.setAlphaF(self.opacity)
        p.setBrush(bg)
        p.setPen(QColor(90, 78, 60, 160))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            self.moved.emit(self.x(), self.y())

    def contextMenuEvent(self, e):
        if self.menu_builder:
            m = QMenu(self)
            self.menu_builder(m)
            m.exec(e.globalPos())
