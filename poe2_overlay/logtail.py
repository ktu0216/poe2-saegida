"""로그 파일 끝을 따라 읽는다. 게임이 파일을 쓰는 중에도 공유 읽기로 연다."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator


class LogTail:
    def __init__(self, path: Path, offset: int = 0):
        self.path = path
        self.offset = offset
        self._partial = b""

    def size(self) -> int:
        try:
            return os.path.getsize(self.path)
        except OSError:
            return -1

    def read_new(self, max_bytes: int = 64 * 1024 * 1024) -> list[str]:
        size = self.size()
        if size < 0:
            return []
        if size < self.offset:  # 파일이 비워졌거나 새로 만들어짐
            self.offset = 0
            self._partial = b""
        if size == self.offset:
            return []
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            data = f.read(min(size - self.offset, max_bytes))
        self.offset += len(data)
        data = self._partial + data
        *complete, self._partial = data.split(b"\n")
        return [ln.decode("utf-8", errors="replace") for ln in complete]


def iter_lines(path: Path, start: int, end: int, chunk: int = 8 * 1024 * 1024) -> Iterator[str]:
    """[start, end) 구간의 완전한 줄만 돌려준다 (처음 잘린 줄은 버림)."""
    with open(path, "rb") as f:
        f.seek(start)
        pos = start
        partial = b""
        first = start > 0
        while pos < end:
            data = f.read(min(chunk, end - pos))
            if not data:
                break
            pos += len(data)
            data = partial + data
            *complete, partial = data.split(b"\n")
            if first and complete:
                complete = complete[1:]
                first = False
            for ln in complete:
                yield ln.decode("utf-8", errors="replace")
