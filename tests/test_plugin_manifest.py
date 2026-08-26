from pathlib import Path

from app.core.plugin import PluginManifest


def test_template_manifest_is_valid() -> None:
    path = Path(__file__).resolve().parents[1] / "plugins" / "template" / "plugin.json"
    manifest = PluginManifest.model_validate_json(path.read_text(encoding="utf-8"))
    assert manifest.name == "template"
    assert manifest.api_version == 1

