"""Section 17 & 31 (test_excessive_pagination_rejected,
test_excessive_request_limits): no single MCP tool call may trigger an
unbounded (or attacker-inflated) sequence of AWS API calls, and
oversized result/page requests must be rejected at validation time before
any AWS call is made."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from aws_cost_analyser.config import get_settings
from aws_cost_analyser.pagination import max_pages
from aws_cost_analyser.tools.cost_and_usage import get_cost_and_usage
from aws_cost_analyser.validation import CostAndUsageRequest

TODAY = date.today()
LAST_MONTH = TODAY - timedelta(days=30)


def test_max_results_above_hard_cap_rejected_without_any_aws_call():
    with pytest.raises(ValidationError):
        CostAndUsageRequest(start_date=LAST_MONTH, end_date=TODAY, max_results=1_000_001)


def test_max_results_above_configured_cap_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAX_RESULTS_PER_PAGE", "10")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError):
            CostAndUsageRequest(start_date=LAST_MONTH, end_date=TODAY, max_results=50)
    finally:
        get_settings.cache_clear()


def test_pagination_never_exceeds_configured_max_pages(monkeypatch: pytest.MonkeyPatch, ce_stub):
    """Even if AWS kept returning NextPageToken forever, the server must
    stop after settings.max_result_pages calls -- proving a malicious or
    buggy upstream response can't drive unbounded AWS spend/latency."""
    monkeypatch.setenv("MAX_RESULT_PAGES", "3")
    get_settings.cache_clear()

    client, stubber = ce_stub
    page = {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": str(LAST_MONTH), "End": str(TODAY)},
                "Total": {"UnblendedCost": {"Amount": "1.00", "Unit": "USD"}},
                "Groups": [],
                "Estimated": False,
            }
        ],
        "GroupDefinitions": [],
        "NextPageToken": "always-more",  # AWS (or a compromised endpoint) never stops paginating
    }
    for _ in range(3):
        stubber.add_response("get_cost_and_usage", page)
    monkeypatch.setattr(
        "aws_cost_analyser.tools.cost_and_usage.cost_explorer_client", lambda: client
    )

    request = CostAndUsageRequest(start_date=LAST_MONTH, end_date=TODAY, max_results=100)
    result = get_cost_and_usage(request)

    assert max_pages() == 3
    assert len(result["results_by_time"]) == 3  # exactly 3 pages fetched, not unbounded
    assert result["truncated"] is True
    stubber.assert_no_pending_responses()
    get_settings.cache_clear()


def test_time_range_dos_via_huge_span_rejected():
    with pytest.raises(ValidationError):
        CostAndUsageRequest(
            start_date=date(1970, 1, 1),
            end_date=TODAY,
        )
