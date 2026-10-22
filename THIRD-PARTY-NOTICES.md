# Third-party notices / 서드파티 고지

POE2 새기다 (Saegida) 자체는 [MIT](LICENSE) 라이선스입니다.
설치 파일과 휴대용 zip(PyInstaller로 만든 실행 파일)에는 아래 구성 요소가 함께 들어 있고, 각자의 라이선스를 따릅니다.

POE2 Saegida itself is licensed under [MIT](LICENSE).
The installer and portable zip (a PyInstaller build) bundle the components below, each under its own license.

## 함께 배포하는 구성 요소 / Bundled components

| 구성 요소 / Component | 라이선스 / License | 소스·전문 / Source & license text |
|---|---|---|
| Qt for Python (PySide6, Shiboken6) | LGPL-3.0 | https://code.qt.io/cgit/pyside/pyside-setup.git · https://www.gnu.org/licenses/lgpl-3.0.html |
| Qt 6 (PySide6에 포함된 Qt 라이브러리 / Qt libraries shipped with PySide6) | LGPL-3.0 | https://code.qt.io · https://doc.qt.io/qt-6/licensing.html |
| Python 런타임 / Python runtime | PSF License (포함 모듈은 Python 라이선스 문서 참고 / bundled modules: see Python's license page) | https://docs.python.org/3/license.html |
| PyInstaller 부트로더 / PyInstaller bootloader | GPL-2.0-or-later with the bootloader exception | https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt |

### LGPL 안내 / LGPL note

Qt와 PySide6 라이브러리는 실행 파일에 합쳐 넣지 않고, 설치 폴더의 `_internal` 안에 별도 파일(DLL·`.pyd`)로 들어 있습니다.
같은 버전의 PySide6를 직접 빌드하거나 고친 라이브러리로 이 파일들을 바꿔 쓸 수 있습니다.
새기다의 전체 소스는 https://github.com/ktu0216/poe2-saegida 에 있고, `build.bat`으로 같은 방식의 실행 파일을 다시 만들 수 있습니다.

The Qt and PySide6 libraries are not linked into the executable; they ship as separate files (DLLs and `.pyd`) under `_internal` in the install folder.
You may replace them with your own build or modified version of the same PySide6 release.
Saegida's full source is at https://github.com/ktu0216/poe2-saegida, and `build.bat` rebuilds the same kind of executable.

## 참고한 자료 / Data sources

- 지역 팁 일부 / Some zone tips: [POE2Radar](https://github.com/Sikaka/POE2Radar) `zone_notes.json` (MIT, originally Path of Levelling 2) — 요약·번역 / summarised and translated
- 지역·보상 영어 이름 / English zone and reward names: [poe2db.tw](https://poe2db.tw)
- 영어 클라이언트 로그 형식 / English client log format: [bear421/poe-map-log-viewer](https://github.com/bear421/poe-map-log-viewer) (MIT) 문서 / docs
- 젬 내부 ID → 이름 / Gem internal IDs → names: [Path of Building (PoE2)](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2) `Data/Gems.lua`
- 막간 지역 팁 일부 / Some interlude tips: [poe2way 액트 가이드](https://www.poe2way.com/act-guide/ko)

Path of Exile은 Grinding Gear Games의 상표입니다. 새기다는 Grinding Gear Games, Kakao Games와 관련 없는 개인 제작 도구입니다.
Path of Exile is a trademark of Grinding Gear Games. Saegida is a personal tool, not affiliated with Grinding Gear Games or Kakao Games.
