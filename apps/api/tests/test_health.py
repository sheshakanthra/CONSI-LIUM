"""Health-check test.

WHY this exists: CLAUDE.md's definition of "done" requires at least one test
per phase. For the scaffold phase the meaningful contract is "the app boots and
the health endpoint answers", so we assert exactly that. We do NOT assert the
`database` field is "ok" — that would require a live Postgres and turn a unit
test into an integration test; the DB path is exercised by `docker-compose up`.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200

    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "consilium-api"
    # `database` will be "ok" if Postgres is reachable, else "error: ...".
    # Either way the key must be present — the endpoint never omits it.
    assert "database" in body
