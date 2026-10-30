"""Hardening after a week of scheduled runs (2026-10-23..30): AMEX's login refused with a bare 403 and
was reported as an unexplained `failed` run after run; failure output lived only in Temporal history,
which the 24h retention deleted."""
import asyncio
import json
import logging

import pytest
from google.protobuf.duration_pb2 import Duration
from temporalio.api.workflowservice.v1 import DescribeNamespaceResponse
from temporalio.exceptions import ApplicationError

import activities
import worker
from activities import merge_status
from finance import push


def entry(status, run_id, at="2026-10-30T06:20:00+03:00"):
    return {"status": status, "message": "x", "updated_at": at, "run_id": run_id}


# --- AMEX: a refused login call is its own outcome -------------------------------------------

AMEX_BLOCKED = ("LOGIN FAILED: BOT_BLOCKED (ValidateIdDataNoReg HTTP 403 from AkamaiGHost: Access Denied)\n"
                "----------------------------------------")


def test_amex_bot_block_is_a_known_login_problem_not_an_unexplained_failure():
    assert activities.looks_expired(AMEX_BLOCKED)


def test_amex_unknown_login_outcome_stays_a_plain_failure():
    # What the scheduled runs of 10-27..10-30 printed before the 403 was classified.
    tail = "LOGIN FAILED: UNKNOWN https://he.americanexpress.co.il/personalarea/login/ (page saved to x)"
    assert not activities.looks_expired(tail)


# --- failure streak --------------------------------------------------------------------------

def streak_after(*runs):
    doc = None
    for status, run_id in runs:
        doc = merge_status(doc, "amex", entry(status, run_id))
    return doc["sources"]["amex"]["failure_streak"]


def test_a_run_is_counted_once_however_often_it_republishes():
    # checking -> scraping -> failed -> (retry from the same run publishes failed again)
    assert streak_after(("scraping", "r1"), ("failed", "r1"), ("failed", "r1")) == 1


def test_consecutive_failed_runs_accumulate_across_failure_kinds():
    # AMEX 10-27 22:00 .. 10-30 06:20 plus a rejected dump and a lapsed login in between
    assert streak_after(("failed", "r1"), ("scraping", "r2"), ("rejected", "r2"),
                        ("scraping", "r3"), ("needs_login", "r3")) == 3


def test_done_resets_the_streak():
    assert streak_after(("failed", "r1"), ("failed", "r2"), ("done", "r3"), ("failed", "r4")) == 1


def test_in_flight_statuses_keep_the_count():
    assert streak_after(("failed", "r1"), ("failed", "r2"), ("scraping", "r3")) == 2


def test_streak_push_fires_at_three_then_every_sixth_run():
    due = [n for n in range(1, 14) if push.streak_push_due(n)]
    assert due == [3, 6, 12]


def test_streak_payload_names_the_source_and_replaces_the_previous_one():
    p = push.streak_payload("amex", "אמריקן אקספרס", 3, "LOGIN FAILED: BOT_BLOCKED (HTTP 403)\nmore")
    assert "3" in p["body"] and "BOT_BLOCKED" in p["body"] and "more" not in p["body"]
    assert p["tag"] == "sync-streak-amex"


def test_failure_streak_activity_reads_the_status_file(tmp_path, monkeypatch):
    target = tmp_path / "sync-status.json"
    target.write_text(json.dumps(merge_status(merge_status(None, "amex", entry("failed", "r1")),
                                              "amex", entry("failed", "r2"))))
    monkeypatch.setattr(activities, "STATUS_FILE", target)
    assert asyncio.run(activities.failure_streak("amex")) == 2
    assert asyncio.run(activities.failure_streak("cal")) == 0  # never seen
    target.unlink()
    assert asyncio.run(activities.failure_streak("amex")) == 0  # no file yet


# --- failure output reaches the worker log ---------------------------------------------------

def test_log_failure_writes_the_output_tail(caplog):
    with caplog.at_level(logging.ERROR):
        activities.log_failure("scrape.mjs", "amex", 1, AMEX_BLOCKED)
    assert "scrape.mjs failed for amex (rc=1)" in caplog.text and "BOT_BLOCKED" in caplog.text


# --- namespace retention ---------------------------------------------------------------------

class FakeService:
    def __init__(self, days):
        self.days, self.updated = days, None

    async def describe_namespace(self, req):
        resp = DescribeNamespaceResponse()
        resp.config.workflow_execution_retention_ttl.CopyFrom(Duration(seconds=self.days * 86400))
        return resp

    async def update_namespace(self, req):
        self.updated = req.config.workflow_execution_retention_ttl.ToTimedelta().days


class FakeClient:
    namespace = "default"

    def __init__(self, days):
        self.workflow_service = FakeService(days)


def test_retention_raised_from_the_24h_default():
    client = FakeClient(1)
    note = asyncio.run(worker.ensure_retention(client, 30))
    assert client.workflow_service.updated == 30 and "1d -> 30d" in note


def test_retention_never_lowered():
    client = FakeClient(90)
    asyncio.run(worker.ensure_retention(client, 30))
    assert client.workflow_service.updated is None


def test_retention_failure_does_not_stop_the_worker():
    client = FakeClient(1)

    async def boom(req):
        raise RuntimeError("server down")
    client.workflow_service.describe_namespace = boom
    assert "not updated" in asyncio.run(worker.ensure_retention(client, 30))
