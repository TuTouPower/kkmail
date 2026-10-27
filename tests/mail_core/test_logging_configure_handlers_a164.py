"""A164: configure_logging must only remove (and close) its own handlers.

The old implementation removed *every* root handler — including handlers
installed by the host process / test harness — and never closed them,
leaking file descriptors and silently dropping foreign log sinks.
"""

from __future__ import annotations

import io
import logging

from mail_core.logging_config import configure_logging


class _RecordingHandler(logging.StreamHandler):
    def __init__(self):
        super().__init__(io.StringIO())
        self.closed = False

    def close(self):  # noqa: D102 - test double
        self.closed = True
        super().close()


def test_configure_logging_preserves_foreign_handlers_and_closes_own():
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    foreign = _RecordingHandler()
    root.addHandler(foreign)
    try:
        configure_logging(service_name="a164-first")
        own_first = [h for h in root.handlers if getattr(h, "_mail_core_installed", False)]
        assert foreign in root.handlers
        assert len(own_first) == 1

        configure_logging(service_name="a164-second")
        # Foreign handler survives both reconfigurations, unclosed.
        assert foreign in root.handlers
        assert foreign.closed is False
        # The handler installed by the first call was removed *and* closed.
        assert own_first[0] not in root.handlers
        assert own_first[0]._closed is True
        own_second = [h for h in root.handlers if getattr(h, "_mail_core_installed", False)]
        assert len(own_second) == 1
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            if handler not in original_handlers:
                handler.close()
        for handler in original_handlers:
            root.addHandler(handler)
        root.setLevel(original_level)
