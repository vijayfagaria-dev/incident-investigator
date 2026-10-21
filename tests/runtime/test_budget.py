import pytest

from investigator.llm.messages import Usage
from investigator.runtime.budget import Budget, BudgetExceeded, BudgetLimits

LIMITS = BudgetLimits(
    model_calls=5,
    tool_calls=3,
    tokens=1000,
    wall_clock_s=60,
    reserve_model_calls=2,
    reserve_tokens=200,
)


def spend(budget: Budget, calls: int, tokens_each: int = 10) -> None:
    for _ in range(calls):
        budget.record_model_call(Usage(prompt_tokens=tokens_each))


def test_exploration_stops_at_the_limit_minus_the_reserve() -> None:
    budget = Budget(LIMITS)
    spend(budget, 2)
    assert budget.exploration_stop_reason() is None

    spend(budget, 1)
    assert budget.exploration_stop_reason() == "model call budget reached"
    with pytest.raises(BudgetExceeded):
        budget.require_model_call()
    budget.require_model_call(concluding=True)


def test_the_reserve_itself_can_be_spent_only_once() -> None:
    budget = Budget(LIMITS)
    spend(budget, 5)
    with pytest.raises(BudgetExceeded, match="including the reserve"):
        budget.require_model_call(concluding=True)


def test_tokens_tool_calls_and_time_each_end_exploration() -> None:
    by_tokens = Budget(LIMITS)
    spend(by_tokens, 1, tokens_each=850)
    by_tools = Budget(LIMITS)
    taken = [by_tools.take_tool_call() for _ in range(4)]
    now = [0.0]
    by_time = Budget(LIMITS, clock=lambda: now[0])
    now[0] = 61.0

    assert by_tokens.exploration_stop_reason() == "token budget reached"
    assert taken == [True, True, True, False]
    assert by_tools.exploration_stop_reason() == "tool call budget reached"
    assert by_time.exploration_stop_reason() == "time budget reached"
