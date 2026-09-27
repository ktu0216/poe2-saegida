"""설정/진행도 저장과 로그·가이드 파일 자동 탐색."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "poe2-overlay"
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
        return json.loads(path.read_text(encoding="utf-8"))
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


def _reim_guide_candidates() -> list[Path]:
    home = Path.home()
    roots = [home / "Desktop", home / "Downloads", home / "Documents", home / "OneDrive" / "바탕 화면"]
    out = []
    for r in roots:
        if not r.is_dir():
            continue
        # 최대 2단계 아래의 "PoE Act Guide*" 폴더
        for pat in ("PoE Act Guide*", "*/PoE Act Guide*"):
            for d in r.glob(pat):
                f = d / "data_editable" / "poe2" / "act_guide_1.csv"
                if f.is_file():
                    out.append(f)
    return out


def build_planner_dir() -> Optional[Path]:
    cfg = find_game_config()
    return cfg.parent / "BuildPlanner" if cfg else None


def find_reim_gem_data() -> Optional[Path]:
    """레임 가이드의 젬 한국어 이름 데이터 폴더 (data_editable/pob_leveling)."""
    for f in _reim_guide_candidates():
        d = f.parents[1] / "pob_leveling"
        if d.is_dir():
            return d
    return None


def find_guide(configured: str = "") -> Path:
    if configured and Path(configured).is_file():
        return Path(configured)
    reim = _reim_guide_candidates()
    if reim:
        return max(reim, key=lambda p: p.stat().st_mtime)
    return resource_dir() / "guides" / "default_ko.csv"
