"""grep 工具的匹配、过滤与安全行为。"""

import pytest


@pytest.fixture
def tree(by_name):
    by_name["write_file"].invoke(
        {"file_path": "app.py", "content": "def main():\n    pass\nDEF setup():\n"}
    )
    by_name["write_file"].invoke(
        {"file_path": "docs/note.md", "content": "def not python\n"}
    )
    return by_name


def test_matches_use_relative_posix_paths_with_line_numbers(tree):
    output = tree["grep"].invoke({"pattern": "def "})
    lines = output.splitlines()
    assert lines[0] == "app.py:1:def main():"
    assert "docs/note.md:1:def not python" in lines


def test_glob_filters_searched_files(tree):
    output = tree["grep"].invoke({"pattern": "def ", "glob": "**/*.md"})
    assert output.splitlines() == ["docs/note.md:1:def not python"]


def test_ignore_case_toggle(tree):
    sensitive = tree["grep"].invoke({"pattern": "DEF"})
    assert "app.py:3" in sensitive
    assert "ignore_case" not in sensitive
    insensitive = tree["grep"].invoke({"pattern": "DEF", "ignore_case": True})
    joined = insensitive.splitlines()
    assert "app.py:1:def main():" in joined
    assert "app.py:3:DEF setup():" in joined


def test_head_limit_truncates_matches(tree):
    output = tree["grep"].invoke({"pattern": "def ", "head_limit": 1})
    assert len(output.splitlines()) == 1


def test_no_match_returns_note(tree):
    output = tree["grep"].invoke({"pattern": "zzz-nowhere"})
    assert "No matches" in output


def test_invalid_regex_raises(tree):
    with pytest.raises(ValueError, match="Invalid regex"):
        tree["grep"].invoke({"pattern": "([unclosed"})


def test_search_path_escape_raises(tree):
    with pytest.raises(ValueError, match="escapes the workspace"):
        tree["grep"].invoke({"pattern": "def", "path": ".."})


def test_binary_and_oversized_files_are_skipped(tree, workspace):
    (workspace / "blob.bin").write_bytes(b"\x00\xff\xfe\x00def ")
    big = workspace / "big.txt"
    big.write_text("def " * 3_000_000, encoding="utf-8")
    output = tree["grep"].invoke({"pattern": "def ", "head_limit": 50})
    assert "blob.bin" not in output
    assert "big.txt" not in output
