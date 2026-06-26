from typing import Any, Literal
from pydantic import BaseModel, Field

Severity = Literal['error', 'warning', 'info']


class ValidationIssue(BaseModel):
    row_number: int | None = None
    column_name: str | None = None
    severity: Severity
    code: str
    message: str
    value: str | None = None
    suggestion: str | None = None
    source: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ValidationSummary(BaseModel):
    job_id: str
    status: str
    total_rows: int
    error_count: int
    warning_count: int
