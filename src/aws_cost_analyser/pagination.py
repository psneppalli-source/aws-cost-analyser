"""Shared pagination bound: every tool that lists/paginates AWS results
must go through this cap so a single MCP tool call can never trigger an
unbounded (or attacker-inflated) sequence of AWS API calls.

Pagination tokens are always handled internally -- the server calls AWS
repeatedly using AWS's own NextPageToken, capped by settings.max_result_pages.
A client-supplied "max_results" further trims the returned payload. Tokens
are never accepted as MCP tool input.
"""

from __future__ import annotations

from aws_cost_analyser.config import get_settings


def max_pages() -> int:
    return get_settings().max_result_pages
