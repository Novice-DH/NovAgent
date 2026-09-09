"""read_file / write_file / edit_file 的语义与路径安全。"""

import pytest


def test_write_creates_parent_directories(by_name, workspace):
    message = by_name["write_file"].invoke(
        {"file_path": "deep/nested/file.txt", "content": "hello"}
    )
    assert (workspace / "deep" / "nested" / "file.txt").read_text(
        encoding="utf-8"
    ) == "hello"
    assert "deep/nested/file.txt" in message.replace("\\", "/")


def test_write_overwrites_existing_file(by_name, workspace):
    by_name["write_file"].invoke({"file_path": "a.txt", "content": "first"})
    by_name["write_file"].invoke({"file_path": "a.txt", "content": "second"})
    assert (workspace / "a.txt").read_text(encoding="utf-8") == "second"


def test_read_returns_content_and_honors_offset_limit(by_name):
    by_name["write_file"].invoke(
        {"file_path": "lines.txt", "content": "l1\nl2\nl3\nl4"}
    )
    assert by_name["read_file"].invoke({"file_path": "lines.txt"}) == "l1\nl2\nl3\nl4"
    assert by_name["read_file"].invoke(
        {"file_path": "lines.txt", "offset": 2, "limit": 2}
    ) == "l2\nl3"


def test_read_missing_file_and_directory(by_name, workspace):
    with pytest.raises(FileNotFoundError):
        by_name["read_file"].invoke({"file_path": "missing.txt"})
    with pytest.raises(IsADirectoryError):
        by_name["read_file"].invoke({"file_path": "."})


def test_read_and_write_reject_escape(by_name, tmp_path):
    with pytest.raises(ValueError, match="escapes the workspace"):
        by_name["read_file"].invoke({"file_path": "../secret.txt"})
    with pytest.raises(ValueError, match="escapes the workspace"):
        by_name["write_file"].invoke(
            {"file_path": str(tmp_path / "evil.txt"), "content": "x"}
        )
    assert not (tmp_path / "evil.txt").exists()


def test_edit_replaces_unique_occurrence(by_name, workspace):
    by_name["write_file"].invoke({"file_path": "code.py", "content": "a = 1\nb = 2"})
    message = by_name["edit_file"].invoke(
        {"file_path": "code.py", "old_text": "a = 1", "new_text": "a = 42"}
    )
    assert (workspace / "code.py").read_text(encoding="utf-8") == "a = 42\nb = 2"
    assert "Replaced 1 occurrence" in message


def test_edit_without_match_keeps_file_unchanged(by_name, workspace):
    by_name["write_file"].invoke({"file_path": "f.txt", "content": "original"})
    with pytest.raises(ValueError, match="not found"):
        by_name["edit_file"].invoke(
            {"file_path": "f.txt", "old_text": "absent", "new_text": "x"}
        )
    assert (workspace / "f.txt").read_text(encoding="utf-8") == "original"


def test_edit_with_multiple_matches_keeps_file_unchanged(by_name, workspace):
    by_name["write_file"].invoke({"file_path": "f.txt", "content": "dup\ndup\ndup"})
    with pytest.raises(ValueError, match="3 times"):
        by_name["edit_file"].invoke(
            {"file_path": "f.txt", "old_text": "dup", "new_text": "x"}
        )
    assert (workspace / "f.txt").read_text(encoding="utf-8") == "dup\ndup\ndup"


def test_edit_rejects_empty_old_text(by_name):
    with pytest.raises(ValueError, match="old_text must not be empty"):
        by_name["edit_file"].invoke(
            {"file_path": "f.txt", "old_text": "", "new_text": "x"}
        )


def test_edit_rejects_escape(by_name, tmp_path):
    with pytest.raises(ValueError, match="escapes the workspace"):
        by_name["edit_file"].invoke(
            {"file_path": "../f.txt", "old_text": "a", "new_text": "b"}
        )
