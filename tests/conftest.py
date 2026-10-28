"""Test-wide safety: no network access and no real credentials, ever."""

import pytest
import requests

import data.finviz.client as finviz_client


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise RuntimeError("network access is disabled in tests")
    monkeypatch.setattr(requests.sessions.Session, "request", refuse)


@pytest.fixture(autouse=True)
def _no_real_finviz_key(monkeypatch, tmp_path):
    # setenv first so delenv registers an undo even if the variable was absent.
    monkeypatch.setenv("FINVIZ_API_KEY", "placeholder")
    monkeypatch.delenv("FINVIZ_API_KEY")
    # Never let a test read the developer's real project .env.
    monkeypatch.setattr(finviz_client, "DEFAULT_ENV_FILE", tmp_path / "no-such.env")
