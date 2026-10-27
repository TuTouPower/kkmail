"""A253: GC / backup job payloads must go through _validate_job_payload.

Previously only folder-sync payloads were validated, so a GC job with
``cool_off_hours="abc"`` raised ValueError in the handler's bare
``float(...)`` (a counted failure instead of an invalid-payload
rejection), a negative value pushed the GC cool-off into the future
(making nearly every blob eligible), and a backup job's ``output_dir``
reached ``run_backup`` with no type check at all.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from mail_core.mail.domain.enums import JobType
from mail_core.mail.storage.models import WorkerJob
from mail_core.worker.handlers import _validate_job_payload, handle_job


def _job(job_type: str, payload):
    job = WorkerJob(job_type=job_type, status="claimed", payload=payload)
    job.id = uuid.uuid4()
    return job


@pytest.mark.parametrize(
    "payload",
    [
        {"cool_off_hours": "abc"},
        {"cool_off_hours": float("nan")},
        {"cool_off_hours": float("inf")},
        {"cool_off_hours": -1},
        {"cool_off_hours": True},
        {"cool_off_hours": [24]},
    ],
)
def test_gc_cool_off_hours_rejected(payload):
    _payload, error = _validate_job_payload(_job(JobType.GC_BLOBS.value, payload))
    assert error is not None and "cool_off_hours" in error


@pytest.mark.parametrize(
    "payload",
    [{}, {"cool_off_hours": None}, {"cool_off_hours": 0}, {"cool_off_hours": 24}, {"cool_off_hours": "12.5"}],
)
def test_gc_cool_off_hours_accepted(payload):
    _payload, error = _validate_job_payload(_job(JobType.GC_BLOBS.value, payload))
    assert error is None


@pytest.mark.parametrize("payload", [{"output_dir": 123}, {"output_dir": ["x"]}, {"output_dir": {"x": 1}}])
def test_backup_output_dir_rejected(payload):
    _payload, error = _validate_job_payload(_job(JobType.BACKUP_RUN.value, payload))
    assert error is not None and "output_dir" in error


@pytest.mark.parametrize("payload", [{}, {"output_dir": None}, {"output_dir": "/tmp/backups"}])
def test_backup_output_dir_accepted(payload):
    _payload, error = _validate_job_payload(_job(JobType.BACKUP_RUN.value, payload))
    assert error is None


def test_gc_invalid_payload_fails_job_without_running_gc():
    job = _job(JobType.GC_BLOBS.value, {"cool_off_hours": "-5"})
    job.locked_by = "w-a253"
    session = MagicMock()
    with (
        patch("mail_core.worker.handlers.fail_job") as fail,
        patch("mail_core.blobs.gc.run_gc_blobs") as run_gc,
    ):
        result = handle_job(session, job, worker_id="w-a253")
    assert result is False
    fail.assert_called_once()
    assert "invalid_payload:" in str(fail.call_args.args[2])
    assert fail.call_args.kwargs["max_attempts"] == 1
    run_gc.assert_not_called()
