"""SQLAlchemy session event listeners for transactional NOTIFY wakes."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, SessionTransaction

from mail_core.mail.domain.enums import JobStatus
from mail_core.mail.storage.models import OutboxEvent, WorkerJob
from mail_core.realtime.notify import _warn_notify_failure, notify_jobs, notify_outbox

log = logging.getLogger("mail_core.db.events")


def _is_postgresql(session: Session) -> bool:
    try:
        bind = session.get_bind()
        return bind is not None and bind.dialect.name == "postgresql"
    except Exception:
        return False


def _get_wake_stack(session: Session) -> list[dict[str, bool]]:
    if "_wake_stack" not in session.info:
        session.info["_wake_stack"] = [{"outbox": False, "jobs": False}]
    return session.info["_wake_stack"]


def _is_runnable_now(dt: datetime | None, now_utc: datetime) -> bool:
    if dt is None:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt <= now_utc


def _on_tx_create(session: Session, transaction: SessionTransaction) -> None:
    if session.info.get("_in_commit_notify"):
        return
    if transaction.nested:
        _get_wake_stack(session).append({"outbox": False, "jobs": False})


def _on_soft_rollback(session: Session, transaction: SessionTransaction) -> None:
    if session.info.get("_in_commit_notify"):
        return
    rolled = session.info.setdefault("_rolled_back_txs", set())
    rolled.add(id(transaction))
    stack = session.info.get("_wake_stack")
    if stack and len(stack) > 1:
        stack.pop()


def _on_rollback(session: Session) -> None:
    if session.info.get("_in_commit_notify"):
        return
    if session.get_nested_transaction() is None:
        session.info.pop("_wake_stack", None)
        session.info.pop("_rolled_back_txs", None)
    else:
        stack = session.info.get("_wake_stack")
        if stack and len(stack) > 1:
            stack.pop()


def _on_tx_end(session: Session, transaction: SessionTransaction) -> None:
    if session.info.get("_in_commit_notify"):
        return
    rolled = session.info.get("_rolled_back_txs", set())
    is_rolled_back = id(transaction) in rolled
    if is_rolled_back:
        rolled.discard(id(transaction))
    stack = session.info.get("_wake_stack")
    if not stack:
        return
    if transaction.nested:
        if len(stack) > 1:
            child = stack.pop()
            if not is_rolled_back:
                stack[-1]["outbox"] |= child["outbox"]
                stack[-1]["jobs"] |= child["jobs"]
    elif transaction.parent is None:
        session.info.pop("_wake_stack", None)
        session.info.pop("_rolled_back_txs", None)


def _on_before_flush(session: Session, flush_context: Any, instances: Any) -> None:
    if session.info.get("_in_commit_notify"):
        return
    if not _is_postgresql(session):
        return

    now_utc = datetime.now(timezone.utc)
    stack = _get_wake_stack(session)
    cur = stack[-1]

    for obj in session.new:
        if isinstance(obj, OutboxEvent):
            cur["outbox"] = True
        elif isinstance(obj, WorkerJob):
            if obj.status == JobStatus.PENDING.value and _is_runnable_now(obj.run_after, now_utc):
                cur["jobs"] = True

    for obj in session.dirty:
        if isinstance(obj, WorkerJob):
            if obj.status == JobStatus.PENDING.value:
                insp = inspect(obj)
                hist_ra = insp.attrs.run_after.history
                if hist_ra.has_changes() and _is_runnable_now(obj.run_after, now_utc):
                    cur["jobs"] = True
                hist_st = insp.attrs.status.history
                if hist_st.has_changes() and _is_runnable_now(obj.run_after, now_utc):
                    cur["jobs"] = True


def _on_before_commit(session: Session) -> None:
    if session.info.get("_in_commit_notify"):
        return
    if not _is_postgresql(session):
        return

    # Flush pending changes so _on_before_flush runs for all new/dirty objects
    session.flush()

    stack = session.info.get("_wake_stack")
    if not stack:
        return
    flags = stack[0]
    wake_outbox = flags.get("outbox", False)
    wake_jobs = flags.get("jobs", False)
    if not wake_outbox and not wake_jobs:
        return

    session.info["_in_commit_notify"] = True
    try:
        with session.begin_nested():
            if wake_outbox:
                notify_outbox(session)
            if wake_jobs:
                notify_jobs(session)
    except Exception as exc:
        _warn_notify_failure(exc)
    finally:
        session.info["_in_commit_notify"] = False


_installed = False


def install_session_wake_hooks(session_cls_or_factory: Any = Session) -> None:
    global _installed
    if _installed:
        return
    event.listen(session_cls_or_factory, "after_transaction_create", _on_tx_create)
    event.listen(session_cls_or_factory, "after_soft_rollback", _on_soft_rollback)
    event.listen(session_cls_or_factory, "after_rollback", _on_rollback)
    event.listen(session_cls_or_factory, "after_transaction_end", _on_tx_end)
    event.listen(session_cls_or_factory, "before_flush", _on_before_flush)
    event.listen(session_cls_or_factory, "before_commit", _on_before_commit)
    _installed = True
