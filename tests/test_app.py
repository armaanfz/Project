"""Minimal Flask route tests."""
import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_home_returns_200(client):
    r = client.get("/")
    assert r.status_code == 200


def test_samples_returns_200(client):
    r = client.get("/samples")
    assert r.status_code == 200


def test_home_tab_content_returns_200(client):
    r = client.get("/home-tab-content")
    assert r.status_code == 200
