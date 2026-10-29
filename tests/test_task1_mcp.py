from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from assessment.task1_mcp.service import (
    GetCustomerRecordInput,
    TriggerRefundInput,
    get_customer_record,
    trigger_refund,
)


def test_customer_id_is_strictly_validated() -> None:
    assert get_customer_record(GetCustomerRecordInput(customer_id="CUST-A1B2C"))["status"] == "active"
    for invalid in ("cust-A1B2C", "CUST-1234", "CUST-123456", 12345):
        with pytest.raises(ValidationError):
            GetCustomerRecordInput(customer_id=invalid)


def test_refund_validation_and_edge_cases() -> None:
    valid = TriggerRefundInput(
        customer_id="CUST-Z9Y8X",
        amount=0.01,
        reason="Duplicate transaction",
    )
    assert trigger_refund(valid)["status"] == "accepted"

    bad_values = (
        {"amount": 0.0, "reason": "long enough"},
        {"amount": -1.0, "reason": "long enough"},
        {"amount": math.inf, "reason": "long enough"},
        {"amount": 1.0, "reason": "short"},
        {"amount": 1.0, "reason": "          "},
    )
    for values in bad_values:
        with pytest.raises(ValidationError):
            TriggerRefundInput(customer_id="CUST-Z9Y8X", **values)


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        GetCustomerRecordInput(customer_id="CUST-A1B2C", unexpected=True)

