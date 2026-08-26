from __future__ import annotations

from argparse import Namespace

from app.cli import _capabilities, _plugin_features, _scopes_list, _scopes_set
from app.core.capabilities import Capability, capability_registry


def test_capabilities_lists(capsys) -> None:
    capability_registry.register(Capability(name="records", description="records"))
    capability_registry.register(Capability(name="ai", description="ai"))
    _capabilities(Namespace())
    output = capsys.readouterr().out
    assert "records" in output
    assert "ai" in output


def test_plugin_features_lists_declarations(capsys) -> None:
    _plugin_features(Namespace(name="template"))
    output = capsys.readouterr().out
    assert "功能" in output
    assert "/ping" in output
    assert "daily" in output
    assert "GroupMessageReceived" in output


def test_plugin_features_missing_plugin(capsys) -> None:
    _plugin_features(Namespace(name="not_exist_plugin"))
    output = capsys.readouterr().out
    assert "插件不存在" in output


def test_scopes_list_and_set(tmp_path, monkeypatch, capsys) -> None:
    from app.core.config import load_settings, save_settings

    config_path = tmp_path / "config.yaml"
    load_settings(config_path)
    settings = load_settings(config_path)
    save_settings(settings)

    monkeypatch.setattr("app.cli._settings", lambda: load_settings(config_path))
    _scopes_set(
        Namespace(key="dice.roll", value="off", scope="group:123")
    )
    _scopes_list(Namespace())
    output = capsys.readouterr().out
    assert "group:123" in output
    assert "dice.roll=关" in output


def test_connections_list(capsys, tmp_path, monkeypatch) -> None:
    from app.cli import _connections_list
    from app.core.config import load_settings, save_settings

    config_path = tmp_path / "config.yaml"
    load_settings(config_path)
    save_settings(load_settings(config_path))
    monkeypatch.setattr("app.cli._settings", lambda: load_settings(config_path))
    _connections_list(Namespace())
    output = capsys.readouterr().out
    assert "napcat_main" in output
    assert "onebot" in output


def test_plugin_repo_list_offline(capsys) -> None:
    """本地插件仓库（plugin-repo/）离线可列出。"""
    from app.cli import _plugin_repo_list

    assert _plugin_repo_list(Namespace()) == 0
    output = capsys.readouterr().out
    assert "dice" in output
    assert "welcome" in output


def test_plugin_repo_install_unknown_fails(capsys) -> None:
    """安装不存在的插件应失败且不写入。"""
    from app.cli import _plugin_repo_install

    assert (
        _plugin_repo_install(
            Namespace(id="not_exist_plugin", name=None, force=False)
        )
        == 1
    )
    output = capsys.readouterr().out
    assert "安装失败" in output
