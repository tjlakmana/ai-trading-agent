"""Write the API's OpenAPI schema for the dashboard's generated TypeScript types.

    python -m api.openapi_export dashboard/openapi.json
    (then, in dashboard/: npm run gen:api)

tests/test_api_contract.py fails if the committed schema is out of date.
"""

import json
import sys
from pathlib import Path

from api.app import create_app
from api.settings import ApiSettings


def openapi_schema() -> dict:
    return create_app(ApiSettings(db_path=Path("unused.db"))).openapi()


def render() -> str:
    return json.dumps(openapi_schema(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "dashboard/openapi.json")
    target.write_text(render(), encoding="utf-8")
    print(f"wrote {target}")
