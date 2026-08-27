from __future__ import annotations

import time

from app.adapters.base import BotClient, ConnectionHealth


def _stub_adapter() -> object:
    class Stub:
        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send_group_message(self, group_id, message) -> bool:
            return True

        async def send_private_message(self, user_id, message) -> bool:
            return True

    return Stub()


def test_connection_health_scoring() -> None:
    client = BotClient()
    client.register("napcat", _stub_adapter())
    client.status["napcat"] = "connected"
    client.details["napcat"] = {"last_heartbeat": time.time()}
    client._bump("napcat", "received", 10)
    client._bump("napcat", "sent", 5)

    health = client.health()
    assert len(health) == 1
    item = health[0]
    assert isinstance(item, ConnectionHealth)
    assert item.connected is True
    assert item.score >= 85
    assert item.messages_received == 10
    assert item.messages_sent == 5


def test_connection_health_disconnected_low_score() -> None:
    client = BotClient()
    client.register("offline", _stub_adapter())
    client.status["offline"] = "disconnected"
    health = client.health()[0]
    assert health.connected is False
    assert health.score < 50


def test_connection_health_stale_heartbeat() -> None:
    client = BotClient()
    client.register("stale", _stub_adapter())
    client.status["stale"] = "connected"
    client.details["stale"] = {"last_heartbeat": time.time() - 1000}
    item = client.health(stale_seconds=300)[0]
    assert item.heartbeat_stale is True
