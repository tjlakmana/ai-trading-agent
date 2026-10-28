"""Named Finviz discovery profiles (V1 hypotheses, not Warrior Trading's rules).

    broad_v1   price $2-$20 and up on the day. A wide universe (about 1,100
               stocks on 2026-10-28); the in-play filter evaluates every one,
               and history classifies each as qualified / near-miss / filtered out.
    strict_v1  the original five-filter momentum screen (about 10 stocks).

Both use only verified filter codes. The profile only changes which stocks
Finviz returns. The in-play rules are the same for both.
"""

from types import MappingProxyType

from data.finviz.config import FinvizScreenConfig

BROAD_V1 = "broad_v1"
STRICT_V1 = "strict_v1"
CUSTOM_TICKERS = "custom_tickers"  # recorded name for --tickers screens

PROFILES = MappingProxyType({
    BROAD_V1: FinvizScreenConfig(filters=("sh_price_2to20", "ta_change_u")),
    STRICT_V1: FinvizScreenConfig(),
})
DEFAULT_PROFILE = STRICT_V1
