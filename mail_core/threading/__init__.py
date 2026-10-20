from mail_core.threading.rules import (
    ThreadAssignment,
    assign_thread_for_message,
    extract_message_ids,
    normalize_message_id,
    normalize_subject,
)

__all__ = [
    "ThreadAssignment",
    "assign_thread_for_message",
    "extract_message_ids",
    "normalize_message_id",
    "normalize_subject",
]
