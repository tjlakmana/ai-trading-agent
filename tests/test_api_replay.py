"""Phase 3: deterministic replay endpoint (read-only)."""

import pytest

from tests.api_fixtures import WRITE_HEADERS, build_history, make_client


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "memory.db"
    ids = build_history(path)
    return make_client(path), ids, path


def replay(client, run_id, overrides=None):
    return client.post(f"/api/runs/{run_id}/replay", json={"overrides": overrides or {}}, headers=WRITE_HEADERS)


def test_replay_with_original_config_changes_nothing(setup):
    client, ids, _ = setup
    body = replay(client, ids["broad"]).json()
    assert body["changed"] == [] and body["applied_overrides"] == {}
    assert body["counts"] == body["original_counts"]
    assert body["in_play_config"]["min_cumulative_volume"] == 500_000  # the run's own config
    assert "never written" in body["note"]


def test_replay_with_looser_pct_change(setup):
    client, ids, _ = setup
    body = replay(client, ids["broad"][:8], {"min_pct_change": 0.02}).json()
    changed = {c["ticker"]: c for c in body["changed"]}
    assert changed["EFGH"]["original_status"] == "NEAR_MISS" and changed["EFGH"]["status"] == "QUALIFIED"
    assert changed["IJKL"]["status"] == "NEAR_MISS" and changed["IJKL"]["failed_hard_checks"] == ["max_float_shares"]
    assert body["counts"] == {"rows": 4, "qualified": 2, "near_miss": 1, "filtered_out": 0, "rejected": 1}
    assert body["applied_overrides"] == {"min_pct_change": 0.02}


def test_null_disables_a_threshold(setup):
    client, ids, _ = setup
    body = replay(client, ids["broad"], {"max_float_shares": None, "preferred_max_float_shares": None}).json()
    assert body["in_play_config"]["max_float_shares"] is None
    # IJKL failed % change AND float (FILTERED_OUT); with the float check disabled only % change fails.
    assert [(c["ticker"], c["original_status"], c["status"], c["failed_hard_checks"]) for c in body["changed"]] == [
        ("IJKL", "FILTERED_OUT", "NEAR_MISS", ["min_pct_change"])]


def test_level_override(setup):
    client, ids, _ = setup
    body = replay(client, ids["broad"], {"catalyst_level": "hard"}).json()
    abcd = next(c for c in body["changed"] if c["ticker"] == "ABCD")
    assert abcd["original_status"] == "QUALIFIED" and abcd["status"] == "NEAR_MISS"
    assert abcd["failed_hard_checks"] == ["catalyst"]
    assert body["applied_overrides"] == {"catalyst_level": "HARD"}


def test_int_fields_accept_whole_numbers(setup):
    client, ids, _ = setup
    body = replay(client, ids["broad"], {"min_cumulative_volume": 5_000_000}).json()
    assert {c["ticker"] for c in body["changed"]} == {"ABCD", "EFGH"}


@pytest.mark.parametrize("overrides, message", [
    ({"secret_field": 1}, "cannot be overridden"),
    ({"negative_catalyst_types": "OFFERING"}, "cannot be overridden"),
    ({"max_float_shares": 1.5}, "whole number"),
    ({"min_pct_change": "0.2"}, "must be a number"),
    ({"catalyst_level": "SOMETIMES"}, "must be one of"),
    ({"min_room_to_resistance_pct": None}, "cannot be null"),
    ({"min_price": 25.0}, "min_price"),  # above max_price: InPlayConfig validation
    ({"min_price": -1}, "min_price"),
])
def test_invalid_overrides_rejected(setup, overrides, message):
    client, ids, _ = setup
    r = replay(client, ids["broad"], overrides)
    assert r.status_code == 400 and message in r.json()["detail"]


@pytest.mark.parametrize("overrides", [
    {"min_pct_change": True}, {"max_float_shares": False}, {"negative_catalyst_types": []},
    {"min_price": {"nested": 1}},
])
def test_non_scalar_or_boolean_values_rejected_by_schema(setup, overrides):
    # Booleans are never coerced into 1/0 thresholds; lists/objects never reach the config.
    client, ids, _ = setup
    assert replay(client, ids["broad"], overrides).status_code == 422


def test_replay_of_failed_run(setup):
    client, ids, _ = setup
    assert replay(client, ids["failed"]).status_code == 409


def test_replay_unknown_run(setup):
    client, _, _ = setup
    assert replay(client, "ffffffffff").status_code == 404


def test_replay_is_deterministic_and_never_writes(setup):
    client, ids, path = setup
    before = path.read_bytes()
    runs_before = client.get("/api/runs").json()
    first = replay(client, ids["broad"], {"min_pct_change": 0.02, "max_float_shares": 100_000_000}).json()
    second = replay(client, ids["broad"], {"min_pct_change": 0.02, "max_float_shares": 100_000_000}).json()
    assert first == second
    assert client.get("/api/runs").json() == runs_before
    assert path.read_bytes() == before


def test_replay_body_must_be_an_object(setup):
    client, ids, _ = setup
    r = client.post(f"/api/runs/{ids['broad']}/replay", json={"overrides": [1, 2]}, headers=WRITE_HEADERS)
    assert r.status_code == 422
