from __future__ import annotations

from app.services.preset_utils import split_message


def test_split_short_message() -> None:
    assert split_message("hello") == ["hello"]
    assert split_message("") == []


def test_split_long_message_at_newline() -> None:
    text = "\n".join("行" * 500 for _ in range(10))
    chunks = split_message(text, limit=1800)
    assert len(chunks) > 1
    assert all(len(chunk) <= 1800 for chunk in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")
    # 拼接回来应保留全部内容（去除切分处的空白）
    assert all(chunk for chunk in chunks)


def test_split_no_break_points() -> None:
    text = "字" * 5000
    chunks = split_message(text, limit=1800)
    assert len(chunks) == 3
    assert all(len(chunk) <= 1800 for chunk in chunks)
    assert "".join(chunks) == text
