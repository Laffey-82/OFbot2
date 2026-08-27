import re
from pathlib import Path

from app.core.i18n import SUPPORTED_LANGUAGES, TRANSLATIONS, t


def test_translation_lookup_and_fallback() -> None:
    assert t("nav.dashboard", "zh-CN") == "仪表盘"
    assert t("nav.dashboard", "en") == "Dashboard"
    # 缺失语言回退中文，缺失键回退键名
    assert t("nav.dashboard", "fr") == "仪表盘"
    assert t("not.exists.key", "en") == "not.exists.key"


def test_supported_languages_have_zh_fallback() -> None:
    for language in SUPPORTED_LANGUAGES:
        assert language in TRANSLATIONS
    assert "en" in SUPPORTED_LANGUAGES


def test_all_template_i18n_keys_exist() -> None:
    """全部模板中使用的 t_('key') 必须存在于 zh-CN 翻译表。"""
    templates_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "templates"
    used: set[str] = set()
    pattern = re.compile(r"t_\('([a-z0-9_.]+)'\)")
    for path in templates_dir.glob("*.html"):
        used.update(pattern.findall(path.read_text(encoding="utf-8")))
    assert used, "未扫描到任何 t_ 键"
    missing = sorted(key for key in used if key not in TRANSLATIONS["zh-CN"])
    assert not missing, f"模板使用了未定义的 i18n 键：{missing}"


def test_every_page_uses_i18n_title() -> None:
    """除 base/docs_view 外，所有模板标题应使用 t_。"""
    templates_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "templates"
    hardcoded: list[str] = []
    for path in templates_dir.glob("*.html"):
        if path.stem in {"base", "docs_view"}:
            continue
        text = path.read_text(encoding="utf-8")
        m = re.search(r"block title\s*\}(.*?)\{\% endblock", text)
        if m and "t_(" not in m.group(1):
            hardcoded.append(path.stem)
    assert not hardcoded, f"以下模板标题未接入 t_：{hardcoded}"
