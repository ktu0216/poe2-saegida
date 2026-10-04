def test_app_module_imports():
    # 빌드 전에 app.py 문법·import 오류를 잡는다 (PyInstaller 는 오류가 있어도 빈 exe 를 만든다)
    import poe2_overlay.app  # noqa: F401
