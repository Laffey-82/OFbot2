from __future__ import annotations

from pathlib import Path

from scripts.repo_setup import LABELS, TOPICS, plan_requests


def test_plan_requests_contains_metadata_and_labels() -> None:
    requests = plan_requests()
    methods = [item["method"] for item in requests]
    assert "PATCH" in methods  # 仓库元数据
    assert "PUT" in methods  # topics
    assert methods.count("POST") == len(LABELS)  # 每个缺失标签一条 POST
    topics_payload = next(
        item["payload"] for item in requests if item["method"] == "PUT"
    )
    assert topics_payload["names"] == TOPICS


def test_labels_cover_issue_label_doc() -> None:
    """标签清单覆盖 ISSUE_LABELS.md 中记录的标签名。"""
    text = (
        Path(__file__).resolve().parents[1] / "docs" / "ISSUE_LABELS.md"
    ).read_text(encoding="utf-8")
    for name in LABELS:
        assert name in text, f"ISSUE_LABELS.md 缺少标签 {name}"
