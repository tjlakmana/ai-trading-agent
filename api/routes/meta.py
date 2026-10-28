"""Health, modules, profiles and replay-form metadata."""

from fastapi import APIRouter, Depends, Request

from api import config_meta, schemas
from api.deps import history, utc_now
from api.modules import Capabilities, module_dicts
from data.finviz.client import api_key_configured
from data.finviz.profiles import DEFAULT_PROFILE, PROFILES
from data.finviz.schema import VERIFIED_FILTERS
from memory.scan_store import SCHEMA_VERSION

API_VERSION = "1"
router = APIRouter(prefix="/api", tags=["meta"])


def capabilities(request: Request) -> Capabilities:
    return Capabilities(finviz_configured=request.app.state.finviz_configured(),
                        history_available=request.app.state.settings.db_path.is_file())


@router.get("/health", response_model=schemas.HealthOut)
def health(request: Request, store=Depends(history)):
    return {"status": "ok", "api_version": API_VERSION, "server_time": utc_now(request),
            "database_exists": store is not None, "schema_version": SCHEMA_VERSION,
            "finviz_key_configured": request.app.state.finviz_configured()}


@router.get("/modules", response_model=list[schemas.ModuleOut])
def list_modules(request: Request):
    return module_dicts(capabilities(request))


@router.get("/profiles", response_model=list[schemas.ProfileOut])
def list_profiles():
    return [{"name": name, "is_default": name == DEFAULT_PROFILE,
             "filters": [{"code": f, "meaning": VERIFIED_FILTERS[f]} for f in config.filters]}
            for name, config in PROFILES.items()]


@router.get("/in-play-config", response_model=list[schemas.ConfigFieldOut])
def in_play_config_fields():
    return config_meta.field_specs()


def default_finviz_configured() -> bool:
    return api_key_configured()
