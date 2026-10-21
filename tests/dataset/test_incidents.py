"""Checks every incident in the dataset is coherent, realistic and does not leak its answer."""

import ast
from datetime import timedelta
from pathlib import Path
from statistics import mean

import pytest

import investigator
from investigator.domain.causes import Outcome
from investigator.eval.ground_truth import GroundTruth, Split, Tag, load_ground_truth
from investigator.world.dataset import INCIDENT_FILE, Dataset
from investigator.world.store import TelemetryStore

from ..conftest import DATASETS

INCIDENT_IDS = Dataset(DATASETS).incident_ids()
SOURCE = Path(investigator.__file__).parent

# Update deliberately when the generator or an incident changes; a surprise mismatch
# means telemetry changed under existing results.
FINGERPRINTS = {
    "D1": "f24a467bbb4021fbc4b6b97771ae202ff31711868752470687a627e0a8f49741",
    "D2": "7fb21f3c3523d551a8cb06425c172e3fd635720423b07185c6c0d42ee2faa373",
    "D3": "bbd63c75693b0002f085d5ca2aa0dab8a104c36fb5c1a73f480c32f8ff610b9c",
    "D4": "8d1878b8846716eeae9e21cca58b9be296c5831fb357353bad3382f5c37c0a01",
    "T01": "1c86e2f7f8540fda6f3e24564190823de8869215c0dd2d9d4a8a6d772423c3eb",
    "T02": "e9b7d9910354c6990b2b8d71db345c95e927577af9dec456f4a08662076ebbfc",
    "T03": "d307f182156c1eeeb0e890ecde77e4de77f3b6390ba727d02f3d9f8de437a382",
    "T04": "ee77ac6934bf8c6bc36c1e002886a5bcce36fcc49d4d20ab0f6bd5a524da1a4b",
    "T05": "3fd0aebf145ba6f7264c014444541597e388a229c08560274fcbf07afa0c0eb9",
    "T06": "da8fcc182807cf4b6502e734abaef4e089778fa81ea0e2e53fc3f3f0b17cc783",
    "T07": "1174be45e132e805223fb8abc0bd55c215c832e4bd6aaac2da186ba31a9ff9e5",
    "T08": "c465880c4b69e36c9b43daaf8d5ddf0085ff9ef5c21488f0594b533dbacdd448",
    "T09": "794329aba40c00da7e706dc37e93a085e3b0afff8d613a149ab223a50b33a641",
    "T10": "e7a5cb5dede9f13b4938e5d749ec993291c20379a5b9ccb1ab01dfde25ba5fc0",
}


@pytest.fixture(scope="module")
def worlds(dataset: Dataset) -> dict[str, TelemetryStore]:
    return {incident_id: dataset.telemetry(incident_id) for incident_id in INCIDENT_IDS}


def test_dataset_has_incidents() -> None:
    assert INCIDENT_IDS


@pytest.mark.parametrize("incident_id", INCIDENT_IDS)
def test_rendering_matches_the_recorded_fingerprint(
    incident_id: str, worlds: dict[str, TelemetryStore]
) -> None:
    assert worlds[incident_id].fingerprint() == FINGERPRINTS[incident_id]


@pytest.mark.parametrize("incident_id", INCIDENT_IDS)
def test_key_evidence_and_red_herrings_exist_in_the_telemetry(
    incident_id: str, dataset: Dataset, worlds: dict[str, TelemetryStore]
) -> None:
    truth = load_ground_truth(dataset, incident_id)
    world = worlds[incident_id]
    change_ids = {change.id for change in world.changes}
    assert set(truth.key_evidence.changes) <= change_ids
    assert set(truth.key_evidence.metrics) <= set(world.metrics)
    assert {ref for ref in truth.red_herrings if ref.startswith("chg:")} <= change_ids
    for pattern in truth.key_evidence.log_patterns:
        assert any(
            record.service == pattern.service and pattern.contains in record.message
            for record in world.logs
        ), pattern


@pytest.mark.parametrize("incident_id", INCIDENT_IDS)
def test_key_metrics_move_after_the_trigger(
    incident_id: str, dataset: Dataset, worlds: dict[str, TelemetryStore]
) -> None:
    truth = load_ground_truth(dataset, incident_id)
    if truth.root_cause is None or truth.root_cause.trigger is None:
        pytest.skip("no triggering change")
    world = worlds[incident_id]
    trigger = next(change for change in world.changes if change.id == truth.root_cause.trigger)
    for ref in truth.key_evidence.metrics:
        series = world.metrics[ref]
        points = list(zip(series.timestamps(), series.values, strict=True))
        before = mean(
            v for ts, v in points if trigger.ts - timedelta(minutes=30) <= ts < trigger.ts
        )
        after = mean(
            v
            for ts, v in points
            if trigger.ts + timedelta(minutes=5) <= ts < trigger.ts + timedelta(minutes=35)
        )
        assert abs(after - before) / before > 0.25, (
            f"{ref} barely moves: {before:.3g} -> {after:.3g}"
        )


@pytest.mark.parametrize("incident_id", INCIDENT_IDS)
def test_incident_report_does_not_reveal_the_answer(incident_id: str, dataset: Dataset) -> None:
    truth: GroundTruth = load_ground_truth(dataset, incident_id)
    report = (dataset.incident_dir(incident_id) / INCIDENT_FILE).read_text()
    if truth.root_cause is not None:
        assert truth.root_cause.category.value not in report
        if truth.root_cause.trigger is not None:
            assert truth.root_cause.trigger not in report


@pytest.mark.parametrize("incident_id", INCIDENT_IDS)
def test_no_log_line_names_the_answer(incident_id: str, dataset: Dataset) -> None:
    truth = load_ground_truth(dataset, incident_id)
    if truth.root_cause is None:
        pytest.skip("no root cause to give away")
    giveaways = {truth.root_cause.category.value}
    if truth.root_cause.trigger is not None:
        giveaways.add(truth.root_cause.trigger)
    for effect in dataset.scenario(incident_id).log_effects():
        assert not any(word in effect.template for word in giveaways), effect.template


def test_the_test_split_has_ten_incidents_covering_every_tag(dataset: Dataset) -> None:
    truths = [load_ground_truth(dataset, i) for i in INCIDENT_IDS]
    held_out = [truth for truth in truths if truth.split is Split.TEST]

    assert len(held_out) >= 10
    assert {tag for truth in held_out for tag in truth.tags} == set(Tag)
    assert any(truth.expected_outcome is Outcome.INCONCLUSIVE for truth in held_out)


def test_prompts_do_not_mention_any_incident_or_its_answer(dataset: Dataset) -> None:
    prompts = " ".join(path.read_text() for path in SOURCE.rglob("prompts/*.md")).lower()
    for incident_id in INCIDENT_IDS:
        truth = load_ground_truth(dataset, incident_id)
        leaks = {
            incident_id,
            *truth.key_evidence.changes,
            *truth.red_herrings,
            *(pattern.contains for pattern in truth.key_evidence.log_patterns),
        }
        assert not [leak for leak in leaks if leak.lower() in prompts], incident_id


def test_history_ids_are_unique_and_match_file_names(dataset: Dataset) -> None:
    history = dataset.history()
    assert len({incident.id for incident in history}) == len(history)
    for path in (DATASETS / "history").glob("*.yaml"):
        assert any(incident.id.replace(":", "-") == path.stem for incident in history), path


def _string_constants(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _imported_modules(path: Path) -> set[str]:
    modules = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


@pytest.mark.parametrize(
    ("filename", "owner"),
    [("scenario.yaml", "world/dataset.py"), ("expected.yaml", "eval/ground_truth.py")],
)
def test_scenario_and_ground_truth_files_have_a_single_reader(filename: str, owner: str) -> None:
    readers = {
        path.relative_to(SOURCE).as_posix()
        for path in SOURCE.rglob("*.py")
        if filename in _string_constants(path)
    }
    assert readers == {owner}


def test_only_the_evaluator_cli_and_viewer_import_the_evaluator() -> None:
    importers = {
        path.relative_to(SOURCE).as_posix()
        for path in SOURCE.rglob("*.py")
        if any(
            m == "investigator.eval" or m.startswith("investigator.eval.")
            for m in _imported_modules(path)
        )
    }
    outside = {path for path in importers if not path.startswith(("eval/", "ui/"))}
    assert outside <= {"cli.py"}
