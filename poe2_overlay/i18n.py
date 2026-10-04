"""화면 문구 번역 (한국어 기본, 영어 추가).

한국어 문구를 그대로 키로 쓴다: t("세션 지도 {n}판", n=3). 언어가 en 이면 EN 사전에서 찾고, 없으면 한국어 그대로.
저장 데이터·내부 키(액트 이름 "액트 1", 모드 "하드코어" 등)는 바꾸지 않고 화면에 보일 때만 번역한다.
"""
from __future__ import annotations

import re

LANG = "ko"  # "ko" | "en"
LANGS = ("auto", "ko", "en")  # 설정값: auto = 로그 파일(Client.txt → 영어, KakaoClient.txt → 한국어)


def set_lang(lang: str) -> None:
    global LANG
    LANG = "en" if lang == "en" else "ko"


def resolve(setting: str, log_path) -> str:
    """설정(auto/ko/en)과 로그로 실제 언어. auto 는 로그 내용(마지막 지역 이름이 한글인지), 없으면 파일 이름."""
    if setting in ("ko", "en"):
        return setting
    if lang := detect_log_lang(log_path):
        return lang
    name = str(log_path or "").lower()
    return "ko" if not name or "kakao" in name else "en"


_SCENE = re.compile(rb"\[SCENE\] Set Source \[([^\]\r\n]+)\]")
_HANGUL = re.compile("[가-힣]")


def scene_lang(name: str) -> str:
    """지역 이름(로그 [SCENE]) → 게임 클라이언트 언어. 카카오판도 영어로 바꿀 수 있어 파일 이름만으로는 모른다."""
    return "ko" if _HANGUL.search(name) else "en"


def detect_log_lang(log_path, tail: int = 2 * 1024 * 1024) -> str:
    """로그 끝부분의 마지막 지역 이름으로 게임 언어. 모르면 ""."""
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - tail))
            data = f.read()
    except (OSError, TypeError):
        return ""
    for m in reversed(_SCENE.findall(data)):
        name = m.decode("utf-8", "replace")
        if name not in ("(null)", "(unknown)"):
            return scene_lang(name)
    return ""


def t(ko: str, **kw) -> str:
    s = EN.get(ko, ko) if LANG == "en" else ko
    return s.format(**kw) if kw else s


_ACT = re.compile(r"^(액트|막간) (\d+)$")


def act(name: str) -> str:
    """액트 이름 (내부 키) → 화면 표시."""
    if LANG != "en":
        return name
    if m := _ACT.match(name):
        return ("Act " if m[1] == "액트" else "Interlude ") + m[2]
    return EN.get(name, name)


# 직업·전직 이름: 로그에 찍힌 게임 언어 그대로 저장되므로 화면에 보일 때 바꾼다
CLASS_EN = {  # poe2db.tw/kr·us Ascendancy_class 공식 표기 (2026-10-05)
    "워리어": "Warrior", "머서너리": "Mercenary", "레인저": "Ranger", "헌트리스": "Huntress",
    "위치": "Witch", "소서리스": "Sorceress", "몽크": "Monk", "드루이드": "Druid",
    "머라우더": "Marauder", "듀얼리스트": "Duelist", "쉐도우": "Shadow", "템플러": "Templar",
    "타이탄": "Titan", "워브링어": "Warbringer", "스미스 오브 키타바": "Smith of Kitava",
    "택티션": "Tactician", "위치헌터": "Witchhunter", "젬링 리저네어": "Gemling Legionnaire",
    "데드아이": "Deadeye", "패스파인더": "Pathfinder",
    "아마존": "Amazon", "스피릿 워커": "Spirit Walker", "리추얼리스트": "Ritualist",
    "인퍼널리스트": "Infernalist", "블러드 메이지": "Blood Mage", "리치": "Lich", "심연의 리치": "Abyssal Lich",
    "스톰위버": "Stormweaver", "크로노맨서": "Chronomancer", "디사이플 오브 바라시타": "Disciple of Varashta",
    "마셜 아티스트": "Martial Artist", "인보커": "Invoker", "애컬라이트 오브 차율라": "Acolyte of Chayula",
    "오라클": "Oracle", "샤먼": "Shaman",
}
CLASS_KO = {v: k for k, v in CLASS_EN.items()}


def cls(name: str) -> str:
    """직업 이름 (게임 언어) → 화면 언어."""
    return CLASS_EN.get(name, name) if LANG == "en" else CLASS_KO.get(name, name)


EN: dict[str, str] = {
    # 액트·모드 (내부 키)
    "엔드게임": "Endgame",
    "캠페인 전체": "Campaign",
    "소프트코어": "Softcore",
    "하드코어": "Hardcore",
    "미지정": "Not set",
    # 패널
    "캠페인 완료": "Campaign done",
    "전체": "Total",
    "구간 기록": "Splits",
    "(PB = 이전 캐릭터 최고)": "(PB = best of previous characters)",
    "(보조 젬 없음)": "(no supports)",
    "다음": "Next",
    "젬": "Gems",
    "{n}개 모두 받음": "all {n} received",
    "경험치 {pct}%": "XP {pct}%",
    "세션 지도 {n}판": "Session maps {n}",
    "평균 {v}": "avg {v}",
    "사망 {n}": "deaths {n}",
    "누적 {n}": "total {n}",
    "최종 보스 처치 {k} · 도전 {n}": "Pinnacle kills {k} · attempts {n}",
    "최종 보스": "Pinnacle bosses",
    "(처치는 확인되는 보스만)": "(kills only where the log confirms them)",
    "처치 {k} / 도전 {n}": "kills {k} / attempts {n}",
    "도전 {n}": "attempts {n}",
    " · 사망 {n}": " · deaths {n}",
    "POE2 새기다": "POE2 Saegida",
    "새 캐릭터 — 모드를 선택하세요": "New character — choose a mode",
    " (Ctrl+Alt+T 로 클릭 통과를 끄고 선택)": " (turn off click-through with Ctrl+Alt+T first)",
    "건너뛰기": "Skip",
    "⚔ 아이템 비교": "⚔ Item compare",
    "💎 젬": "💎 Gems",
    "이 캐릭터에 빌드가 지정되지 않았습니다": "No build is set for this character",
    "우클릭 → 빌드 (젬 안내) 에서 고르거나, 게임 빌드 플래너에 연결":
        "Right-click → Build (gem guide), or link one in the in-game Build Planner",
    "{name} 정규식": "{name} regex",
    "{key} 복사": "{key} to copy",
    "PoE2 실행 대기 중": "Waiting for PoE2",
    "게임에 접속하면 캐릭터를 자동으로 이어서 추적합니다.": "Log in and tracking continues automatically.",
    "캐릭터 없음": "No character",
    "게임에서 지역을 이동하면 자동으로 인식합니다.": "Change area in game and the character is detected.",
    "대기 중…": "Waiting…",
    "캐릭터 확인 중": "Identifying character",
    "접속 중": "Connecting",
    "레벨업·보상·사망 메시지가 나오면 자동으로 확정됩니다.":
        "Confirmed automatically on the next level-up, reward or death message.",
    "우클릭 → 캐릭터 메뉴에서 직접 고를 수도 있습니다.": "Or pick it from Right-click → Character.",
    "새 캐릭터 (이름 확인 중)": "New character (name pending)",
    " {n}차": " · Asc {n}",
    "(추정)": "(guess)",
    "가이드 경로 밖": "off the guide route",
    "이동": "Move on",
    "🗺 엔드게임": "🗺 Endgame",
    "전투 중": "fighting",
    "처치": "killed",
    "에게 사망": " — died",
    "⚔ {boss} 전투 중": "⚔ fighting {boss}",
    "✓ {boss} 처치": "✓ {boss} killed",
    "☠ {boss}에게 사망": "☠ died to {boss}",
    "· 추천: {tip}": "· pick: {tip}",
    "✓ 퀘스트 패시브 +2 받음": "✓ quest passives +2 received",
    "퀘스트 패시브 +2 ({src})": "quest passives +2 ({src})",
    "🏆 영구 보상 {v}": "🏆 Permanent rewards {v}",
    " · 퀘스트 패시브 {v}": " · quest passives {v}",
    " · {act} 남음: ": " · left in {act}: ",
    "🔒 클릭 통과 중 (Ctrl+Alt+T 해제)": "🔒 Click-through on (Ctrl+Alt+T to turn off)",
    "다음 Lv {lv}:": "Next Lv {lv}:",
    "이전 단계 (Ctrl+Alt+←)": "Previous step (Ctrl+Alt+←)",
    "다음 단계 (Ctrl+Alt+→)": "Next step (Ctrl+Alt+→)",
    "영구 보상·구간 기록 (Ctrl+Alt+R)": "Rewards & splits (Ctrl+Alt+R)",
    "젬 카드 (Ctrl+Alt+G)": "Gem card (Ctrl+Alt+G)",
    "전체 메뉴 (우클릭과 같음)": "Full menu (same as right-click)",
    "POE2 가이드 알림": "POE2 guide notices",
    # 보스전 간단 모드
    "보스": "boss",
    "⚔ {name} 전투 중": "⚔ fighting {name}",
    "⚠ 곧 {name}": "⚠ {name} soon",
    " · Lv {lv} · 지역 {area}": " · Lv {lv} · area {area}",
    "· Tab→미니맵": "· Tab→minimap",
    # 알림
    "단축키 등록 실패: ": "Hotkey registration failed: ",
    "로그 파일을 찾지 못했습니다. 메뉴 → 로그 파일 선택": "Log file not found. Menu → Choose log file",
    "💎 Lv {lv} — {names} 장착 가능": "💎 Lv {lv} — {names} can be equipped",
    "📋 {name} 정규식 복사됨 — 검색창에 Ctrl+V": "📋 {name} regex copied — Ctrl+V in the search box",
    "자동 숨김 켜짐": "Auto-hide on",
    "자동 숨김 꺼짐 (항상 표시)": "Auto-hide off (always shown)",
    # 아이템 비교
    "두 번 복사": "double copy",
    "📌 장착 중 ({slot}) · {title}": "📌 Equipped ({slot}) · {title}",
    "장착 기준 없음 — 장착 중인 아이템이면 한 번 더 Ctrl+C (또는 {key}) 로 등록":
        "No equipped item saved — if you wear this, Ctrl+C again (or {key}) to save it",
    "▲ 더 좋음": "▲ better",
    "▼ 더 나쁨": "▼ worse",
    "≈ 비슷": "≈ similar",
    "(직전 복사 대비)": "(vs. previous copy)",
    "📌 {slot} 장착 기준 저장 · {title}": "📌 Saved as equipped {slot} · {title}",
    "{slot} 대비": "vs. {slot}",
    " (약한 쪽)": " (weaker)",
    "({slot} 대비)": "(vs. {slot})",
    "장착했다면 한 번 더 Ctrl+C (또는 {key}) 로 기준 갱신": "If you equipped it, Ctrl+C again (or {key}) to update",
    "미가공 스킬 젬": "Uncut Skill Gem",
    "미가공 보조 젬": "Uncut Support Gem",
    "미가공 정신력 젬": "Uncut Spirit Gem",
    " ({lv}레벨)": " (level {lv})",
    "빌드가 연결되지 않았습니다 — 우클릭 메뉴 → 빌드 (젬 안내)": "No build linked — Right-click → Build (gem guide)",
    "💎 {title} → 빌드 기준": "💎 {title} → for your build",
    "📌 {how}{slot} 장착 기준 등록 · {title}": "📌 {how}saved as equipped {slot} · {title}",
    "{other} 자리에 꼈다면 한 번 더 두 번 복사 (또는 {key})": "Worn in {other}? Double copy again (or {key})",
    "반지 1": "Ring 1",
    " 또는 ": " or ",
    "물리": "Phys",
    "원소": "Ele",
    "공속": "APS",
    "치명": "Crit",
    "방어도": "Armour",
    "회피": "Evasion",
    "에너지 보호막": "Energy Shield",
    "생명력": "Life",
    "저항 합": "Total res",
    "이동 속도": "Move speed",
    "공격 추가 피해": "Added attack dmg",
    "정신력": "Spirit",
    "{kind} 스킬 레벨": "{kind} skill levels",
    "반지 2": "Ring 2",
    # 메뉴
    "다음 단계  ({key})": "Next step  ({key})",
    "이전 단계  ({key})": "Previous step  ({key})",
    "캐릭터": "Character",
    "자동 인식": "Auto-detect",
    "모드: {mode}": "Mode: {mode}",
    "모드": "Mode",
    "빌드 (젬 안내)": "Build (gem guide)",
    "게임에 연결된 빌드 따라가기": "Follow the build linked in game",
    "{label}  ({n}개 구간)": "{label}  ({n} stages)",
    "투명도: {v}%  ({key} / Down)": "Opacity: {v}%  ({key} / Down)",
    "보스전 간단 모드 (한 줄)": "Compact mode in boss fights (one line)",
    "보스전 시작 시 Tab → 미니맵 안내": "Tab → minimap hint when a boss fight starts",
    "지역 길 찾기 메모 (🧭)": "Zone layout tips (🧭)",
    "상인 대화 시 정규식 자동 복사": "Auto-copy vendor regex",
    "PB 비교 표시 (연습용)": "Show PB comparison (practice)",
    "클릭 통과  ({key})": "Click-through  ({key})",
    "숨기기/보이기  ({key})": "Hide / show  ({key})",
    "게임 창이 아닐 때 자동 숨김  ({key})": "Auto-hide when the game is not focused  ({key})",
    "영구 보상 전체 목록  ({key})": "All rewards & splits  ({key})",
    "젬 카드  ({key})": "Gem card  ({key})",
    "위치 초기화 (왼쪽 위 기본 위치)": "Reset position (top-left)",
    "가이드 CSV 선택…": "Choose guide CSV…",
    "가이드 파일 열기": "Open guide file",
    "로그 파일 선택…": "Choose log file…",
    "가이드: {name} ({n}단계)": "Guide: {name} ({n} steps)",
    "로그: {path}": "Log: {path}",
    "없음": "none",
    "종료": "Quit",
    "언어 / Language": "Language / 언어",
    "🆕 {v} 내려받는 중…": "🆕 Downloading {v}…",
    "최신 버전입니다 ({v})": "You are on the latest version ({v})",
    "업데이트 확인 실패: {e}": "Update check failed: {e}",
    "🆕 새 버전 {v} — 우클릭 → 업데이트": "🆕 Version {v} is out — right-click → update",
    "🆕 업데이트 설치 ({v})": "🆕 Install update ({v})",
    "🆕 새 버전 받기 ({v}) — 릴리스 페이지": "🆕 Get version {v} — release page",
    "업데이트 (현재 {v})": "Updates (current {v})",
    "지금 확인": "Check now",
    "캠페인": "Campaign",
    "캠페인 완주": "Campaign complete",
    "🏁 캠페인 완주! 완주 카드 저장: {p}": "🏁 Campaign complete! Card saved: {p}",
    "완주 카드 저장: {p}": "Campaign card saved: {p}",
    "LiveSplit 파일 저장: {p}": "LiveSplit file saved: {p}",
    "기록 내보내기": "Export records",
    "캠페인 완주 카드 (PNG)": "Campaign complete card (PNG)",
    "LiveSplit 스플릿 파일 (.lss)": "LiveSplit splits file (.lss)",
    "저장 폴더 열기": "Open the export folder",
    "새 버전 자동 확인": "Check for new versions automatically",
    "자동 (로그 파일 기준)": "Auto (from the log file)",
    "POE2 로그 파일 선택": "Choose the POE2 log file",
    "로그 (*.txt)": "Log (*.txt)",
    "가이드 CSV 선택": "Choose guide CSV",
}
