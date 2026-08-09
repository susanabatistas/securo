// Static ticker -> Asset.type overrides for symbols Yahoo Finance's
// `quoteType` gets wrong or leaves ambiguous. The recurring case is Brazilian
// FIIs (fundos imobiliários): Yahoo frequently reports them as `EQUITY`,
// indistinguishable from a regular stock. ETFs are usually classified
// correctly already, but a few are listed here too where we've seen drift.
//
// Deliberately small and manually curated — not exhaustive. Tickers not in
// this list fall back to the existing quoteType-based detection
// (`assetTypeFromQuoteType`), and from there to the generic `investment`
// bucket, which the Tipo dropdown already lets the user correct by hand.
//
// Keys are the base B3 ticker without the `.SA` suffix, uppercase.
const BR_TICKER_CLASS_OVERRIDES: Record<string, 'etf' | 'fund'> = {
  // Common Brazilian ETFs
  BOVA11: 'etf',
  IVVB11: 'etf',
  SMAL11: 'etf',
  HASH11: 'etf',
  DIVO11: 'etf',
  XINA11: 'etf',
  IMAB11: 'etf',
  BBSD11: 'etf',
  ISUS11: 'etf',
  GOLD11: 'etf',
  // Common FIIs (fundos imobiliários) — mapped to `fund`, the closest
  // existing Asset.type bucket (there is no dedicated `fii` type).
  HGLG11: 'fund',
  KNRI11: 'fund',
  MXRF11: 'fund',
  XPLG11: 'fund',
  VISC11: 'fund',
  BCFF11: 'fund',
  HGRE11: 'fund',
  KNCR11: 'fund',
  IRDM11: 'fund',
  RECT11: 'fund',
}

function baseSymbol(symbol: string): string {
  return symbol.trim().toUpperCase().replace(/\.SA$/, '')
}

/**
 * Resolve the Asset.type for a ticker, preferring the static override list
 * for known-ambiguous Brazilian tickers before falling back to `fallback`
 * (normally `assetTypeFromQuoteType(quote.quote_type)`).
 */
export function resolveAssetType(symbol: string, fallback: string): string {
  const override = BR_TICKER_CLASS_OVERRIDES[baseSymbol(symbol)]
  return override ?? fallback
}
