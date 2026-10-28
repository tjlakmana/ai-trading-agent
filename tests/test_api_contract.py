"""The dashboard's TypeScript types are generated from dashboard/openapi.json; keep it current."""

from pathlib import Path

from api.openapi_export import render

ROOT = Path(__file__).resolve().parent.parent


def test_committed_openapi_schema_is_current():
    committed = (ROOT / "dashboard" / "openapi.json").read_text(encoding="utf-8")
    assert committed == render(), (
        "dashboard/openapi.json is stale: run `python -m api.openapi_export dashboard/openapi.json` "
        "then `npm run gen:api` in dashboard/")


def test_generated_types_exist():
    assert (ROOT / "dashboard" / "src" / "api" / "schema.d.ts").is_file()
