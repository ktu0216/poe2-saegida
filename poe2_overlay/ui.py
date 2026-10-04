"""가이드 우선 오버레이 창."""
from __future__ import annotations

import html
import re
from typing import Callable, Optional

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QFont, QGuiApplication, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from .guide import Step, is_town
from .regex import RegexRule
from .rewards import SlotState
from .timing import CAMPAIGN, TimerView, fmt, fmt_delta
from .tracker import NEW_CHAR, UNKNOWN_CHAR, Snapshot
from .xp import full_xp_areas, xp_multiplier

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




def _gem_card(gems, names) -> tuple[str, str]:
    """빌드 플래너 기준 (머리글, 본문): 스킬 아래 보조 젬 들여쓰기, 다음 레벨 젬. (미가공 젬은 Ctrl+C 도우미)"""
    b = gems.build
    head = (f'💎 {html.escape(b.label)} <span style="color:{DIM};font-weight:normal">'
            f'· {html.escape(b.stage or "-")}</span>')
    out = []
    for g in (g for g in gems.now if g.supports):
        out.append(f'<div style="margin-top:3px"><b style="color:{TEXT}">● {html.escape(names(g.id))}</b></div>')
        sup = " · ".join(html.escape(names(s)) for s in g.supports)
        out.append(f'<div style="color:#c8bfae;margin-left:14px">└ {sup}</div>')
    alone = [g for g in gems.now if not g.supports]
    if alone:
        out.append(f'<div style="margin-top:3px"><b style="color:{TEXT}">◆ {" · ".join(html.escape(names(g.id)) for g in alone)}</b>'
                   f' <span style="color:{DIM}">(보조 젬 없음)</span></div>')
    if gems.upcoming:
        lv = gems.upcoming[0].lo
        for g in (x for x in gems.upcoming if x.lo == lv):
            sup = " · ".join(html.escape(names(s)) for s in g.supports)
            out.append(f'<div style="margin-top:6px;color:{DIM}">다음 Lv {lv}: <b style="color:#c8bfae">{html.escape(names(g.id))}</b>'
                       + (f' + {sup}' if sup else "") + '</div>')
    return head, "".join(out)

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


def _xp_badge(level: int, area_level: int) -> str:
    """경험치 효율: 100% 초록, 80% 이상 노랑, 50% 이상 주황, 그 아래 빨강. 100% 가 아니면 범위도."""
    pct = round(xp_multiplier(level, area_level) * 100)
    color = OK if pct >= 100 else ACCENT if pct >= 80 else WARN if pct >= 50 else "#ff5252"
    text = f'<span style="color:{color}">경험치 {pct}%</span>'
    if pct < 100:
        lo, hi = full_xp_areas(level)
        text += f' <span style="color:{DIM}">(100%: {lo}~{hi})</span>'
    return text


def _league_line(league: str, mode: str, cls_html: str = "") -> str:
    parts = []
    if league.startswith("HC ") and mode and "하드코어" not in mode and "HC" not in mode:
        league = league[3:]  # 하드코어에서 죽어 일반 리그로 옮겨진 캐릭터 (게임 설정의 리그 선택은 HC 로 남아 있다)
    if league:
        parts.append(f"🏳 {html.escape(league)}")
    if mode:
        parts.append(f'<b style="color:{MODE_COLOR.get(mode, DIM)}">{html.escape(mode)}</b>')
    cls_line = (f'<br><span style="color:{DIM};font-weight:normal;font-size:small">{cls_html}</span>'
                if cls_html else "")  # 직업·전직은 따로 한 줄 (리그와 합치면 줄이 넘어간다)
    if not parts:
        return cls_line
    return cls_line + f'<br><span style="color:{DIM};font-weight:normal;font-size:small">{" · ".join(parts)}</span>'


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
        self.waiting = False  # 게임이 꺼져 있음 (실행 대기 화면)
        self.passive_sources: list = []  # rewards.PassiveSource: 🎁 퀘스트 패시브 표시
        self.zone_tips: dict[str, str] = {}  # 지역 코드 → 🧭 길 찾기 메모 (비우면 표시 안 함)
        self._anchor: Optional[QPoint] = None  # 프로그램/드래그로 정한 위치 (창 높이가 바뀔 때 Windows 가 옮기면 되돌린다)
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
        self.step_tip = _label(fs - 2, DIM)  # 🧭 지역 길 찾기 메모
        cl.addWidget(self.step_area)
        cl.addWidget(self.step_text)
        cl.addWidget(self.step_gift)
        cl.addWidget(self.step_tip)
        root.addWidget(card)
        self.card = card

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

        # 보스전 간단 모드: 이 한 줄만 보이고 나머지는 숨긴다
        self.compact_lbl = _label(fs - 1, TEXT, True)
        self.compact_lbl.setVisible(False)
        root.insertWidget(0, self.compact_lbl)
        self.compact = False
        self._full = [w for w in (self.char_lbl, self.act_lbl, self.bar, self.timer_lbl, self.loc_lbl, card,
                                  self.gem_lbl, self.next_lbl, self.foot_lbl, self.reward_lbl, self.mode_box)]

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
               item_msg: str = "", gems=None, gem_names=None, gem_card: bool = False,
               item_color: str = ACCENT) -> None:
        rewards = rewards or []
        self._render_gems(gems, gem_names, hidden=gem_card)
        # 알림 창 카드: 순서 고정 (알림 → 아이템 비교 → 젬 → 정규식)
        cards = []
        if flash:
            cards.append(("", html.escape(flash), OK))
        if item_msg:
            cards.append(("⚔ 아이템 비교", item_msg, item_color))
        if gem_card:  # Ctrl+Alt+G
            if gems is not None:
                head, body = _gem_card(gems, gem_names)
                cards.append((head, body, ACCENT))
            else:
                cards.append(("💎 젬", f'<span style="color:{WARN}">이 캐릭터에 빌드가 지정되지 않았습니다</span>'
                              f'<br><span style="color:{DIM}">우클릭 → 빌드 (젬 안내) 에서 고르거나, 게임 빌드 플래너에 연결</span>', WARN))
        if regex and not flash:
            cards.append((f'🔎 {html.escape(regex.name)} 정규식 <span style="color:{DIM};font-weight:normal">· {html.escape(regex_key)} 복사</span>',
                          f'<span style="color:{ACCENT};font-family:Consolas">{html.escape(regex.regex)}</span>',  # 맑은 고딕은 \ 를 ₩ 로 그린다
                          DIM))
        self.toast.set_cards(cards, self.isVisible())
        self._follow()
        self.timer_lbl.setText(_timer_line(timer) if timer else "&nbsp;")  # 비어도 자리 유지
        self.step_gift.setText("")
        self.step_gift.setVisible(False)  # 보스·보상 표시가 있을 때만 보인다
        self.step_tip.setVisible(False)
        key = (s.character.name, s.character.zone) if s.character else None  # 지역을 옮기면 다시 내용에 맞게
        if key != self._grow_key:
            self._grow_key, self._min_h = key, 0
        self.reward_lbl.setVisible(False)
        c = s.character
        if c is None:
            if self.waiting:
                self.char_lbl.setText("PoE2 실행 대기 중")
                self.loc_lbl.setText("게임에 접속하면 캐릭터를 자동으로 이어서 추적합니다.")
            else:
                self.char_lbl.setText("캐릭터 없음")
                self.loc_lbl.setText("게임에서 지역을 이동하면 자동으로 인식합니다.")
            self.act_lbl.setText("")
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
        # 첫 줄은 이름·레벨만 (전직 이름이 길면 줄이 밀린다), 직업·전직은 리그 줄로
        cls = f'<span style="color:{TEXT}">{html.escape(c.cls)}</span>' if c.cls else ""
        if c.ascension:
            cls += f" {c.ascension}차"
        tag = "" if s.confirmed else f' <span style="color:{DIM};font-weight:normal">(추정)</span>'
        league = _league_line(s.league, c.mode, cls)
        self.char_lbl.setText(f"{name} · Lv {c.level}{tag}{league}")

        step = s.step
        if step:
            self.act_lbl.setText(f"{step.act}  {step.index + 1}/{s.total}")
            self.bar.setMaximum(max(1, s.total - 1))
            self.bar.setValue(step.index)

        loc = html.escape(c.area_name or c.zone or "-")
        loc_html = f"📍 {loc}"
        if c.area_level and not is_town(c.zone):  # 마을은 안전 지대라 레벨·경험치 표시 없음
            gap = c.area_level - c.level
            color = WARN if gap >= 3 else (OK if gap <= 0 else DIM)
            loc_html += f' · <span style="color:{color}">Lv {c.area_level}</span>'  # 한 줄에 들어가게 짧게
            if gap >= 3:
                loc_html += f' <span style="color:{WARN}">(−{gap})</span>'
            loc_html += " · " + _xp_badge(c.level, c.area_level)
        if s.off_route and not is_town(c.zone):
            loc_html += f' · <span style="color:{WARN}">가이드 경로 밖</span>'
        self.loc_lbl.setText(loc_html)

        if step:
            self.step_area.setText(html.escape(step.area))
            self.step_text.setText(rich(step.text) or "이동")
            here = s.character.zone if s.character else ""  # 하위 지역(집정관의 능묘 등)에 있으면 그 지역 메모
            if tip := self.zone_tips.get(here) or self.zone_tips.get(step.zone):
                self.step_tip.setText("🧭 " + html.escape(tip))
                self.step_tip.setVisible(True)
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
            gifts = [html.escape(r.slot.brief) + (f' <span style="color:{DIM}">· 추천: {html.escape(r.slot.tip)}</span>' if r.slot.tip else "")
                     for r in rewards if not r.done and r.slot.zone == step.zone]
            passive = [src for src in self.passive_sources if src.on(step.zone, step.text)]
            if passive and s.flags.get("passive"):  # 이 단계에서 이미 받음
                parts.append(f'<span style="color:{OK}">✓ 퀘스트 패시브 +2 받음</span>')
            elif passive:
                gifts += [f"퀘스트 패시브 +2 ({html.escape(src.label)})" for src in passive]
            if gifts:
                parts.append("🎁 " + " · ".join(gifts))
            if parts:
                self.step_gift.setText(" · ".join(parts))
                self.step_gift.setVisible(True)
        rows = []
        if s.upcoming:  # 바로 다음 단계만 전체 문구, 그 뒤는 지역 이름만
            st = s.upcoming[0]
            rows.append(f'<div><span style="color:{TEXT}">{html.escape(st.area)}</span> — {rich(st.text)}</div>')
            if rest := s.upcoming[1:]:
                rows.append(f'<div style="font-size:small;color:{DIM}">→ '
                            + " → ".join(html.escape(x.area) for x in rest) + "</div>")
        self.next_lbl.setText("".join(rows))

        foot = []
        if rewards:
            done = sum(r.done for r in rewards)
            line = (f'🏆 영구 보상 <b style="color:{TEXT}">{done}/{len(rewards)}</b>'
                    f' · 퀘스트 패시브 <b style="color:{TEXT}">{c.passive_points}/{passive_total}</b>')
            left = [r.slot for r in rewards if not r.done and step and r.slot.act == step.act]
            if left:
                line += f" · {html.escape(step.act)} 남음: " + " · ".join(
                    f'<span style="color:{GIFT}">{html.escape(sl.brief)}</span>' for sl in left)
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
        # 할 일 카드는 테두리·여백 때문에 전체 높이 계산에서 줄바꿈이 작게 잡힐 때가 있다(글자 겹침·잘림)
        # → 카드의 실제 폭 기준으로 필요한 높이를 최소 높이로 정해 둔다.
        m = lay.contentsMargins()
        card_w = self.card.width() if self.card.width() > 0 else self.width() - m.left() - m.right()
        self.card.setMinimumHeight(self.card.layout().totalHeightForWidth(card_w))
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

    def render_compact(self, html_text: str) -> None:
        """보스전: 한 줄만 남기고 알림 창도 숨긴다."""
        if not self.compact:
            self.compact = True
            for w in self._full:
                w.setVisible(False)
            self.compact_lbl.setVisible(True)
            self.toast.set_cards([], False)
        self.compact_lbl.setText(html_text)
        self._min_h = 0
        self._fit()

    def leave_compact(self) -> None:
        if not self.compact:
            return
        self.compact = False
        self.compact_lbl.setVisible(False)
        for w in self._full:
            if w not in (self.reward_lbl, self.mode_box):  # 이 둘은 render 가 필요할 때만 켠다
                w.setVisible(True)
        self._min_h = 0

    def show_mode_prompt(self, show: bool) -> None:
        if show:
            self.mode_msg.setText("새 캐릭터 — 모드를 선택하세요" + (
                " (Ctrl+Alt+T 로 클릭 통과를 끄고 선택)" if self.click_through else ""))
        if show != self.mode_box.isVisible():
            self.mode_box.setVisible(show)
            self._min_h = 0  # 선택 줄이 사라지면 창을 줄인다
            self._fit()

    def _render_gems(self, gems, names, hidden: bool = False) -> None:
        """패널에는 다음에 쓸 젬 한 줄만 (전체 세팅은 젬 카드 Ctrl+Alt+G). 젬 카드가 열려 있으면 숨김."""
        show = gems is not None and not hidden and bool(gems.upcoming)
        self.gem_lbl.setVisible(show)
        if not show:
            return
        nxt = gems.upcoming[0].lo
        soon = " · ".join(html.escape(names(g.id)) for g in gems.upcoming if g.lo == nxt)
        self.gem_lbl.setText(f'💎 <span style="color:{DIM}">다음 Lv {nxt}:</span> '
                             f'<span style="color:{GIFT}">{soon}</span>')

    def _clamped(self, pos: QPoint) -> QPoint:
        """pos 에 창을 두었을 때 화면 안에 들어오는 위치 (위쪽이 잘리면 캐릭터 줄이 안 보인다)."""
        center = pos + QPoint(self.width() // 2, self.height() // 2)
        screen = QGuiApplication.screenAt(center) or QGuiApplication.screenAt(QCursor.pos())             or QGuiApplication.primaryScreen()
        a = screen.availableGeometry()
        x = min(max(pos.x(), a.left()), a.right() + 1 - self.width())
        y = min(max(pos.y(), a.top()), a.bottom() + 1 - min(self.height(), a.height()))
        return QPoint(x, y)

    def clamp_to_screen(self) -> None:
        p = self._clamped(self.pos())
        if p != self.pos():
            self.move(p)

    def _follow(self) -> None:
        self.toast.follow(self.frameGeometry())

    def move(self, *args) -> None:
        super().move(*args)
        self._anchor = self.pos()

    def moveEvent(self, e):
        super().moveEvent(e)
        self._follow()
        # 높이가 커질 때 Windows 가 창을 위로 끌어올리는 경우가 있다 (화면 위로 잘림) → 정한 위치로 되돌린다
        if self._drag is None and self._anchor is not None and e.pos() != self._anchor:
            QTimer.singleShot(0, self._restore_anchor)

    def _restore_anchor(self) -> None:
        if self._drag is None and self._anchor is not None and self.pos() != self._anchor:
            super().move(self._anchor)

    def setVisible(self, visible: bool) -> None:
        super().setVisible(visible)
        self.toast.set_cards(self.toast.cards, visible)

    def setWindowOpacity(self, value: float) -> None:
        super().setWindowOpacity(value)  # 글자까지 함께 투명하게 (사용자 선택)
        self.toast.setWindowOpacity(value)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            # 옮길 위치를 먼저 화면 안으로 맞춘 뒤 한 번만 옮긴다 (밖으로 갔다 되돌아오면 가장자리에서 떨린다)
            p = self._clamped(e.globalPosition().toPoint() - self._drag)
            if p != self.pos():
                self.move(p)

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
    """가이드 패널 바로 아래(공간이 없으면 위)에 붙는 알림 창. 카드(머리글+본문)를 위아래로 쌓는다."""

    def __init__(self, fs: int, width: int):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("POE2 가이드 알림")
        self.fs = fs
        self.cards: list[tuple[str, str, str]] = []
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(6)
        self.setFixedWidth(width)

    def set_cards(self, cards: list[tuple[str, str, str]], parent_visible: bool) -> None:
        """cards: [(머리글 html, 본문 html, 테두리 색)]"""
        if cards != self.cards:
            self.cards = list(cards)
            while self.lay.count():
                w = self.lay.takeAt(0).widget()
                if w:
                    w.deleteLater()
            total = 0
            for head, body, color in cards:
                card = self._card(head, body, color)
                cl = card.layout()
                cl.activate()  # 카드 안 줄바꿈 글자 높이를 폭 기준으로 계산
                h = cl.totalHeightForWidth(self.width()) if cl.hasHeightForWidth() else card.sizeHint().height()
                card.setFixedHeight(h)
                self.lay.addWidget(card)
                card.show()  # 이미 떠 있는 창에 새로 넣은 카드는 직접 보이게 해야 한다
                total += h
            if cards:
                self.setFixedHeight(total + self.lay.spacing() * (len(cards) - 1))
        self.setVisible(bool(cards) and parent_visible)

    def _card(self, head: str, body: str, color: str) -> QFrame:
        f = QFrame()
        f.setObjectName("tcard")
        f.setStyleSheet(f"QFrame#tcard{{background:rgba(14,12,10,242);border:2px solid {color};border-radius:6px}}")
        lay = QVBoxLayout(f)
        lay.setContentsMargins(10, 6, 10, 8)
        lay.setSpacing(3)
        if head:
            h = _label(self.fs, color, True)
            h.setText(head)
            lay.addWidget(h)
        b = _label(self.fs, TEXT)
        b.setText(body)
        lay.addWidget(b)
        return f

    def setWindowOpacity(self, value: float) -> None:
        super().setWindowOpacity(max(value, 0.9))  # 카드는 패널보다 덜 투명하게 (읽기 쉽게)

    def follow(self, g) -> None:
        screen = self.screen().availableGeometry() if self.screen() else None
        y = g.bottom() + 6
        if screen is not None and y + self.height() > screen.bottom():
            y = g.top() - self.height() - 6
        self.move(g.left(), y)
