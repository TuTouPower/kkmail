from fastapi.testclient import TestClient

from mail_core.api.app import app


def test_health():
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["service"] == "mail-core"


def test_ready():
    assert TestClient(app).get("/ready").json()["status"] == "ready"
