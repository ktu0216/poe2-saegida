"""PyInstaller 진입점 (패키지 상대 import 를 쓰기 위해 모듈 밖에서 실행)."""
import sys

from poe2_overlay.app import main

sys.exit(main())
