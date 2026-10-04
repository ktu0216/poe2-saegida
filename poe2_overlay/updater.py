"""새 버전 확인과 업데이트 (GitHub 릴리스).

보내는 것: GitHub 에 최신 릴리스 정보를 한 번 묻는 요청뿐 (게임 데이터·로그·캐릭터 정보는 보내지 않는다).
설치본이면 설치 파일을 내려받아(크기·SHA-256 확인) 조용히 덮어쓰기 설치 후 다시 실행, 휴대용이면 릴리스 페이지를 연다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import __version__

REPO = "ktu0216/poe2-saegida"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGE = f"https://github.com/{REPO}/releases/latest"
UA = f"poe2-saegida/{__version__} (update check)"


@dataclass
class Release:
    version: str
    page_url: str
    setup_url: str = ""
    setup_name: str = ""
    setup_size: int = 0
    sha256: str = ""  # GitHub 가 주는 자산 digest (없으면 크기만 확인)


def parse_version(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", text)[:3]) or (0,)


def is_newer(latest: str, current: str = __version__) -> bool:
    return parse_version(latest) > parse_version(current)


def parse_release(data: dict) -> Optional[Release]:
    tag = data.get("tag_name") or ""
    if not tag or data.get("draft") or data.get("prerelease"):
        return None
    rel = Release(tag.lstrip("vV"), data.get("html_url") or PAGE)
    for a in data.get("assets") or []:
        name = a.get("name") or ""
        if name.lower().endswith(".exe") and "setup" in name.lower():
            rel.setup_url = a.get("browser_download_url") or ""
            rel.setup_name = name
            rel.setup_size = int(a.get("size") or 0)
            digest = a.get("digest") or ""
            rel.sha256 = digest.split(":", 1)[1] if digest.startswith("sha256:") else ""
    return rel


def fetch_latest(timeout: float = 6.0) -> Optional[Release]:
    req = urllib.request.Request(API, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return parse_release(json.loads(r.read().decode("utf-8")))


def installed() -> bool:
    """설치 파일로 설치한 경우 (사용자별 설치 위치). 휴대용·개발 실행은 False."""
    if not getattr(sys, "frozen", False):
        return False
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "poe2-saegida"
    try:
        return Path(sys.executable).resolve().parent == base.resolve()
    except OSError:
        return False


def download(rel: Release, dest_dir: Path, progress: Optional[Callable[[int, int], None]] = None,
             timeout: float = 30.0) -> Path:
    """설치 파일을 받아 크기와 SHA-256 을 확인한다. 맞지 않으면 지우고 예외."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / (rel.setup_name or "poe2-saegida-setup.exe")
    part = out.with_suffix(".part")
    h = hashlib.sha256()
    got = 0
    req = urllib.request.Request(rel.setup_url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(part, "wb") as f:
        while chunk := r.read(256 * 1024):
            f.write(chunk)
            h.update(chunk)
            got += len(chunk)
            if progress:
                progress(got, rel.setup_size)
    if (rel.setup_size and got != rel.setup_size) or (rel.sha256 and h.hexdigest().lower() != rel.sha256.lower()):
        part.unlink(missing_ok=True)
        raise ValueError("downloaded installer does not match the release (size/SHA-256)")
    part.replace(out)
    return out
