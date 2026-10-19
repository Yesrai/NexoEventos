"""Pruebas locales de las funciones puras de scripts/cloud/v2-measure.py."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("m", Path(__file__).resolve().parents[1] / "cloud" / "v2-measure.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

LOG = "\n".join([
    '{"line":"2026-10-20T15:00:01+00:00 method=GET path=/api/events status=200 bytes=10 request_time=0.1 request_id=a"}',
    '{"line":"2026-10-20T15:00:05+00:00 method=POST path=/api/auth/login status=500 bytes=10 request_time=0.1 request_id=b"}',
    '{"line":"2026-10-20T15:00:06+00:00 method=GET path=/assets/x.js status=200 bytes=10 request_time=0.1 request_id=c"}',
    '{"line":"2026-10-20T15:10:00+00:00 method=GET path=/api/events status=200 bytes=10 request_time=0.1 request_id=d"}',
])


class Measure(unittest.TestCase):
    def test_count_requests_filters_window_and_prefix(self) -> None:
        self.assertEqual(m.count_requests(LOG, "2026-10-20T15:00:00Z", "2026-10-20T15:05:00Z"), {"requests": 2, "errors_5xx": 1})

    def test_health_transitions_and_failover_summary(self) -> None:
        samples = [(100 + 2 * i, {"i-a": "healthy", "i-b": "healthy" if i < 12 or i >= 30 else ("unhealthy" if i >= 17 else "healthy")}) for i in range(40)]
        tr = m.health_transitions(samples)
        self.assertEqual([x["to"] for x in tr if x["instance"] == "i-b"], ["healthy", "unhealthy", "healthy"])
        summary = m.failover_summary(tr, stopped_at_s=24.0, restored_at_s=48.0)
        self.assertEqual(summary, {"detected_after_s": 10.0, "recovered_after_s": 12.0})


if __name__ == "__main__":
    unittest.main()
