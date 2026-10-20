from fastapi.testclient import TestClient

from mail_core.api.app import _code_schema_head, app


def test_health_reports_schema_head():
    res = TestClient(app).get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["service"] == "mail-core"
    assert body["schema_head"] == _code_schema_head()
    assert body["schema_head"]


def test_ready_without_db_returns_503(monkeypatch):
    """When DB is unreachable, /ready must be 503 (not a false ready)."""
    from sqlalchemy.exc import OperationalError

    class Boom:
        def connect(self):
            raise OperationalError("SELECT 1", {}, Exception("db down"))

    monkeypatch.setattr("mail_core.db.session.get_engine", lambda url=None: Boom())
    res = TestClient(app).get("/ready")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "not_ready"
    assert body["reason"] == "database: OperationalError"
    assert "db down" not in res.text  # no driver detail leak


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


def _engine_with_revision(rev):
    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, *_a, **_k):
            return _Result(rev)

    class Engine:
        def connect(self):
            return Conn()

    return Engine()


class _Listener:
    def __init__(self, alive, listen_ready=None):
        self.is_alive = alive
        # /ready requires a successful LISTEN, not merely a reconnecting thread.
        self.listen_ready = alive if listen_ready is None else listen_ready


def test_ready_ok_when_db_at_head_and_listener_alive(monkeypatch):
    monkeypatch.setattr("mail_core.db.session.get_engine", lambda url=None: _engine_with_revision(_code_schema_head()))
    monkeypatch.setattr("mail_core.realtime.listener.get_outbox_listener", lambda: _Listener(True))
    res = TestClient(app).get("/ready")
    assert res.status_code == 200
    assert res.json()["status"] == "ready"
    assert res.json()["schema_revision"] == _code_schema_head()


def test_ready_503_when_schema_behind(monkeypatch):
    monkeypatch.setattr("mail_core.db.session.get_engine", lambda url=None: _engine_with_revision("old"))
    monkeypatch.setattr("mail_core.realtime.listener.get_outbox_listener", lambda: _Listener(True))
    res = TestClient(app).get("/ready")
    assert res.status_code == 503
    assert res.json()["reason"] == "schema_out_of_date"


def test_ready_503_when_listener_down(monkeypatch):
    monkeypatch.setattr("mail_core.db.session.get_engine", lambda url=None: _engine_with_revision(_code_schema_head()))
    monkeypatch.setattr("mail_core.realtime.listener.get_outbox_listener", lambda: _Listener(False))
    res = TestClient(app).get("/ready")
    assert res.status_code == 503
    assert res.json()["reason"] == "outbox_listener"


def test_ready_503_when_listener_alive_but_not_listening(monkeypatch):
    """Reconnect loop running without a successful LISTEN must not report ready."""
    monkeypatch.setattr("mail_core.db.session.get_engine", lambda url=None: _engine_with_revision(_code_schema_head()))
    monkeypatch.setattr(
        "mail_core.realtime.listener.get_outbox_listener",
        lambda: _Listener(True, listen_ready=False),
    )
    res = TestClient(app).get("/ready")
    assert res.status_code == 503
    assert res.json()["reason"] == "outbox_listener"

