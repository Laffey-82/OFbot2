from __future__ import annotations

import pytest

from app.services.alerts import (
    BUILTIN_ALERT_TEMPLATES,
    AlertService,
    install_alert_template,
    install_default_alerts,
)


def test_builtin_alert_templates_fields() -> None:
    assert len(BUILTIN_ALERT_TEMPLATES) >= 5
    for template in BUILTIN_ALERT_TEMPLATES:
        assert template["name"]
        assert template["event"]


def test_install_alert_template_and_dedupe() -> None:
    service = AlertService()
    assert install_alert_template(service, "连接断开") is True
    assert install_alert_template(service, "连接断开") is False
    assert any(rule.name == "连接断开" for rule in service.rules)
    with pytest.raises(KeyError):
        install_alert_template(service, "不存在")


def test_install_default_alerts() -> None:
    service = AlertService()
    assert install_default_alerts(service) == len(BUILTIN_ALERT_TEMPLATES)
    assert install_default_alerts(service) == 0
    assert len(service.rules) == len(BUILTIN_ALERT_TEMPLATES)
