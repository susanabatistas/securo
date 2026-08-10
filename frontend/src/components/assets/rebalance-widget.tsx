import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { PieChart, Pie, Cell, Tooltip as RechartsTooltip, ResponsiveContainer } from 'recharts'
import { ChevronDown, ChevronRight } from 'lucide-react'
import type { Asset, AssetGroup } from '@/types'
import { formatCurrency } from '@/lib/format'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const UNGROUPED_COLOR = '#9CA3AF'
// Drift under 1% of the total portfolio isn't worth flagging as an action —
// it's well within the noise of day-to-day price movement.
const TOLERANCE_FRACTION = 0.01
// Suggested contribution amounts under this fraction of the contribution
// itself round to visual noise — skip them rather than show "aportar R$0,03".
const MIN_ALLOCATION_FRACTION = 0.005

interface Row {
  key: string
  name: string
  color: string
  currentValue: number
  currentPct: number
  targetPct: number | null
}

function suggestion(currentValue: number, targetValue: number, toleranceValue: number): 'buy' | 'sell' | 'balanced' {
  const drift = currentValue - targetValue
  if (Math.abs(drift) <= toleranceValue) return 'balanced'
  return drift > 0 ? 'sell' : 'buy'
}

/**
 * B3 (and most markets) don't sell fractional shares — a raw R$ suggestion
 * like "aportar R$237,42" isn't actually buyable. Rounds a suggested amount
 * down to a whole number of units at the asset's last quoted price. Only
 * meaningful for market-priced tickers; manual/growth-rule assets (real
 * estate, vehicles...) have no per-unit price, so this returns null for
 * them and the raw R$ amount is shown as-is.
 */
function quantizeToUnits(amount: number, unitPrice: number | null | undefined): { units: number; amount: number } | null {
  if (unitPrice == null || unitPrice <= 0) return null
  const units = Math.floor(amount / unitPrice)
  return { units, amount: units * unitPrice }
}

interface AllocationTarget {
  key: string
  currentValue: number
  targetPct: number | null
}

/**
 * Deterministic "where should a new contribution go" split: money is
 * directed first at whatever is furthest below its target in absolute
 * terms, fully closing each gap before spilling over — once every target
 * is met, any remainder splits by target weight (so a contribution larger
 * than the total gap still lands somewhere sensible instead of piling
 * entirely onto the single most-underweight bucket). Items without a
 * target get nothing — same "not managed by rebalancing" policy as the
 * rest of this widget.
 */
function allocateContribution(items: AllocationTarget[], newTotal: number, amount: number): Map<string, number> {
  const result = new Map<string, number>()
  if (amount <= 0) return result
  const eligible = items.filter((i) => i.targetPct != null && i.targetPct > 0)
  if (eligible.length === 0) return result

  const targetPctSum = eligible.reduce((acc, i) => acc + (i.targetPct ?? 0), 0)
  const deficits = eligible.map((i) => ({
    key: i.key,
    targetPct: i.targetPct ?? 0,
    deficit: Math.max((newTotal * (i.targetPct ?? 0)) / 100 - i.currentValue, 0),
  }))
  const totalDeficit = deficits.reduce((acc, d) => acc + d.deficit, 0)

  if (totalDeficit >= amount) {
    if (totalDeficit > 0) {
      for (const d of deficits) result.set(d.key, (d.deficit / totalDeficit) * amount)
    }
  } else {
    const surplus = amount - totalDeficit
    for (const d of deficits) {
      const fromWeight = targetPctSum > 0 ? (d.targetPct / targetPctSum) * surplus : 0
      result.set(d.key, d.deficit + fromWeight)
    }
  }
  return result
}

/**
 * Allocation pie (by wallet) + hierarchical rebalance suggestions.
 * Two independent target levels, both optional:
 *   - AssetGroup.target_pct — a wallet's target share of the *total*
 *     portfolio.
 *   - Asset.target_pct — an asset's target share of its *own wallet*, not
 *     of the total. Effective target vs. the whole portfolio is the
 *     product of the two (wallet target × asset target), matching the
 *     "ETFs wallet = 20%, Asset A inside it = 50%" example this was built
 *     from.
 * Wallets/assets without a target still show up (current % only, no
 * suggestion) — nothing here is mandatory to fill in. Lives in its own
 * page-width tab, so the layout leans wider/taller than a squeezed card.
 */
export function RebalanceWidget({
  wallets,
  assetsByGroup,
  totalValue,
  userCurrency,
  locale,
  mask,
}: {
  wallets: AssetGroup[]
  assetsByGroup: Map<string | null, Asset[]>
  totalValue: number
  userCurrency: string
  locale: string
  mask: (v: string) => string
}) {
  const { t } = useTranslation()
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [contributionInput, setContributionInput] = useState('')
  const contributionAmount = Number(contributionInput) || 0

  const rows = useMemo((): Row[] => {
    const list: Row[] = wallets
      .map((w) => ({
        key: w.id,
        name: w.name,
        color: w.color,
        currentValue: w.current_value_primary,
        currentPct: totalValue > 0 ? (w.current_value_primary / totalValue) * 100 : 0,
        targetPct: w.target_pct,
      }))
      // Keep wallets with a target even at zero value — a wallet you just
      // created to grow into (target set, nothing bought yet) is exactly
      // the case the contribution calculator most needs to see, not one to
      // silently drop. Only truly untracked empty wallets (no target,
      // nothing in them) are filtered out.
      .filter((r) => r.currentValue > 0 || r.targetPct != null)

    const ungrouped = assetsByGroup.get(null) ?? []
    const ungroupedValue = ungrouped.reduce((acc, a) => acc + (a.current_value_primary ?? a.current_value ?? 0), 0)
    if (ungroupedValue > 0) {
      list.push({
        key: '__ungrouped__',
        name: t('assets.ungrouped'),
        color: UNGROUPED_COLOR,
        currentValue: ungroupedValue,
        currentPct: totalValue > 0 ? (ungroupedValue / totalValue) * 100 : 0,
        targetPct: null,
      })
    }
    return list.sort((a, b) => b.currentValue - a.currentValue)
  }, [wallets, assetsByGroup, totalValue, t])

  const targetPctSum = wallets.reduce((acc, w) => acc + (w.target_pct ?? 0), 0)
  const hasAnyTarget = rows.some((r) => r.targetPct != null)

  const walletAllocations = useMemo(
    () => allocateContribution(
      rows.map((r) => ({ key: r.key, currentValue: r.currentValue, targetPct: r.targetPct })),
      totalValue + contributionAmount,
      contributionAmount,
    ),
    [rows, totalValue, contributionAmount],
  )

  if (rows.length === 0) return null

  const tolerance = totalValue * TOLERANCE_FRACTION
  const minAllocation = contributionAmount * MIN_ALLOCATION_FRACTION

  return (
    <div className="space-y-5">
      {/* Contribution calculator — its own card up top since it's the most
          interactive piece and deserves to not be squeezed next to the pie. */}
      <div className="rounded-xl border border-border p-4">
        <Label htmlFor="rebalance-contribution" className="text-sm font-medium text-foreground">
          {t('assets.contributionLabel')}
        </Label>
        <div className="mt-2 flex flex-col sm:flex-row sm:items-start gap-3">
          <Input
            id="rebalance-contribution"
            type="number"
            min={0}
            step="0.01"
            placeholder="0"
            value={contributionInput}
            onChange={(e) => setContributionInput(e.target.value)}
            className="max-w-[200px]"
          />
          {contributionAmount > 0 && (
            <div className="flex-1 min-w-0">
              {!hasAnyTarget ? (
                <p className="text-xs text-muted-foreground py-2">{t('assets.contributionNeedsTargets')}</p>
              ) : walletAllocations.size === 0 ? (
                <p className="text-xs text-muted-foreground py-2">{t('assets.rebalanceBalanced')}</p>
              ) : (
                <div className="space-y-1.5">
                  <p className="text-xs font-medium text-muted-foreground">{t('assets.contributionSuggestionTitle')}</p>
                  <div className="flex flex-wrap gap-x-5 gap-y-1.5">
                    {rows
                      .map((r) => ({ row: r, amount: walletAllocations.get(r.key) ?? 0 }))
                      .filter(({ amount }) => amount > minAllocation)
                      .sort((a, b) => b.amount - a.amount)
                      .map(({ row, amount }) => (
                        <div key={row.key} className="flex items-center gap-1.5 text-sm">
                          <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ backgroundColor: row.color }} />
                          <span className="text-foreground">{row.name}</span>
                          <span className="font-semibold text-emerald-600 tabular-nums">
                            {mask(formatCurrency(amount, userCurrency, locale))}
                          </span>
                        </div>
                      ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Allocation pie + hierarchical drift list */}
      <div className="rounded-xl border border-border p-4 sm:p-6">
        <div className="text-sm font-medium text-foreground mb-4">{t('assets.rebalanceTitle')}</div>

        <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-8">
          <div className="relative h-64 mx-auto lg:mx-0 w-full max-w-[280px]">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={rows} dataKey="currentValue" nameKey="name" innerRadius={75} outerRadius={115} stroke="var(--card)" strokeWidth={3}>
                  {rows.map((r) => (
                    <Cell key={r.key} fill={r.color} />
                  ))}
                </Pie>
                <RechartsTooltip
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null
                    const row = payload[0].payload as Row
                    return (
                      <div style={{ background: 'var(--card)', color: 'var(--foreground)', border: '1px solid var(--border)', borderRadius: '0.75rem', fontSize: '12px', boxShadow: '0 4px 12px rgba(0,0,0,0.08)', padding: '8px 10px' }}>
                        <p style={{ fontWeight: 600 }}>{row.name}</p>
                        <p>{row.currentPct.toFixed(1)}% · {mask(formatCurrency(row.currentValue, userCurrency, locale))}</p>
                      </div>
                    )
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
            {/* Total, centered in the donut hole — recharts has no native
                slot for this, so it's an absolutely-positioned overlay. */}
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-[11px] text-muted-foreground">{t('assets.total')}</span>
              <span className="text-lg font-bold tabular-nums text-foreground">
                {mask(formatCurrency(totalValue, userCurrency, locale))}
              </span>
            </div>
          </div>

          <div className="min-w-0 space-y-1">
            {targetPctSum > 100 && (
              <p className="text-xs text-amber-600 mb-2">{t('assets.rebalanceOverTargetSum', { pct: targetPctSum.toFixed(0) })}</p>
            )}
            {rows.map((row) => {
              const walletAssets = row.key === '__ungrouped__' ? [] : (assetsByGroup.get(row.key) ?? [])
              const hasChildren = walletAssets.length > 0
              const isExpanded = expandedId === row.key
              const walletTargetValue = row.targetPct != null ? (totalValue * row.targetPct) / 100 : null
              const action = walletTargetValue != null ? suggestion(row.currentValue, walletTargetValue, tolerance) : null
              const assetTargetPctSum = walletAssets.reduce((acc, a) => acc + (a.target_pct ?? 0), 0)
              const walletAllocation = walletAllocations.get(row.key) ?? 0
              const assetAllocations = walletAllocation > 0
                ? allocateContribution(
                    walletAssets.map((a) => ({
                      key: a.id,
                      currentValue: a.current_value_primary ?? a.current_value ?? 0,
                      targetPct: a.target_pct,
                    })),
                    row.currentValue + walletAllocation,
                    walletAllocation,
                  )
                : new Map<string, number>()

              return (
                <div key={row.key} className="border-b border-border/60 last:border-b-0">
                  <button
                    type="button"
                    disabled={!hasChildren}
                    onClick={() => setExpandedId(isExpanded ? null : row.key)}
                    className="w-full flex items-center gap-2 text-sm py-2.5 text-left disabled:cursor-default hover:bg-muted/30 -mx-2 px-2 rounded-md transition-colors"
                  >
                    {hasChildren ? (
                      isExpanded ? <ChevronDown size={14} className="text-muted-foreground shrink-0" /> : <ChevronRight size={14} className="text-muted-foreground shrink-0" />
                    ) : (
                      <span className="w-3.5 shrink-0" />
                    )}
                    <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ backgroundColor: row.color }} />
                    <span className="text-foreground font-medium truncate flex-1">{row.name}</span>
                    <span className="text-muted-foreground tabular-nums shrink-0">
                      {row.currentPct.toFixed(0)}%{row.targetPct != null && ` / ${row.targetPct.toFixed(0)}%`}
                    </span>
                    {/* Only show the "close the whole gap" amount when there's no
                        contribution being planned — with one entered, the top
                        calculator already says exactly how much of it comes here,
                        and showing this larger theoretical number alongside would
                        read as "spend more than what you typed". */}
                    {action === 'buy' && walletTargetValue != null && contributionAmount === 0 && (
                      <span className="shrink-0 font-medium text-emerald-600">
                        {t('assets.rebalanceBuy', {
                          amount: mask(formatCurrency(Math.abs(row.currentValue - walletTargetValue), userCurrency, locale)),
                        })}
                      </span>
                    )}
                    {action === 'sell' && (
                      <span className="shrink-0 text-muted-foreground">{t('assets.rebalanceOverTarget')}</span>
                    )}
                    {action === 'balanced' && (
                      <span className="shrink-0 text-muted-foreground">{t('assets.rebalanceBalanced')}</span>
                    )}
                  </button>

                  {isExpanded && hasChildren && (
                    <div className="ml-[22px] pl-3 border-l border-border space-y-1.5 mt-0.5 mb-2.5">
                      {assetTargetPctSum > 100 && (
                        <p className="text-[11px] text-amber-600">{t('assets.rebalanceOverTargetSum', { pct: assetTargetPctSum.toFixed(0) })}</p>
                      )}
                      {walletAssets.map((asset) => {
                        const assetValue = asset.current_value_primary ?? asset.current_value ?? 0
                        const assetPctOfWallet = row.currentValue > 0 ? (assetValue / row.currentValue) * 100 : 0
                        const assetTargetValue = walletTargetValue != null && asset.target_pct != null
                          ? (walletTargetValue * asset.target_pct) / 100
                          : null
                        const assetAction = assetTargetValue != null ? suggestion(assetValue, assetTargetValue, tolerance) : null
                        const assetContribution = assetAllocations.get(asset.id) ?? 0
                        // Current price per unit, in primary currency — derived from
                        // already-converted current_value_primary / units rather than
                        // the asset's native-currency last_price, so this stays correct
                        // for international tickers without a separate FX lookup.
                        const unitPricePrimary = asset.valuation_method === 'market_price' && asset.units && asset.units > 0
                          ? assetValue / asset.units
                          : null

                        // Contribution money (if any) takes priority. The full
                        // "close the whole gap" drift amount only makes sense as a
                        // number to actually spend when there's no contribution
                        // being planned — with one entered, an asset that got none
                        // of it (other assets had bigger gaps) shouldn't still show
                        // a bigger, unfunded number that reads as "spend more than
                        // what you typed".
                        const rawSuggested = assetContribution > minAllocation
                          ? assetContribution
                          : contributionAmount === 0 && assetAction === 'buy' && assetTargetValue != null
                            ? Math.abs(assetValue - assetTargetValue)
                            : null
                        const quantized = rawSuggested != null ? quantizeToUnits(rawSuggested, unitPricePrimary) : null

                        return (
                          <div key={asset.id} className="flex items-center gap-2 text-xs py-0.5">
                            <span className="text-muted-foreground truncate flex-1">{asset.ticker || asset.name}</span>
                            <span className="text-muted-foreground tabular-nums shrink-0">
                              {assetPctOfWallet.toFixed(0)}%{asset.target_pct != null && ` / ${asset.target_pct.toFixed(0)}%`}
                            </span>
                            {rawSuggested != null && quantized && quantized.units > 0 ? (
                              <span className="shrink-0 font-medium text-emerald-600">
                                {t('assets.rebalanceBuyUnits', {
                                  count: quantized.units,
                                  amount: mask(formatCurrency(quantized.amount, userCurrency, locale)),
                                })}
                              </span>
                            ) : rawSuggested != null && quantized && quantized.units === 0 ? (
                              <span className="shrink-0 text-muted-foreground">
                                {t('assets.rebalanceMinUnit', { amount: mask(formatCurrency(unitPricePrimary as number, userCurrency, locale)) })}
                              </span>
                            ) : rawSuggested != null ? (
                              // No per-unit price to quantize against (manual/growth-rule
                              // assets aren't bought in discrete units) — raw amount stands.
                              <span className="shrink-0 font-medium text-emerald-600">
                                {t('assets.rebalanceBuy', { amount: mask(formatCurrency(rawSuggested, userCurrency, locale)) })}
                              </span>
                            ) : assetAction === 'sell' ? (
                              <span className="shrink-0 text-muted-foreground">{t('assets.rebalanceOverTarget')}</span>
                            ) : assetAction === 'balanced' ? (
                              <span className="shrink-0 text-muted-foreground">{t('assets.rebalanceBalanced')}</span>
                            ) : asset.target_pct == null && row.targetPct != null ? (
                              <span className="shrink-0 text-muted-foreground">{t('assets.rebalanceNoTarget')}</span>
                            ) : null}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
