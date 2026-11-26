"""Batched IMAP remote writeback execution helpers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import imaplib
import ssl
from typing import Any

from mail_core.mail.domain.failures import FailureDomain, StructuredFailure
from mail_core.providers.base import RemoteOperationResult
from mail_core.providers.connection_slots import is_capacity_error
from mail_core.providers.imap_wire import (
    _copyuid_remote_states,
    _extract_copyuid_texts,
    _get_server_uidvalidity,
    _parse_uids_flags_from_response,
    _quote_mailbox,
    imap_uid_for_command,
    parse_imap_remote_id,
)
from mail_core.providers.remote_writeback import (
    OP_MARK_READ,
    OP_MOVE,
    OP_SET_FLAG,
    OP_TRASH,
    compress_uids_chunked,
    normalize_op_type,
    require_remote_id,
)


@dataclass(frozen=True)
class _FlagOpSpec:
    state_key: str
    imap_flag: str
    label: str
    flag_index: int
    default_value: bool


_FLAG_OP_SPECS: dict[str, _FlagOpSpec] = {
    OP_MARK_READ: _FlagOpSpec(
        state_key="is_read",
        imap_flag=r"(\Seen)",
        label="Seen",
        flag_index=0,
        default_value=True,
    ),
    OP_SET_FLAG: _FlagOpSpec(
        state_key="is_flagged",
        imap_flag=r"(\Flagged)",
        label="Flagged",
        flag_index=1,
        default_value=True,
    ),
}


@dataclass(frozen=True)
class ValidatedImapOp:
    """Validated remote operation ready for per-folder batched IMAP execution."""

    op_id: Any
    op_type: str
    desired: dict[str, Any]
    numeric_uid: int
    folder: str
    uidvalidity: int | None
    dest_folder: str | None


def _resolve_dest_folder(op_type: str, desired: dict[str, Any]) -> str | None:
    if op_type == OP_MOVE:
        dest = str(desired.get("dest_folder_remote_id") or desired.get("to_folder") or "")
        if not dest:
            raise ValueError("missing dest_folder_remote_id")
    elif op_type == OP_TRASH:
        dest = str(desired.get("trash_folder_remote_id") or "Trash")
    else:
        return None
    _quote_mailbox(dest)
    return dest


def _resolve_source_folder(remote_id: str, desired: dict[str, Any]) -> tuple[str, int | None]:
    parsed = parse_imap_remote_id(remote_id)
    explicit_folder = desired.get("folder_remote_id")
    parsed_folder = parsed[1] if parsed else ""
    folder = str(explicit_folder or parsed_folder or "INBOX")
    if parsed is not None and explicit_folder and str(explicit_folder) != parsed[1]:
        raise ValueError(
            f"folder_remote_id {explicit_folder!r} does not match remote_id folder {parsed[1]!r}"
        )
    return folder, (parsed[0] if parsed is not None else None)


def _parse_numeric_uid(remote_id: str) -> int:
    uid_str = imap_uid_for_command(remote_id)
    try:
        return int(uid_str)
    except ValueError as exc:
        raise ValueError(f"invalid numeric UID {uid_str!r}") from exc


def _validate_single_op(item: Any) -> ValidatedImapOp | RemoteOperationResult:
    desired = dict(item.desired_state or {})
    op_type = normalize_op_type(item.op_type)
    try:
        remote_id = require_remote_id(desired)
        folder, uidvalidity = _resolve_source_folder(remote_id, desired)
        numeric_uid = _parse_numeric_uid(remote_id)
        _quote_mailbox(folder)
        dest_folder = _resolve_dest_folder(op_type, desired)
    except ValueError as exc:
        return RemoteOperationResult(success=False, error=str(exc))

    return ValidatedImapOp(
        op_id=item.op_id,
        op_type=op_type,
        desired=desired,
        numeric_uid=numeric_uid,
        folder=folder,
        uidvalidity=uidvalidity,
        dest_folder=dest_folder,
    )


def _validate_and_group_ops(
    operations: Sequence[Any],
    results: dict[Any, RemoteOperationResult],
) -> dict[str, list[ValidatedImapOp]]:
    folder_groups: dict[str, list[ValidatedImapOp]] = {}
    for item in operations:
        validated = _validate_single_op(item)
        if isinstance(validated, RemoteOperationResult):
            results[item.op_id] = validated
        else:
            folder_groups.setdefault(validated.folder, []).append(validated)
    return folder_groups


def _filter_uidvalidity(
    items: list[ValidatedImapOp],
    folder: str,
    srv_uv: int | None,
    results: dict[Any, RemoteOperationResult],
) -> list[ValidatedImapOp]:
    valid_items: list[ValidatedImapOp] = []
    for item in items:
        expected_uv = item.uidvalidity
        mismatch = (
            expected_uv is not None
            and expected_uv > 0
            and srv_uv is not None
            and srv_uv != expected_uv
        )
        if mismatch:
            results[item.op_id] = RemoteOperationResult(
                success=False,
                error=f"UIDVALIDITY mismatch for {folder}: expected {expected_uv}, got {srv_uv}",
            )
        else:
            valid_items.append(item)
    return valid_items


def _subgroup_target_value(item: ValidatedImapOp) -> Any:
    spec = _FLAG_OP_SPECS.get(item.op_type)
    if spec is not None:
        return bool(item.desired.get(spec.state_key, spec.default_value))
    return item.dest_folder


def _record_uid_map_result(
    uid_to_items: dict[int, list[ValidatedImapOp]],
    uids: Sequence[int],
    result: RemoteOperationResult,
    results: dict[Any, RemoteOperationResult],
) -> None:
    for uid in uids:
        for item in uid_to_items.get(uid, ()):
            results[item.op_id] = result


def _fetch_flags_fallback(
    client: Any,
    missing_uids: list[int],
    flags_by_uid: dict[int, tuple[bool | None, bool | None]],
) -> None:
    if not missing_uids:
        return
    for uid_spec, _ in compress_uids_chunked(missing_uids):
        f_typ, f_data = client.uid("FETCH", uid_spec, "(FLAGS UID)")
        if f_typ == "OK":
            flags_by_uid.update(_parse_uids_flags_from_response(f_data))


def _verify_flag_result(
    uid: int,
    folder: str,
    spec: _FlagOpSpec,
    want_value: bool,
    flags_by_uid: dict[int, tuple[bool | None, bool | None]],
) -> RemoteOperationResult:
    if uid not in flags_by_uid:
        return RemoteOperationResult(success=False, error=f"UID {uid} not found in {folder}")
    if flags_by_uid[uid][spec.flag_index] is want_value:
        return RemoteOperationResult(success=True, remote_state={spec.state_key: want_value})
    return RemoteOperationResult(
        success=False,
        error=f"STORE {spec.label} for UID {uid} could not be verified via FETCH",
    )


def _apply_flag_chunk(
    client: Any,
    folder: str,
    spec: _FlagOpSpec,
    want_value: bool,
    chunk_str: str,
    chunk_uids: list[int],
    uid_to_items: dict[int, list[ValidatedImapOp]],
    results: dict[Any, RemoteOperationResult],
) -> None:
    flag_op = "+FLAGS" if want_value else "-FLAGS"
    typ, data = client.uid("STORE", chunk_str, flag_op, spec.imap_flag)
    if typ != "OK":
        _record_uid_map_result(
            uid_to_items,
            chunk_uids,
            RemoteOperationResult(success=False, error=f"STORE {spec.label} failed"),
            results,
        )
        return

    flags_by_uid = _parse_uids_flags_from_response(data)
    missing_uids = [u for u in chunk_uids if u not in flags_by_uid]
    _fetch_flags_fallback(client, missing_uids, flags_by_uid)
    for uid in chunk_uids:
        res = _verify_flag_result(uid, folder, spec, want_value, flags_by_uid)
        _record_uid_map_result(uid_to_items, [uid], res, results)


def _execute_move_subchunks(
    client: Any,
    dest_target: str,
    move_uids: list[int],
    uid_to_items: dict[int, list[ValidatedImapOp]],
    results: dict[Any, RemoteOperationResult],
) -> None:
    for move_spec, move_chunk_uids in compress_uids_chunked(move_uids):
        typ, response_data = client.uid("MOVE", move_spec, _quote_mailbox(dest_target))
        if typ != "OK":
            _record_uid_map_result(
                uid_to_items,
                move_chunk_uids,
                RemoteOperationResult(success=False, error="IMAP server does not support atomic MOVE/delete"),
                results,
            )
            continue
        copyuid_texts = _extract_copyuid_texts(client, response_data)
        states_by_uid = _copyuid_remote_states(copyuid_texts, move_chunk_uids, dest_target)
        for uid in move_chunk_uids:
            res = RemoteOperationResult(success=True, remote_state=states_by_uid[uid])
            _record_uid_map_result(uid_to_items, [uid], res, results)


def _apply_move_chunk(
    client: Any,
    folder: str,
    dest_target: str,
    chunk_str: str,
    chunk_uids: list[int],
    uid_to_items: dict[int, list[ValidatedImapOp]],
    results: dict[Any, RemoteOperationResult],
) -> None:
    # A368: MOVE has no per-UID response, so verify existence first; a
    # silent-OK server must not let an already-expunged UID report success.
    f_typ, f_data = client.uid("FETCH", chunk_str, "(FLAGS UID)")
    existing_uids = set(_parse_uids_flags_from_response(f_data)) if f_typ == "OK" else set()
    for uid in chunk_uids:
        if uid not in existing_uids:
            res = RemoteOperationResult(success=False, error=f"UID {uid} not found in {folder}")
            _record_uid_map_result(uid_to_items, [uid], res, results)
    move_uids = [u for u in chunk_uids if u in existing_uids]
    _execute_move_subchunks(client, dest_target, move_uids, uid_to_items, results)


def _execute_subgroup(
    client: Any,
    folder: str,
    op_type: str,
    target_val: Any,
    sub_items: list[ValidatedImapOp],
    results: dict[Any, RemoteOperationResult],
) -> None:
    uid_to_items: dict[int, list[ValidatedImapOp]] = {}
    for item in sub_items:
        uid_to_items.setdefault(item.numeric_uid, []).append(item)
    flag_spec = _FLAG_OP_SPECS.get(op_type)

    for chunk_str, chunk_uids in compress_uids_chunked(sorted(uid_to_items)):
        if flag_spec is not None:
            _apply_flag_chunk(
                client, folder, flag_spec, bool(target_val), chunk_str, chunk_uids, uid_to_items, results
            )
        elif op_type in (OP_MOVE, OP_TRASH):
            _apply_move_chunk(client, folder, str(target_val), chunk_str, chunk_uids, uid_to_items, results)


def _handle_folder_exception(
    exc: Exception,
    items: list[ValidatedImapOp],
    results: dict[Any, RemoteOperationResult],
) -> None:
    if is_capacity_error(exc):
        raise exc
    failure = StructuredFailure.from_exception(exc)
    has_succeeded = any(res.success for res in results.values())
    is_transport_or_imap = (
        isinstance(exc, (TimeoutError, ConnectionError, OSError, ssl.SSLError, imaplib.IMAP4.error))
        or failure.domain is not FailureDomain.UNKNOWN
    )
    if not has_succeeded and is_transport_or_imap:
        raise exc
    err_text = failure.format()
    for item in items:
        if item.op_id not in results:
            results[item.op_id] = RemoteOperationResult(success=False, error=err_text, failure=failure)


def _execute_folder_ops(
    client: Any,
    folder: str,
    items: list[ValidatedImapOp],
    results: dict[Any, RemoteOperationResult],
) -> None:
    try:
        typ, _ = client.select(_quote_mailbox(folder))
        if typ != "OK":
            for item in items:
                results[item.op_id] = RemoteOperationResult(success=False, error=f"select {folder} failed")
            return

        srv_uv = _get_server_uidvalidity(client, folder)
        valid_items = _filter_uidvalidity(items, folder, srv_uv, results)
        if not valid_items:
            return

        subgroups: dict[tuple[str, Any], list[ValidatedImapOp]] = {}
        for item in valid_items:
            subgroups.setdefault((item.op_type, _subgroup_target_value(item)), []).append(item)

        for (op_type, target_val), sub_items in subgroups.items():
            _execute_subgroup(client, folder, op_type, target_val, sub_items, results)
    except Exception as exc:
        _handle_folder_exception(exc, items, results)


def execute_imap_writeback_batch(
    operations: Sequence[Any],
    *,
    connect_fn: Callable[[], tuple[Any, Any]],
    close_fn: Callable[[Any, Any], None],
) -> Sequence[tuple[Any, RemoteOperationResult]]:
    """Validate and execute a batch of IMAP remote operations across folders."""
    if not operations:
        return []

    results: dict[Any, RemoteOperationResult] = {}
    folder_groups = _validate_and_group_ops(operations, results)
    if not folder_groups:
        fallback = RemoteOperationResult(success=False, error="unknown error")
        return [(op.op_id, results.get(op.op_id, fallback)) for op in operations]

    client, permit = connect_fn()
    try:
        for folder, items in folder_groups.items():
            _execute_folder_ops(client, folder, items, results)
    finally:
        close_fn(client, permit)

    unhandled = RemoteOperationResult(success=False, error="operation unhandled")
    return [(op.op_id, results.get(op.op_id, unhandled)) for op in operations]
