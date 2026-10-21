from pydantic import Field

from investigator.domain.base import DomainModel
from investigator.runtime.budget import BudgetLimits


class InvestigationConfig(DomainModel):
    max_rounds: int = Field(default=2, ge=1)
    concurrency: int = Field(default=3, ge=1)
    max_lead_tasks: int = Field(default=1, ge=0)
    """Follow-ups started from specialists' leads within a round."""
    max_followup_tasks: int = Field(default=2, ge=1)
    """Follow-ups started from evidence requests between rounds."""
    specialist_steps: int = Field(default=3, ge=1)
    reasoning_steps: int = Field(default=2, ge=0)
    solo_steps: int = Field(default=12, ge=1)
    """Tool-calling steps for the single-agent baseline, which gathers everything itself."""
    task_timeout_s: float = Field(default=600.0, gt=0)
    task_attempts: int = Field(default=2, ge=1)
    min_confidence: float = Field(default=0.5, ge=0, le=1)
    """Below this, the top hypothesis cannot make the outcome conclusive."""
    min_margin: float = Field(default=0.15, ge=0, le=1)
    """The lead the top hypothesis needs over the runner-up."""
    budget: BudgetLimits = BudgetLimits()
