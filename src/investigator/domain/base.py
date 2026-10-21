from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    """Immutable record that rejects unknown fields, so typos in datasets fail loudly."""

    model_config = ConfigDict(frozen=True, extra="forbid")
