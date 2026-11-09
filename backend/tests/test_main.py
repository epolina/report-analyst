import pytest
from fastapi.testclient import TestClient

MISSING = "00000000-0000-0000-0000-000000000000"


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", f"/reports/{MISSING}", None),
        ("GET", f"/reports/{MISSING}/pages/1", None),
        ("POST", f"/reports/{MISSING}/retry", None),
        ("GET", f"/conversations/{MISSING}", None),
        ("POST", "/chat", {"question": "x", "conversation_id": MISSING}),
    ],
)
def test_unknown_id_is_404(client: TestClient, method: str, path: str, body: object) -> None:
    assert client.request(method, path, json=body).status_code == 404
