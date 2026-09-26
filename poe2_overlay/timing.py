"""액트 스플릿: 캐릭터별 액트 구간 시간과 과거 캐릭터 기록 중 최고(PB) 비교."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from .tracker import PLACEHOLDERS, Character

MIN_SPLIT = 60  # 이보다 짧은 구간은 비정상(지역만 스쳐감)으로 보고 PB에서 제외
ENDGAME = "엔드게임"
CAMPAIGN = "캠페인 전체"


def fmt(seconds: float) -> str:
    s = int(max(0, seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_delta(seconds: float) -> str:
    sign = "+" if seconds > 0 else "-"
    return sign + fmt(abs(seconds))


def act_durations(c: Character) -> list[tuple[str, float, bool]]:
    """(액트, 걸린 시간, 끝났는지). 마지막(진행 중) 액트는 현재 플레이 시간까지."""
    order = sorted(c.splits.items(), key=lambda kv: kv[1])
    out = []
    for i, (act, start) in enumerate(order):
        if act == ENDGAME:  # 엔드게임 진입은 캠페인 끝 표시일 뿐 구간이 아니다
            continue
        if i + 1 < len(order):
            out.append((act, order[i + 1][1] - start, True))
        else:
            out.append((act, c.play_seconds - start, False))
    return out


def personal_bests(chars: Iterable[Character], exclude: Optional[str] = None) -> dict[str, float]:
    """액트별 최단 완료 시간. 지금 캐릭터는 제외해서 '이전 기록'과 비교한다."""
    best: dict[str, float] = {}
    for c in chars:
        if c.name == exclude or c.name in PLACEHOLDERS:
            continue
        for act, dur, done in act_durations(c):
            if done and dur >= MIN_SPLIT and (act not in best or dur < best[act]):
                best[act] = dur
        if ENDGAME in c.splits:  # 캠페인 완주 시간
            total = c.splits[ENDGAME] - min(c.splits.values())
            if total >= MIN_SPLIT and (CAMPAIGN not in best or total < best[CAMPAIGN]):
                best[CAMPAIGN] = total
    return best


@dataclass
class TimerView:
    act: str
    act_time: float
    total: float
    pb: Optional[float]
    rows: list[tuple[str, float, bool, Optional[float]]]  # 액트, 시간, 완료, PB


def timer_view(c: Character, pbs: dict[str, float], live_extra: float = 0.0) -> Optional[TimerView]:
    if not c.splits:
        return None
    rows = []
    durs = act_durations(c)
    for act, dur, done in durs:
        rows.append((act, dur if done else dur + live_extra, done, pbs.get(act)))
    if not rows:
        return None
    if ENDGAME in c.splits:
        rows.append((CAMPAIGN, c.splits[ENDGAME] - min(c.splits.values()), True, pbs.get(CAMPAIGN)))
    cur_act, cur_time, _, cur_pb = next(r for r in reversed(rows) if r[0] != CAMPAIGN)
    return TimerView(cur_act, cur_time, c.play_seconds + live_extra, cur_pb, rows)
