import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from investigator import __version__
from investigator.cli import _live_models, app
from investigator.llm.fallback import FallbackGateway
from investigator.llm.retry import RetryingGateway
from investigator.tracing import MemoryTracer

from .conftest import DATASETS

runner = CliRunner()


def test_version_flag_prints_package_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"investigator {__version__}"


def test_data_list_shows_each_incident() -> None:
    result = runner.invoke(app, ["data", "list", "--datasets", str(DATASETS)])

    assert result.exit_code == 0
    assert "D2    sev2  Checkout failures and payment timeouts" in result.stdout


def test_data_render_writes_readable_files(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["data", "render", "D2", "--datasets", str(DATASETS), "--out", str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    assert {p.name for p in tmp_path.iterdir()} == {
        "incident.json",
        "changes.json",
        "dependencies.json",
        "logs.jsonl",
        "metrics.csv",
    }
    first_log = json.loads((tmp_path / "logs.jsonl").read_text().splitlines()[0])
    assert "template" not in first_log
    assert json.loads((tmp_path / "incident.json").read_text())["id"] == "D2"


def test_data_render_rejects_unknown_incidents() -> None:
    result = runner.invoke(app, ["data", "render", "Z9", "--datasets", str(DATASETS)])

    assert result.exit_code != 0
    assert "unknown incident 'Z9'" in result.output


def test_tools_call_prints_a_structured_result() -> None:
    args = json.dumps({"start": "2026-10-20T10:00:00Z", "end": "2026-10-20T10:05:00Z"})
    result = runner.invoke(
        app,
        [
            "tools",
            "call",
            "get_change_history",
            "--incident",
            "D2",
            "--args",
            args,
            "--datasets",
            str(DATASETS),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["artifacts"] == ["chg:2290", "chg:2291"]


def test_the_main_model_gets_its_backup_and_a_local_one_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")

    assert isinstance(_live_models("nvidia")(MemoryTracer()), FallbackGateway)
    assert isinstance(_live_models("ollama")(MemoryTracer()), RetryingGateway)
