from app.operational_metrics import _label, operational_metric_lines


def test_operational_metrics_fail_closed_without_database():
    assert operational_metric_lines(None)[-1] == "elexion_pipeline_telemetry_up 0"


def test_prometheus_labels_are_escaped():
    assert _label('adapter"\\\n') == 'adapter\\"\\\\\\n'
