"""The Streamlit page, driven headlessly over a scripted sweep."""

from pathlib import Path

import pytest

from investigator.world.dataset import Dataset

from ..conftest import DATASETS
from ..eval.test_runner import SOLO_D2, sweep

testing = pytest.importorskip("streamlit.testing.v1")
PAGE = Path(__file__).parents[2] / "src" / "investigator" / "ui" / "app.py"


async def test_the_page_shows_a_run_and_replays_it(
    dataset: Dataset, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await sweep(dataset, tmp_path).run([SOLO_D2])
    monkeypatch.setenv("INVESTIGATOR_RESULTS", str(tmp_path))
    monkeypatch.setenv("INVESTIGATOR_DATASETS", str(DATASETS))

    page = testing.AppTest.from_file(str(PAGE), default_timeout=60).run()
    assert not page.exception
    assert any("Checkout failures" in m.value for m in page.markdown)

    page.button[0].click().run()
    assert not page.exception

    page.button[1].click().run()
    assert not page.exception
    assert any("exactly the recorded report" in s.value for s in page.success)
