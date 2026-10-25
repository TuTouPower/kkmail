from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from mail_core.mail.domain.enums import JobType
from mail_core.mail.storage.models import WorkerJob
from mail_core.worker.handlers import handle_job


@pytest.mark.parametrize(
    ("job_type", "payload"),
    [
        (JobType.SYNC_FOLDER_METADATA.value, {}),
        (JobType.RECONCILE_FOLDER.value, {"folder_id": "not-a-uuid"}),
        (JobType.SYNC_FOLDER_DELTA.value, {"folder_id": str(uuid.uuid4()), "poll_round": "bad"}),
        (JobType.SYNC_FOLDER_METADATA.value, ["not", "an", "object"]),
    ],
)
def test_invalid_folder_sync_payload_fails_without_changing_account_status(job_type, payload):
    job = WorkerJob(
        account_id=uuid.uuid4(),
        job_type=job_type,
        status="claimed",
        payload=payload,
    )
    job.id = uuid.uuid4()
    job.locked_by = "worker-invalid-payload"
    session = MagicMock()

    with (
        patch("mail_core.worker.handlers.fail_job") as fail,
        patch("mail_core.worker.handlers.update_account_sync_status") as update_status,
    ):
        result = handle_job(session, job, worker_id="worker-invalid-payload")

    assert result is False
    fail.assert_called_once()
    assert "invalid_payload:" in str(fail.call_args.args[2])
    assert fail.call_args.kwargs["max_attempts"] == 1
    update_status.assert_not_called()
    session.get.assert_not_called()
