from app.core.observability import MetricsRegistry, get_system_metrics


def test_metrics_registry() -> None:
    metrics = MetricsRegistry()
    metrics.inc("commands_total")
    metrics.inc("commands_total")
    metrics.set_gauge("cpu", 1.5)
    snapshot = metrics.snapshot()
    assert snapshot["counters"]["commands_total"] == 2.0
    assert snapshot["gauges"]["cpu"] == 1.5
    assert "commands_total 2.0" in metrics.prometheus_text()
    assert "cpu 1.5" in metrics.prometheus_text()


def test_system_metrics_shape() -> None:
    metrics = get_system_metrics()
    assert "cpu_percent" in metrics
    assert "memory_percent" in metrics
    assert "active_tasks" in metrics

