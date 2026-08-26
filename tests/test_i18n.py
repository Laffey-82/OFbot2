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
