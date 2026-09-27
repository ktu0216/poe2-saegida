from poe2_overlay.logtail import iter_lines


def test_iter_lines_keeps_first_line_at_boundary(tmp_path):
    p = tmp_path / "log.txt"
    p.write_bytes(b"one\ntwo\nthree\n")
    assert list(iter_lines(p, 4, p.stat().st_size)) == ["two", "three"]   # 줄 경계
    assert list(iter_lines(p, 5, p.stat().st_size)) == ["three"]          # 줄 중간
    assert list(iter_lines(p, 0, p.stat().st_size)) == ["one", "two", "three"]
