"""Business functions kept separate from the MCP transport for easy testing."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

CustomerId = Annotated[str, StringConstraints(pattern=r"^CUST-[A-Z0-9]{5}$")]


class GetCustomerRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    customer_id: CustomerId


class TriggerRefundInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    customer_id: CustomerId
    amount: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10)]


CUSTOMERS = {
    "CUST-A1B2C": {
        "customer_id": "CUST-A1B2C",
        "name": "Ada Lovelace",
        "status": "active",
    }
}


def get_customer_record(data: GetCustomerRecordInput) -> dict[str, object]:
    return CUSTOMERS.get(
        data.customer_id,
        {"customer_id": data.customer_id, "status": "not_found"},
    )


def trigger_refund(data: TriggerRefundInput) -> dict[str, object]:
    # A real implementation would call a payments service with an idempotency key.
    return {
        "status": "accepted",
        "customer_id": data.customer_id,
        "amount": data.amount,
        "reason": data.reason,
    }

