"""Per-ticker history across recorded runs."""

from fastapi import APIRouter, Depends, Path, Query

from api import schemas, views
from api.deps import history

router = APIRouter(prefix="/api/tickers", tags=["tickers"])


@router.get("/{ticker}/history", response_model=schemas.TickerHistoryOut)
def ticker_history(ticker: str = Path(max_length=10, pattern=r"^[A-Za-z0-9.\-]+$"),
                   store=Depends(history), limit: int = Query(100, ge=1, le=1000)):
    symbol = ticker.upper()
    if store is None:
        return {"ticker": symbol, "observations": []}
    return {"ticker": symbol,
            "observations": [views.ticker_observation(o.started_at, o.profile_name, o.row)
                             for o in store.ticker_history(symbol, limit)]}
