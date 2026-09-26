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
    "window": {"x": 40, "y": 120, "w": 420},
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


def find_guide(configured: str = "") -> Path:
    if configured and Path(configured).is_file():
        return Path(configured)
    reim = _reim_guide_candidates()
    if reim:
        return max(reim, key=lambda p: p.stat().st_mtime)
    return resource_dir() / "guides" / "default_ko.csv"
