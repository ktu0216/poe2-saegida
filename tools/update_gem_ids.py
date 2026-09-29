"""Path of Building(PoE2) 의 Data/Gems.lua 로 젬 내부 ID → 표시 영어 이름 표(guides/gem_ids_pob.json)를 만든다.

빌드 플래너 파일(.build)은 게임 내부 ID(SupportGemMartialTempo)를 쓰는데, 게임·거래소에 보이는 이름은
다르다(Rapid Attacks I). 이 표로 표시 이름을 찾은 뒤 거래소 이름표(gem_names_trade.json)로 한국어를 찾는다.
정신력 젬 구분(persistent 태그)도 함께 저장한다.

사용: .venv\\Scripts\\python.exe tools\\update_gem_ids.py "<POB 폴더>\\Data\\Gems.lua"
"""
import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "guides" / "gem_ids_pob.json"
_ENTRY = re.compile(r'\n\t\["[^"]+"\] = \{(.*?)\n\t\},', re.S)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    table: dict[str, dict] = {}
    for body in _ENTRY.findall(text):
        name = re.search(r'\n\t\tname = "([^"]+)"', body)
        game_id = re.search(r'\n\t\tgameId = "([^"]+)"', body)
        if not name or not game_id:
            continue
        key = game_id[1].rsplit("/", 1)[-1]
        table.setdefault(key, {"name": name[1], "spirit": "persistent = true" in body})
    OUT.write_text(json.dumps({"_comment": "Path of Building(PoE2) Data/Gems.lua 에서 생성 — tools/update_gem_ids.py",
                               "ids": dict(sorted(table.items()))}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(table)}개 → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
