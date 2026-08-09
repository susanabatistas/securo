import { describe, expect, it } from 'vitest'
import { resolveAssetType } from './asset-classification'

describe('resolveAssetType', () => {
  it('overrides known Brazilian FIIs to fund, ignoring the fallback', () => {
    expect(resolveAssetType('HGLG11.SA', 'stock')).toBe('fund')
    expect(resolveAssetType('hglg11.sa', 'stock')).toBe('fund')
    expect(resolveAssetType('KNRI11', 'stock')).toBe('fund')
  })

  it('overrides known Brazilian ETFs to etf', () => {
    expect(resolveAssetType('BOVA11.SA', 'stock')).toBe('etf')
    expect(resolveAssetType('IVVB11', 'investment')).toBe('etf')
  })

  it('falls back to the provided quoteType-based guess for unknown tickers', () => {
    expect(resolveAssetType('AAPL', 'stock')).toBe('stock')
    expect(resolveAssetType('XPTO11.SA', 'investment')).toBe('investment')
  })
})
