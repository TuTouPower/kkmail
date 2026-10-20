from fastapi.testclient import TestClient

from mail_core.api.app import app


def test_health():
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["service"] == "mail-core"


def test_ready_without_db_returns_503(monkeypatch):
    """When DB is unreachable, /ready must be 503 (not a false ready)."""
    from sqlalchemy.exc import OperationalError

    class Boom:
        def connect(self):
            raise OperationalError("SELECT 1", {}, Exception("db down"))

    monkeypatch.setattr("mail_core.db.session.get_engine", lambda url=None: Boom())
    res = TestClient(app).get("/ready")
    assert res.status_code == 503
    assert res.json()["status"] == "not_ready"


def test_ready_ok_when_db_connects(monkeypatch):
    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, *_a, **_k):
            return None

    class OkEngine:
        def connect(self):
            return Conn()

    monkeypatch.setattr("mail_core.db.session.get_engine", lambda url=None: OkEngine())
    res = TestClient(app).get("/ready")
    assert res.status_code == 200
    assert res.json()["status"] == "ready"
