from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app.services.scaffold import ScaffoldService


def test_presets_are_discovered() -> None:
    examples_dir = Path(__file__).resolve().parents[1] / "examples" / "plugins"
    service = ScaffoldService(examples_dir, Path(tempfile.gettempdir()) / "plugins")
    templates = service.list_templates()
    assert len(templates) >= 24
    names = {template["name"] for template in templates}
    assert {"dice", "signin", "order", "stats"}.issubset(names)


def test_preset_install_renames_plugin() -> None:
    examples_dir = Path(__file__).resolve().parents[1] / "examples" / "plugins"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        plugins_dir = Path(tmp_dir) / "plugins"
        service = ScaffoldService(examples_dir, plugins_dir)
        target = service.create_from_template("dice", "mydice")
        manifest = json.loads(
            (target / "plugin.json").read_text(encoding="utf-8")
        )
        assert manifest["name"] == "mydice"
        assert (target / "__init__.py").exists()
