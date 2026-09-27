"""거래소 공개 데이터로 젬 영어→한국어 이름표(guides/gem_names_trade.json)를 만든다.

해외 거래소(영어)와 카카오 거래소(한국어)의 /api/trade2/data/items 는 같은 순서로 같은 목록을 준다.
새 리그·패치로 젬이 바뀌면 다시 실행: .venv\\Scripts\\python.exe tools\\update_gem_names.py
"""
import json
import sys
import urllib.request
from pathlib import Path

URLS = {
    "en": "https://www.pathofexile.com/api/trade2/data/items",
    "ko": "https://poe.kakaogames.com/api/trade2/data/items",
}
UA = "poe2-overlay/0.1 (personal leveling overlay)"
OUT = Path(__file__).resolve().parent.parent / "guides" / "gem_names_trade.json"
CHECK = {"Explosive Grenade": "폭발 유탄", "Deliberation": "신중"}  # 순서가 맞는지 확인용


def gems(lang: str) -> list[str]:
    req = urllib.request.Request(URLS[lang], headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    cat = next(c for c in data["result"] if c["id"] == "gem")
    return [e["type"] for e in cat["entries"]]


def main() -> int:
    en, ko = gems("en"), gems("ko")
    if len(en) != len(ko):
        print(f"개수가 다릅니다: en={len(en)} ko={len(ko)}")
        return 1
    table = dict(zip(en, ko))
    bad = {k: table.get(k) for k, v in CHECK.items() if table.get(k) != v}
    if bad:
        print("순서가 맞지 않습니다:", bad)
        return 1
    OUT.write_text(json.dumps({"_comment": "거래소 공개 데이터(영어/카카오)로 생성 — tools/update_gem_names.py",
                               "names": table}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(table)}개 → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
