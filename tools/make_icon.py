"""앱 아이콘(오버레이 트레이 아이콘과 같은 그림)을 build/icon.ico 로 저장."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from poe2_overlay.ui import make_icon  # noqa: E402

app = QApplication([])
out = Path(__file__).resolve().parent.parent / "build" / "icon.ico"
out.parent.mkdir(exist_ok=True)
if not make_icon().pixmap(64, 64).save(str(out), "ICO"):
    sys.exit("icon save failed")
print(out)
