import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


SERVICE_DIR = Path(__file__).parents[1] / "services" / "llm-interpret"
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, SERVICE_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


analysis = load_module("analysis")
llm_client = load_module("llm_client")
service_module = load_module("service")


def test_parse_duration_supports_custom_ranges():
    assert analysis.parse_duration("5m") == timedelta(minutes=5)
    assert analysis.parse_duration("10 minutes") == timedelta(minutes=10)
    assert analysis.parse_duration("30s") == timedelta(seconds=30)


def test_statistics_include_basic_metrics_and_correlation():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(4):
        timestamp = start + timedelta(seconds=index)
        rows.extend([(timestamp, 0, float(index + 1)), (timestamp, 1, float((index + 1) * 2))])

    stats = analysis.calculate_statistics(rows, high_threshold=3)

    assert stats["sample_count"] == 8
    assert stats["channels"]["0"]["min"] == 1.0
    assert stats["channels"]["0"]["max"] == 4.0
    assert stats["channels"]["0"]["high_count"] == 2
    assert stats["correlations"][0]["coefficient"] == 1.0


def test_custom_llm_client_sends_openai_compatible_payload():
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "Telemetry was stable."}}]}).encode()

    def opener(request, timeout):
        captured["body"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return Response()

    client = llm_client.CustomLLMClient(
        {"LLM_API_URL": "http://llm.local/v1/chat/completions", "LLM_MODEL": "test-model"},
        opener=opener,
    )

    assert client.summarize("summarize this") == "Telemetry was stable."
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["messages"][1]["content"] == "summarize this"


def test_service_analyzes_and_persists_one_window():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class Repository:
        def __init__(self):
            self.ensure_calls = 0
            self.saved = None

        def ensure_summary_table(self):
            self.ensure_calls += 1

        def read_rows(self, window_start, window_end):
            return [
                (start, 0, 1.0),
                (start + timedelta(seconds=1), 0, 2.0),
                (start, 1, 2.0),
                (start + timedelta(seconds=1), 1, 4.0),
            ], False

        def save_summary(self, *args, **kwargs):
            self.saved = (args, kwargs)
            return 42

    class Client:
        enabled = True

        def summarize(self, prompt):
            assert "correlations" in prompt
            return "The two channels increased together."

    config = dict(service_module.DEFAULT_CONFIG)
    config.update({"RUN_ON_STARTUP": False, "LLM_API_URL": "http://llm.local"})
    repository = Repository()
    service = service_module.LLMInterpretService(config, repository=repository, llm_client=Client())

    result = service.analyze_window(start, start + timedelta(seconds=2))

    assert result["summary_id"] == 42
    assert result["llm_used"] is True
    assert repository.ensure_calls == 1
    assert repository.saved[1]["llm_used"] is True
