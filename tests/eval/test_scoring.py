"""Scoring runs against the ground truth, and summarising a sweep."""

import json
from pathlib import Path

import pytest

from investigator.domain.causes import CauseCategory, Outcome, RootCause
from investigator.domain.report import Report
from investigator.eval.ground_truth import load_ground_truth
from investigator.eval.runner import RECORD_FILE, REPORT_FILE, TRACE_FILE, RunRecord
from investigator.eval.scoring import RunScore, score_run
from investigator.eval.summary import load_results, render_summary
from investigator.world.dataset import Dataset

from .test_runner import SOLO_D2, sweep

DECOY = RootCause(
    service="notification-service", category=CauseCategory.CODE_REGRESSION, trigger="chg:2291"
)


@pytest.fixture
async def scripted_sweep(tmp_path: Path, dataset: Dataset) -> Path:
    await sweep(dataset, tmp_path).run([SOLO_D2])
    return tmp_path


def rescore(dataset: Dataset, run: Path, report: Report | None = None) -> RunScore:
    record = RunRecord.model_validate_json((run / RECORD_FILE).read_text())
    trace = [json.loads(line) for line in (run / TRACE_FILE).read_text().splitlines()]
    report = report or Report.model_validate_json((run / REPORT_FILE).read_text())
    logs = {line.id: line for line in dataset.telemetry("D2").logs}
    return score_run(record, report, trace, load_ground_truth(dataset, "D2"), logs)


def test_a_grounded_right_answer_scores_as_correct(scripted_sweep: Path, dataset: Dataset) -> None:
    score = rescore(dataset, scripted_sweep / SOLO_D2.name)

    assert (score.correct, score.top1, score.top3) == (True, True, True)
    assert (score.wrong_conclusion, score.confidently_wrong, score.abstained) == (False,) * 3
    assert score.citations == score.valid_citations == 3
    assert score.rejected_citations == 1
    assert (score.key_evidence, score.key_evidence_cited) == (4, 2)
    assert score.red_herrings_cited == 0
    assert score.tool_calls == 2


def test_wrong_answers_unsupported_text_citations_and_abstentions_are_counted(
    scripted_sweep: Path, dataset: Dataset
) -> None:
    run = scripted_sweep / SOLO_D2.name
    report = Report.model_validate_json((run / REPORT_FILE).read_text())
    decoy_first = (
        report.hypotheses[1].model_copy(update={"rank": 1, "confidence_band": "high"}),
        report.hypotheses[0].model_copy(update={"rank": 2}),
    )
    wrong = report.model_copy(
        update={
            "root_cause": DECOY,
            "hypotheses": decoy_first,
            "summary": "chg:2291 did it, as chg:9999 shows",
        }
    )
    abstained = report.model_copy(update={"outcome": Outcome.INCONCLUSIVE, "root_cause": None})

    confident = rescore(dataset, run, wrong)
    unsure = rescore(dataset, run, abstained)

    assert (confident.correct, confident.top1, confident.top3) == (False, False, True)
    assert (confident.wrong_conclusion, confident.confidently_wrong) == (True, True)
    assert confident.red_herrings_cited == 1
    assert (confident.citations, confident.valid_citations) == (4, 3)
    assert (unsure.correct, unsure.abstained, unsure.top1) == (False, True, True)


async def test_the_summary_is_regenerated_exactly_from_the_runs(
    scripted_sweep: Path, dataset: Dataset
) -> None:
    first = render_summary(load_results(scripted_sweep, dataset), "Results")
    second = render_summary(load_results(scripted_sweep, dataset), "Results")

    assert first == second
    assert "| Correct outcome | 1/1 (100%) |" in first
    assert "| D2 | 1/1: concluded (right) |" in first
