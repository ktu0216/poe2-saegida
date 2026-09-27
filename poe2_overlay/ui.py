"""가이드 우선 오버레이 창."""
from __future__ import annotations

import html
import re
from typing import Callable, Optional

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QGuiApplication, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from .guide import Step, is_town
from .regex import RegexRule
from .rewards import SlotState
from .timing import CAMPAIGN, TimerView, fmt, fmt_delta
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


def _timer_line(t: TimerView) -> str:
    act, cur, pb = t.act, t.act_time, t.pb
    if t.rows[-1][0] == CAMPAIGN:  # 캠페인을 끝낸 캐릭터는 완주 시간만
        act, cur, _, pb = t.rows[-1]
        act += " 완료"
    line = f'⏱ {html.escape(act)} <b style="color:{TEXT}">{fmt(cur)}</b>'
    if pb:
        diff = cur - pb
        color = OK if diff <= 0 else WARN
        line += f' · PB {fmt(t.pb)} <span style="color:{color}">({fmt_delta(diff)})</span>'
    return line + f' · 전체 {fmt(t.total)}'


def _split_table(t: TimerView) -> str:
    out = [f'<div style="color:{ACCENT};margin-top:6px"><b>구간 기록</b> <span style="color:{DIM}">(PB = 이전 캐릭터 최고)</span></div>']
    for act, dur, done, pb in t.rows:
        cmp = ""
        if pb:
            diff = dur - pb
            cmp = f' <span style="color:{OK if diff <= 0 else WARN}">{fmt_delta(diff)}</span> <span style="color:{DIM}">/ PB {fmt(pb)}</span>'
        mark = "✓" if done else "▶"
        out.append(f'<div style="color:{TEXT}">{mark} {html.escape(act)} {fmt(dur)}{cmp}</div>')
    return "".join(out)


def _gem_table(gems, names) -> str:
    out = [f'<div style="color:{ACCENT};margin-top:6px"><b>젬</b> <span style="color:{DIM}">'
           f'{html.escape(gems.build.name)}</span></div>']
    for g in gems.now:
        sup = ", ".join(html.escape(names(s)) for s in g.supports)
        out.append(f'<div style="color:{TEXT}">● {html.escape(names(g.id))}'
                   + (f' <span style="color:{DIM}">+ {sup}</span>' if sup else "") + "</div>")
    for g in gems.upcoming[:6]:
        out.append(f'<div style="color:{DIM}">Lv {g.lo} · {html.escape(names(g.id))}</div>')
    return "".join(out)


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
    mode_chosen = Signal(str)  # 새 캐릭터 모드 선택 ("" = 건너뛰기)

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

        # 새 캐릭터: 모드 선택 (선택/건너뛰기/진행하면 사라짐)
        self.mode_box = QFrame()
        self.mode_box.setObjectName("modebox")
        self.mode_box.setStyleSheet(
            f"QFrame#modebox{{background:rgba(127,184,255,30);border:1px solid #7fb8ff;border-radius:4px}}"
            f"QPushButton{{background:#2a2622;color:{TEXT};border:1px solid #5a5040;border-radius:3px;padding:2px 6px}}"
            f"QPushButton:hover{{border-color:{ACCENT}}}")
        ml = QVBoxLayout(self.mode_box)
        ml.setContentsMargins(8, 5, 8, 6)
        ml.setSpacing(4)
        self.mode_msg = _label(fs - 2, TEXT, True)
        self.mode_msg.setText("새 캐릭터 — 모드를 선택하세요")
        ml.addWidget(self.mode_msg)
        row = QHBoxLayout()
        row.setSpacing(4)
        for mode in ("소프트코어", "하드코어", "SSF", "HC SSF"):
            b = QPushButton(mode)
            b.setFont(QFont("Malgun Gothic", fs - 3))
            b.clicked.connect(lambda _=False, md=mode: self.mode_chosen.emit(md))
            row.addWidget(b)
        row.addStretch(1)
        skip = QPushButton("건너뛰기")
        skip.setFont(QFont("Malgun Gothic", fs - 3))
        skip.clicked.connect(lambda: self.mode_chosen.emit(""))
        row.addWidget(skip)
        ml.addLayout(row)
        self.mode_box.setVisible(False)
        root.addWidget(self.mode_box)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(3)
        self.bar.setStyleSheet(
            f"QProgressBar{{background:#3a342c;border:none;border-radius:1px}}"
            f"QProgressBar::chunk{{background:{ACCENT};border-radius:1px}}")
        root.addWidget(self.bar)

        self.timer_lbl = _label(fs - 2, DIM)
        root.addWidget(self.timer_lbl)

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

        self.gem_lbl = _label(fs - 2, DIM)  # 빌드 플래너 기준 젬 안내
        root.addWidget(self.gem_lbl)

        self.next_lbl = _label(fs - 1, DIM)
        root.addWidget(self.next_lbl)

        self.foot_lbl = _label(fs - 3, DIM)
        root.addWidget(self.foot_lbl)

        self.reward_lbl = _label(fs - 3, DIM)  # 전체 보상 목록 (Ctrl+Alt+R)
        self.reward_lbl.setVisible(False)
        root.addWidget(self.reward_lbl)
        self.show_rewards = False

        self.setFixedWidth(int(settings["window"].get("w", 420)))
        self._grow_key = None  # 이 값(캐릭터)이 같은 동안은 창 높이를 줄이지 않는다 (흔들림 방지)
        self._min_h = 0
        # 아이템 비교·정규식·알림은 패널 아래에 붙는 별도 창에 (패널 크기가 변하지 않도록)
        self.toast = Toast(fs, self.width())
        w = settings["window"]
        if w.get("x") is not None:
            self.move(int(w["x"]), int(w.get("y") or 0))

    # ------------------------------------------------------------ 표시
    def render(self, s: Snapshot, notice: str = "", rewards: Optional[list[SlotState]] = None,
               passive_total: int = 0, timer: Optional[TimerView] = None,
               regex: Optional[RegexRule] = None, regex_key: str = "", flash: str = "",
               item_msg: str = "", gems=None, gem_names=None) -> None:
        rewards = rewards or []
        self._render_gems(gems, gem_names)
        toast = []
        if item_msg:
            toast.append(item_msg)
        if flash:
            toast.append(f'<b style="color:{OK}">{html.escape(flash)}</b>')
        elif regex:
            toast.append(
                f'🔎 <b style="color:{TEXT}">{html.escape(regex.name)}</b> '
                f'<span style="color:{ACCENT};font-family:Consolas">{html.escape(regex.regex)}</span>'  # 맑은 고딕은 \ 를 ₩ 로 그린다
                f' <span style="color:{DIM}">· {html.escape(regex_key)} 복사</span>')
        self.toast.set_content("<br>".join(toast), self.isVisible())
        self._follow()
        self.timer_lbl.setText(_timer_line(timer) if timer else "&nbsp;")  # 비어도 자리 유지
        self.step_gift.setText("&nbsp;")
        key = s.character.name if s.character else None
        if key != self._grow_key:
            self._grow_key, self._min_h = key, 0
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
            self._fit()
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
            self._fit()
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
        if c.area_level and not is_town(c.zone):  # 마을은 안전 지대라 레벨 경고 없음
            gap = c.area_level - c.level
            color = WARN if gap >= 3 else (OK if gap <= 0 else DIM)
            loc_html += f' · <span style="color:{color}">지역 Lv {c.area_level}</span>'
            if gap >= 3:
                loc_html += f' <span style="color:{WARN}">(레벨 {gap} 부족)</span>'
        if s.off_route and not is_town(c.zone):
            loc_html += f' · <span style="color:{WARN}">가이드 경로 밖</span>'
        self.loc_lbl.setText(loc_html)

        if step:
            self.step_area.setText(html.escape(step.area))
            self.step_text.setText(rich(step.text) or "이동")
            parts = []
            if marker := s.flags.get("marker"):
                parts.append(f'<span style="color:{TEXT}">◆ {html.escape(marker)}</span>')
            for label, st in s.flags.get("sub", {}).items():  # 하위 지역 보스 (집정관, 배우자 등)
                icon, color, word = {"engaged": ("⚔", WARN, "전투 중"), "killed": ("✓", OK, "처치"),
                                     "died": ("☠", WARN, "에게 사망")}.get(st, ("", DIM, st))
                parts.append(f'<span style="color:{color}">{icon} {html.escape(label)} {word}</span>')
            boss = html.escape(s.boss)
            state = s.flags.get("boss")
            if state == "engaged":
                parts.append(f'<span style="color:{WARN}">⚔ {boss} 전투 중</span>')
            elif state == "killed":
                parts.append(f'<span style="color:{OK}">✓ {boss} 처치</span>')
            elif state == "died":
                parts.append(f'<span style="color:{WARN}">☠ {boss}에게 사망</span>')
            gifts = [r.slot for r in rewards if not r.done and r.slot.zone == step.zone]
            if gifts:
                parts.append("🎁 " + " · ".join(html.escape(g.label) for g in gifts))
            if parts:
                self.step_gift.setText(" · ".join(parts))
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
                self.reward_lbl.setText(_reward_list(rewards) + (_split_table(timer) if timer else "")
                                        + (_gem_table(gems, gem_names) if gems else ""))
                self.reward_lbl.setVisible(True)
        if notice:
            foot.append(notice)
        if self.click_through:
            foot.append("🔒 클릭 통과 중 (Ctrl+Alt+T 해제)")
        self.foot_lbl.setText("<br>".join(foot))
        self.foot_lbl.setVisible(bool(foot))
        self._fit()

    def _fit(self) -> None:
        """폭은 고정, 높이는 줄바꿈된 내용에 딱 맞게 (adjustSize 는 줄어들지 않는 경우가 있다)."""
        lay = self.layout()
        lay.activate()
        h = lay.heightForWidth(self.width()) if lay.hasHeightForWidth() else lay.sizeHint().height()
        h = max(h, lay.minimumSize().height())
        if not self.show_rewards:  # 전체 목록을 펼친 경우만 예외
            h = max(h, self._min_h)
            self._min_h = h
        self.setFixedHeight(h)
        self._follow()

    # ------------------------------------------------------------ 그리기/조작
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg = QColor(BG)
        bg.setAlphaF(self.opacity)
        p.setBrush(bg)
        p.setPen(QColor(90, 78, 60, 160))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

    def show_mode_prompt(self, show: bool) -> None:
        if show:
            self.mode_msg.setText("새 캐릭터 — 모드를 선택하세요" + (
                " (Ctrl+Alt+T 로 클릭 통과를 끄고 선택)" if self.click_through else ""))
        if show != self.mode_box.isVisible():
            self.mode_box.setVisible(show)
            self._min_h = 0  # 선택 줄이 사라지면 창을 줄인다
            self._fit()

    def _render_gems(self, gems, names) -> None:
        self.gem_lbl.setVisible(gems is not None)
        if gems is None:
            return
        now = " · ".join(html.escape(names(g.id)) for g in gems.now) or "-"
        line = f'💎 <span style="color:{TEXT}">{now}</span>'
        if gems.upcoming:
            nxt = gems.upcoming[0].lo
            soon = [g for g in gems.upcoming if g.lo == nxt]
            line += (f' <span style="color:{DIM}">│ Lv {nxt}: </span>'
                     f'<span style="color:{GIFT}">{" · ".join(html.escape(names(g.id)) for g in soon)}</span>')
        stage = gems.build.stage or gems.build.label
        line += f'<br><span style="color:{DIM};font-size:small">{html.escape(stage)} · {html.escape(gems.build.label)}</span>'
        self.gem_lbl.setText(line)

    def clamp_to_screen(self) -> None:
        """창이 화면 밖으로 나가 잘리지 않게 (위쪽이 잘리면 캐릭터 줄이 안 보인다)."""
        screen = QGuiApplication.screenAt(self.frameGeometry().center()) or QGuiApplication.primaryScreen()
        a = screen.availableGeometry()
        x = min(max(self.x(), a.left()), a.right() - self.width())
        y = min(max(self.y(), a.top()), a.bottom() - min(self.height(), a.height()))
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def _follow(self) -> None:
        self.toast.follow(self.frameGeometry())

    def moveEvent(self, e):
        super().moveEvent(e)
        self._follow()

    def setVisible(self, visible: bool) -> None:
        super().setVisible(visible)
        self.toast.set_content(self.toast.content, visible)

    def setWindowOpacity(self, value: float) -> None:
        super().setWindowOpacity(value)
        self.toast.setWindowOpacity(value)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            self.clamp_to_screen()
            self.moved.emit(self.x(), self.y())

    def contextMenuEvent(self, e):
        if self.menu_builder:
            m = QMenu(self)
            self.menu_builder(m)
            m.exec(e.globalPos())


class Toast(QWidget):
    """가이드 패널 바로 아래(공간이 없으면 위)에 붙는 알림 창. 내용이 없으면 숨는다."""

    def __init__(self, fs: int, width: int):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("POE2 가이드 알림")
        self.content = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        self.lbl = _label(fs - 1, TEXT)
        lay.addWidget(self.lbl)
        self.setFixedWidth(width)

    def set_content(self, html_text: str, parent_visible: bool) -> None:
        self.content = html_text
        if html_text:
            self.lbl.setText(html_text)
            lay = self.layout()
            lay.activate()
            self.setFixedHeight(lay.heightForWidth(self.width()) if lay.hasHeightForWidth()
                                else lay.sizeHint().height())
        self.setVisible(bool(html_text) and parent_visible)

    def follow(self, g) -> None:
        screen = self.screen().availableGeometry() if self.screen() else None
        y = g.bottom() + 6
        if screen is not None and y + self.height() > screen.bottom():
            y = g.top() - self.height() - 6
        self.move(g.left(), y)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg = QColor(BG)
        bg.setAlphaF(0.92)
        p.setBrush(bg)
        p.setPen(QColor(ACCENT))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
