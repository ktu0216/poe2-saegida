"""설정/진행도 저장과 로그·가이드 파일 자동 탐색."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "poe2-saegida"
_OLD_APP_DIR = APP_DIR.parent / "poe2-overlay"  # 이름을 바꾸기 전 (0.1.0 이전) 설정·진행 기록
if not APP_DIR.exists() and _OLD_APP_DIR.is_dir():
    try:
        _OLD_APP_DIR.rename(APP_DIR)
    except OSError:  # 옛 버전이 아직 실행 중이라 파일이 잠겨 있으면 복사
        import shutil
        try:
            shutil.copytree(_OLD_APP_DIR, APP_DIR)
        except OSError:
            pass
SETTINGS_FILE = APP_DIR / "settings.json"
PROGRESS_FILE = APP_DIR / "progress.json"


def resource_dir() -> Path:
    """번들 리소스(guides/) 위치. PyInstaller 로 묶였을 때도 동작."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else Path(__file__).resolve().parent.parent


DEFAULTS: dict[str, Any] = {
    "log_path": "",
    "guide_path": "",
    "window": {"x": None, "y": None, "w": 420},  # x/y 가 None 이면 게임 창 오른쪽 위
    "opacity": 0.88,
    "font_size": 13,
    "upcoming": 3,
    "click_through": False,
}


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))  # 메모장·PowerShell 로 저장하면 BOM 이 붙는다
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_settings() -> dict:
    s = json.loads(json.dumps(DEFAULTS))
    s.update(_read_json(SETTINGS_FILE))
    return s


def save_settings(s: dict) -> None:
    _write_json(SETTINGS_FILE, s)


def load_progress() -> dict:
    return _read_json(PROGRESS_FILE)


def save_progress(p: dict) -> None:
    _write_json(PROGRESS_FILE, p)


# ------------------------------------------------------------------ 탐색
def _log_candidates() -> list[Path]:
    pf86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    cands = [
        Path(r"C:\Daum Games\Path of Exile2\logs\KakaoClient.txt"),
        pf86 / "Steam/steamapps/common/Path of Exile 2/logs/Client.txt",
        pf / "Steam/steamapps/common/Path of Exile 2/logs/Client.txt",
        pf86 / "Grinding Gear Games/Path of Exile 2/logs/Client.txt",
        pf / "Grinding Gear Games/Path of Exile 2/logs/Client.txt",
    ]
    # ExileCompass 에 설정된 경로가 있으면 재사용
    ec = _read_json(Path(os.environ.get("APPDATA", "")) / "com.juddisjudd.exilecompass" / "settings.json")
    if p := ec.get("EXILECOMPASS_POE2_LOG_FILE_PATH_V1"):
        cands.insert(0, Path(p))
    for drive in "DEF":
        cands.append(Path(f"{drive}:/Daum Games/Path of Exile2/logs/KakaoClient.txt"))
        cands.append(Path(f"{drive}:/SteamLibrary/steamapps/common/Path of Exile 2/logs/Client.txt"))
    return cands


def find_log(configured: str = "") -> Optional[Path]:
    if configured and Path(configured).is_file():
        return Path(configured)
    found = [p for p in _log_candidates() if p.is_file()]
    if not found:
        return None
    return max(found, key=lambda p: p.stat().st_mtime)


def find_game_config() -> Optional[Path]:
    """POE2 설정 파일 (캐릭터 선택 화면에서 고른 리그가 league_selected 로 저장됨)."""
    docs = [Path.home() / "Documents", Path.home() / "OneDrive" / "Documents", Path.home() / "OneDrive" / "문서"]
    for d in docs:
        p = d / "My Games" / "Path of Exile 2" / "poe2_production_Config.ini"
        if p.is_file():
            return p
    return None


def read_league(path: Optional[Path]) -> str:
    if not path:
        return ""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("league_selected="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def read_active_builds(path: Optional[Path]) -> dict[str, str]:
    """게임 설정의 active_builds: 캐릭터 이름 -> 빌드 플래너 이름(파일 안 name, 없으면 파일명)."""
    if not path:
        return {}
    try:
        line = next((ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
                     if ln.startswith("active_builds=")), "")
        entries = json.loads(line.split("=", 1)[1]) if line else []
    except (OSError, ValueError):
        return {}
    out = {}
    for e in entries:
        char, ref = e.get("character"), e.get("path", "")
        if not char or not ref:
            continue
        file = Path(ref[5:] if ref.startswith("file:") else ref)
        name = file.stem
        try:
            name = json.loads(file.read_text(encoding="utf-8", errors="replace")).get("name") or name
        except (OSError, ValueError):
            pass
        out[char] = name
    return out


def build_planner_dir() -> Optional[Path]:
    cfg = find_game_config()
    return cfg.parent / "BuildPlanner" if cfg else None


GUIDE_KINDS = ("default", "speedrun")  # 동봉 가이드: 기본(보상 다 챙기기) / 스피드런


def bundled_guide(kind: str, lang: str) -> Optional[Path]:
    p = resource_dir() / "guides" / f"{kind}_{lang}.csv"
    return p if p.is_file() else None


def find_guide(configured: str = "", lang: str = "ko", kind: str = "default") -> Path:
    """메뉴에서 고른 CSV, 없으면 동봉 가이드(종류·화면 언어), 그것도 없으면 기본 가이드."""
    if configured and Path(configured).is_file():
        return Path(configured)
    for k, lg in ((kind, lang), ("default", lang), ("default", "ko")):
        if p := bundled_guide(k, lg):
            return p
    return resource_dir() / "guides" / "default_ko.csv"


def data_file(name: str, lang: str = "ko") -> Path:
    """guides/<name>_<lang>.json, 없으면 한국어 파일 (영어 데이터가 아직 없는 항목)."""
    d = resource_dir() / "guides"
    p = d / f"{name}_{lang}.json"
    return p if p.is_file() else d / f"{name}_ko.json"


def load_zone_tips(path: Path) -> dict[str, str]:
    """지역 코드(소문자) → 길 찾기 메모."""
    return {k.lower(): v for k, v in (_read_json(path).get("tips") or {}).items()}
