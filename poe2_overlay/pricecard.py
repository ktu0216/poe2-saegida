"""시세 카드 HTML (app 과 문서용 스크린샷 tools/screenshots.py 가 같이 쓴다).

머리글: 💰 시세 · 리그 · 모드 (+ ↺ ↗ ✕ 아이콘)
본문: 아이템 → 최저·중간(크게) → 미끼 의심 → 매물 수 → 구분선 → 조건 줄들 → 옵션 한 줄
"""
from __future__ import annotations

import html
import re
from typing import Optional

from .i18n import t
from .trade import Query, Result, TradeData, bait, ex_text, price_text, summary

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")  # 옵션 문구 안의 숫자 자리
DIM, ACCENT, TEXT, OFF = "#9a9284", "#e8b04a", "#ece6da", "#6f685c"
MODE_COLOR = {"하드코어": "#ff6b5b", "HC SSF": "#ff6b5b", "SSF": "#7fb8ff"}


def card(q: Query, res: Result, data: Optional[TradeData], league: str, ssf: bool, lang: str,
         busy: bool = False, dirty: bool = False):
    """→ (머리글 html, 본문, 테두리 색, 아이콘들). 본문은 html 또는 (위 html, 조건 줄들, 아래 html)."""
    esc = html.escape
    dim = lambda s: f'<span style="color:{DIM}">{s}</span>'
    p = lambda a, c: esc(price_text(a, c, data, lang))
    exs = lambda v: esc(ex_text(v, lang))
    # 리그 · 모드 (메인 패널과 같은 색): "금단의 의식 · 하드코어", SSF 는 "(거래 리그 시세)"
    names = data.leagues if data else {}
    hc = league.startswith("HC ") or league == "Hardcore"
    shown = names.get(league[3:], league[3:]) if league.startswith("HC ") else names.get(league, league)
    mode = ("HC SSF" if hc else "SSF") if ssf else ("하드코어" if hc else "소프트코어")
    tag = f'<span style="color:{MODE_COLOR.get(mode, DIM)}">{esc(t(mode))}</span>'
    if ssf:
        tag += f' <span style="color:{DIM}">{t("(거래 리그 시세)")}</span>'
    head = (f'{t("💰 시세")} <span style="color:{DIM};font-weight:normal">· {esc(shown)} · </span>'
            f'<span style="font-weight:normal">{tag}</span>')
    title = f"<b>{esc(q.base or q.name)}</b>" + (f" {dim(esc(q.name))}" if q.rarity == "unique" else "")
    changed = any(f.changed for f in q.filters) or q.status != "securable" or q.indexed != "1week"
    tools = ((("↺", "r:reset", t("조건 원래대로")),) if changed and not q.exchange else ()) + (
        (("↗", res.url, t("거래소에서 열기")),) if res.url else ()) + (("✕", "x:close", t("닫기")),)
    if q.exchange:  # 화폐·룬 …: 교환소 1개 가격
        if res.unit_ex is None:
            body = t("교환소에 엑잘로 사는 매물이 없습니다")
        else:
            one = t("1개 ≈ {p}", p=f'<b style="color:{ACCENT}">{exs(res.unit_ex)}</b>')
            body = f"<big>{one}</big><br>" + dim(t("교환소 온라인 매물 {n}개", n=res.total))
        return head, f"{title}<br>{body}", "#e0b862", tools
    # 조건 줄: 숫자는 굵게(휠로 바꾼 값은 노란색), "이상/이하" 는 뒤에 한 번
    chips, opts = [], []
    for i, f in enumerate(q.filters):
        if f.kind == "opt":  # 타락: 아래 옵션 줄로
            state = {"": t("상관없음"), "false": t("타락 아님"), "true": t("타락만")}[f.text]
            if f.text != f.orig_text:
                state = f'<span style="color:{ACCENT}">{state}</span>'
            opts.append(f'<a href="f:{i}" style="color:{TEXT};text-decoration:none">⇄ {t("타락")}: {state}</a>')
            continue
        box = "☑" if f.enabled else "☐"
        color = TEXT if f.enabled else OFF
        if f.kind == "type":
            text = t("베이스 {name}", name=esc(f.label))
        elif f.value is None:
            text = esc(t(f.label))
        else:
            n = f"{f.value:g}"
            n = f'<b style="color:{ACCENT}">{n}</b>' if f.value != f.orig else f"<b>{n}</b>"
            more = t("이상") if f.min is not None else t("이하")
            if f.avg:  # "번개 피해 1~18 추가" → 거래소는 평균으로 비교
                text = f"{esc(f.label)} {dim(t('평균'))} {n}{f.unit} {more}"
            elif f.kind == "stat" and not f.key.startswith("pseudo.") and (m := _NUM_RE.search(f.label)):
                # 옵션 한 줄: 문구 안의 숫자를 기준값으로 ("민첩 +25" → "민첩 +25 이상")
                text = esc(f.label[:m.start()]) + n + esc(f.label[m.end():]) + " " + more
            else:
                text = f"{esc(t(f.label))} {n}{f.unit} {more}"
        chips.append((str(i), f'<a href="f:{i}" style="color:{color};text-decoration:none">{box} {text}</a>'))
    opts = [f'<a href="o:status" style="color:{TEXT};text-decoration:none">'
            f'{"☑" if q.status == "securable" else "☐"} {t("즉시 구매만")}</a>',
            f'<a href="o:indexed" style="color:{TEXT};text-decoration:none">'
            f'{"☑" if q.indexed else "☐"} {t("최근 1주일")}</a>'] + opts
    rule = f'<hr>{dim(t("조건 · 누르면 켜고 끄기 · 휠로 수치"))}'
    bottom = " &nbsp; ".join(opts)
    if busy:
        bottom += "<br>" + dim(t("다시 찾는 중…"))
    elif dirty:  # 여러 개를 고른 뒤 한 번에 찾기 (위 가격은 바꾸기 전 조건)
        bottom += (f'<br><a href="s:go" style="color:{ACCENT}">{t("🔍 이 조건으로 다시 검색")}</a>'
                   + " " + dim(t("(위 가격은 바꾸기 전 조건)")))
    rows = tuple(chips)
    if not res.listings:
        return head, (f"{title}<br>{t('비슷한 매물이 없습니다')}{rule}", rows, bottom), DIM, tools
    low, mid, _groups = summary(res)
    ex_part = lambda l: f" {dim('≈' + exs(l.ex))}" if l.ex is not None and l.currency != "exalted" else ""
    # 최저·중간을 한 줄씩 (한 줄에 넣으면 엑잘 환산이 다음 줄로 꺾인다)
    big = ("<big>" + t("최저 {p}", p=f'<b style="color:{ACCENT}">{p(low.amount, low.currency)}</b>') + "</big>"
           + ex_part(low) + "<br><big>" + t("중간 {p}", p=f"<b>{p(mid.amount, mid.currency)}</b>") + "</big>"
           + ex_part(mid))
    if bait(res):
        big += f'<br><span style="color:#ff8a65">{t("⚠ 최저가가 유난히 쌉니다 (미끼일 수 있음)")}</span>'
    known = [l.ex for l in res.listings if l.ex is not None]
    if len(known) == len(res.listings):  # 싼 10개를 엑잘로 한 줄
        count = t("매물 {n}개 · 싼 {k}개 {lo}~{hi}", n=res.total, k=len(res.listings),
                  lo=ex_text(min(known), lang).split(" ")[0], hi=exs(max(known)))
    else:
        count = t("매물 {n}개", n=res.total)
    return head, (f"{title}<br>{big}<br>{dim(count)}{rule}", rows, bottom), "#e0b862", tools
