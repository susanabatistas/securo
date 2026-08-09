"""Default classification for assets — pure, deterministic, no I/O."""
from app.providers.tesouro_direto import is_tesouro_symbol

# Static ticker -> Asset.type overrides for symbols Yahoo Finance's
# `quoteType` gets wrong or leaves ambiguous — the recurring case is
# Brazilian FIIs (fundos imobiliários), frequently reported as `EQUITY`,
# indistinguishable from a regular stock. Deliberately kept in sync with the
# frontend's copy (`frontend/src/lib/asset-classification.ts`) — duplicated
# across the TS/Python boundary like the rest of this codebase's per-language
# parsing helpers (e.g. import_service's CSV sniffer isn't shared either),
# not something meant to be imported cross-runtime.
_BR_TICKER_TYPE_OVERRIDES: dict[str, str] = {
    "BOVA11": "etf",
    "IVVB11": "etf",
    "SMAL11": "etf",
    "HASH11": "etf",
    "DIVO11": "etf",
    "XINA11": "etf",
    "IMAB11": "etf",
    "BBSD11": "etf",
    "ISUS11": "etf",
    "GOLD11": "etf",
    "HGLG11": "fund",
    "KNRI11": "fund",
    "MXRF11": "fund",
    "XPLG11": "fund",
    "VISC11": "fund",
    "BCFF11": "fund",
    "HGRE11": "fund",
    "KNCR11": "fund",
    "IRDM11": "fund",
    "RECT11": "fund",
}

_QUOTE_TYPE_TO_ASSET_TYPE: dict[str, str] = {
    "EQUITY": "stock",
    "ETF": "etf",
    "CRYPTOCURRENCY": "crypto",
    "MUTUALFUND": "fund",
    "INDEX": "fund",
}

_DEFAULT_ASSET_TYPE = "investment"


def _base_symbol(ticker: str) -> str:
    return ticker.strip().upper().removesuffix(".SA")


def resolve_asset_type(ticker: str, quote_type: str | None) -> str:
    """Resolve `Asset.type` for a newly-created ticker holding.

    Checks the static BR override list first (fixes Yahoo's ambiguous
    quoteType for FIIs), then falls back to the generic quoteType mapping,
    then to the generic `investment` bucket for anything unrecognized —
    left freely editable by the user afterwards.
    """
    override = _BR_TICKER_TYPE_OVERRIDES.get(_base_symbol(ticker))
    if override is not None:
        return override
    return _QUOTE_TYPE_TO_ASSET_TYPE.get((quote_type or "").upper(), _DEFAULT_ASSET_TYPE)


# --- IR (income tax) estimator bucket -------------------------------------
#
# Which regime applies if the position were sold today. Only securities are
# in scope — real_estate/vehicle/valuable/other have a wholly different
# capital-gains regime and are deliberately excluded (None = not applicable).
TAX_CATEGORIES = ("renda_fixa", "fii", "acoes_etfs_cripto")

_TAX_CATEGORY_BY_TYPE: dict[str, str] = {
    "stock": "acoes_etfs_cripto",
    "etf": "acoes_etfs_cripto",
    "crypto": "acoes_etfs_cripto",
    "fund": "fii",
    "investment": "renda_fixa",
}


def default_tax_category(asset_type: str, ticker: str | None = None) -> str | None:
    """Default IR bucket for `asset_type` (Tesouro Direto always renda_fixa
    regardless of type). None for types this estimator doesn't apply to."""
    if is_tesouro_symbol(ticker):
        return "renda_fixa"
    return _TAX_CATEGORY_BY_TYPE.get(asset_type)


def resolve_tax_category(asset_type: str, override: str | None, ticker: str | None = None) -> str | None:
    return override or default_tax_category(asset_type, ticker)
