"""A18: capacity deferral must survive non-numeric retry_after values.

Both capacity paths in worker/handlers.py converted the delay with a
bare ``float(...)``: a handler result carrying ``retry_after="abc"``
(or NaN/inf) raised inside ``_evaluate_result``, and an exception
carrying ``retry_after_seconds="abc"`` raised inside the capacity
``except`` branch. The generic failure path then counted an attempt for
what is contractually a no-attempt deferral.
"""

from __future__ import annotations

import math
import uuid
from unittest.mock import MagicMock, patch

import pytest

from mail_core.mail.domain.enums import JobType
from mail_core.mail.storage.models import WorkerJob
from mail_core.providers.connection_slots import CAPACITY_RETRY_SECONDS, ProviderCapacityUnavailable
from mail_core.worker import handlers
from mail_core.worker.handlers import _coerce_retry_after, _evaluate_result


@pytest.mark.parametrize(
    "raw",
    ["abc", "", float("nan"), float("inf"), float("-inf"), -3, -0.5, None, object(), {"x": 1}, True],
)
def test_coerce_retry_after_falls_back_for_invalid_values(raw):
    assert _coerce_retry_after(raw) == CAPACITY_RETRY_SECONDS


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(12, 12.0), ("12.5", 12.5), (0, 0.0), (2.25, 2.25)],
)
def test_coerce_retry_after_accepts_finite_non_negative(raw, expected):
    assert _coerce_retry_after(raw) == expected
    assert math.isfinite(_coerce_retry_after(raw))


def test_evaluate_result_capacity_with_garbage_retry_after_reschedules_without_attempt():
    job = WorkerJob(job_type=JobType.REMOTE_OPERATION_PUSH.value, status="claimed", payload={})
    job.id = uuid.uuid4()
    session = MagicMock()
    with (
        patch.object(handlers, "reschedule_job") as reschedule,
        patch.object(handlers, "fail_job") as fail,
        patch.object(handlers, "complete_job") as complete,
    ):
        outcome = _evaluate_result(
            session, job, {"status": "capacity_unavailable", "retry_after": "not-a-number"},
            worker_id="w-a18",
        )
    assert outcome is False
    reschedule.assert_called_once()
    assert reschedule.call_args.kwargs["delay_seconds"] == CAPACITY_RETRY_SECONDS
    fail.assert_not_called()
    complete.assert_not_called()


def test_handle_job_capacity_exception_with_garbage_retry_after_reschedules():
    job = WorkerJob(job_type=JobType.GC_BLOBS.value, status="claimed", payload={})
    job.id = uuid.uuid4()
    job.locked_by = "w-a18"
    session = MagicMock()
    exc = ProviderCapacityUnavailable("saturated")
    exc.retry_after_seconds = "abc"  # type: ignore[attr-defined]
    with (
        patch("mail_core.blobs.gc.run_gc_blobs", side_effect=exc),
        patch.object(handlers, "reschedule_job") as reschedule,
        patch.object(handlers, "fail_job") as fail,
    ):
        outcome = handlers.handle_job(session, job, worker_id="w-a18")
    assert outcome is False
    reschedule.assert_called_once()
    assert reschedule.call_args.kwargs["delay_seconds"] == CAPACITY_RETRY_SECONDS
    fail.assert_not_called()
