import pytest

from investigator.domain.artifacts import artifact_kind, dependency_id, metric_id


def test_builders_produce_ids_of_the_right_kind() -> None:
    assert artifact_kind(metric_id("payments-service", "error_rate")) == "metric"
    assert artifact_kind(dependency_id("edge-gateway", "auth-service")) == "dep"
    assert artifact_kind("chg:2290") == "chg"


@pytest.mark.parametrize("bad", ["2290", "change:2290", "chg:", "chg: 2290"])
def test_artifact_kind_rejects_malformed_ids(bad: str) -> None:
    with pytest.raises(ValueError, match="not an artifact id"):
        artifact_kind(bad)
