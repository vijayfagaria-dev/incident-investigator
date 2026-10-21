from pathlib import Path

import pytest

from investigator.world.dataset import Dataset

DATASETS = Path(__file__).resolve().parents[1] / "datasets"


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    return Dataset(DATASETS)
