import { useState, useMemo, useEffect, useRef, useCallback, memo } from 'react'
import { useTranslation } from 'react-i18next'
import { useDisplayLocale, useDateLocale } from '@/hooks/use-display-locale'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useRegisterPageChatContext } from '@/lib/page-chat-context'
import { assets, assetGroups, currencies as currenciesApi } from '@/lib/api'
import { localDateString } from '@/lib/date-utils'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { DatePickerInput } from '@/components/ui/date-picker-input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { Asset, AssetGroup, AssetTransaction, AssetValue, MarketSymbolMatch, MarketSymbolQuote } from '@/types'
import {
  Home,
  Car,
  Gem,
  TrendingUp,
  Package,
  Plus,
  Pencil,
  Trash2,
  ChevronDown,
  ChevronUp,
  ChevronRight,
  RefreshCw,
  Wallet,
  FolderInput,
  LineChart,
  Layers,
  Bitcoin,
  PieChart,
  AlertTriangle,
} from 'lucide-react'
import {
  AreaChart,
  Area,
  LineChart as RechartsLineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
} from 'recharts'
import { PageHeader } from '@/components/page-header'
import { usePrivacyMode } from '@/hooks/use-privacy-mode'
import { useAuth } from '@/contexts/auth-context'
import { useWorkspace } from '@/contexts/workspace-context'
import { useCollectionFilter } from '@/contexts/collection-filter-context'

// Intl.NumberFormat construction is expensive relative to .format() — this
// page calls formatCurrency several times per holding row plus once per
// series per chart-tooltip frame (i.e. on every mousemove while hovering
// the portfolio/value chart), so an uncached formatter measurably compounds
// with asset count. Cache is unbounded but keyed on (locale, currency)
// pairs, which is a tiny, near-constant set in practice.
const currencyFormatterCache = new Map<string, Intl.NumberFormat>()

function getCurrencyFormatter(currency: string, locale: string): Intl.NumberFormat {
  const key = `${locale}|${currency}`
  let fmt = currencyFormatterCache.get(key)
  if (!fmt) {
    try {
      fmt = new Intl.NumberFormat(locale, { style: 'currency', currency })
    } catch {
      fmt = new Intl.NumberFormat(locale, { style: 'currency', currency: 'USD' })
    }
    currencyFormatterCache.set(key, fmt)
  }
  return fmt
}

function formatCurrency(value: number, currency = 'USD', locale = 'en-US') {
  return getCurrencyFormatter(currency || 'USD', locale).format(value)
}

// Renders a logo image when one is available, falling back to the asset's
// type-based Lucide icon on missing URL or broken image. Uses the type's
// bg color as a tinted placeholder; switches to a white card + border when
// showing a real logo so brand colors don't clash with our palette.
function AssetIcon({
  logoUrl,
  Icon,
  colorClass,
  bgClass,
  size = 20,
  tile = 'w-10 h-10',
}: {
  logoUrl: string | null | undefined
  Icon: React.ElementType
  colorClass: string
  bgClass: string
  size?: number
  tile?: string
}) {
  const [errored, setErrored] = useState(false)
  const showImage = !!logoUrl && !errored
  return (
    <div
      className={`${tile} rounded-lg flex items-center justify-center overflow-hidden shrink-0 ${
        showImage ? 'bg-white border border-border' : bgClass
      }`}
    >
      {showImage ? (
        <img
          src={logoUrl!}
          alt=""
          className="w-full h-full object-contain"
          onError={() => setErrored(true)}
        />
      ) : (
        <Icon size={size} className={colorClass} />
      )}
    </div>
  )
}

// Compact relative-time formatter ("2h ago" / "há 2h"). Used for the price
// preview "last updated" hint. Intl.RelativeTimeFormat handles the locale
// grammar so we don't hand-roll plurals. Falls back to absolute date only
// when the input is missing — otherwise always returns a relative string.
function formatRelativeTime(dateInput: string | null | undefined, locale: string): string | null {
  if (!dateInput) return null
  const then = new Date(dateInput).getTime()
  if (Number.isNaN(then)) return null
  const diffSec = (then - Date.now()) / 1000
  const absSec = Math.abs(diffSec)
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })
  if (absSec < 60) return rtf.format(Math.round(diffSec), 'second')
  if (absSec < 3600) return rtf.format(Math.round(diffSec / 60), 'minute')
  if (absSec < 86400) return rtf.format(Math.round(diffSec / 3600), 'hour')
  return rtf.format(Math.round(diffSec / 86400), 'day')
}

const ASSET_TYPE_CONFIG: Record<string, { icon: React.ElementType; color: string; bg: string }> = {
  real_estate: { icon: Home, color: 'text-blue-600', bg: 'bg-blue-100' },
  vehicle: { icon: Car, color: 'text-violet-600', bg: 'bg-violet-100' },
  valuable: { icon: Gem, color: 'text-amber-600', bg: 'bg-amber-100' },
  investment: { icon: TrendingUp, color: 'text-emerald-600', bg: 'bg-emerald-100' },
  stock: { icon: LineChart, color: 'text-sky-600', bg: 'bg-sky-100' },
  etf: { icon: Layers, color: 'text-teal-600', bg: 'bg-teal-100' },
  crypto: { icon: Bitcoin, color: 'text-orange-600', bg: 'bg-orange-100' },
  fund: { icon: PieChart, color: 'text-indigo-600', bg: 'bg-indigo-100' },
  other: { icon: Package, color: 'text-slate-600', bg: 'bg-slate-100' },
}

function getTypeConfig(type: string) {
  return ASSET_TYPE_CONFIG[type] ?? ASSET_TYPE_CONFIG['other']
}

const ASSET_TYPES = [
  'stock',
  'etf',
  'crypto',
  'fund',
  'real_estate',
  'vehicle',
  'valuable',
  'investment',
  'other',
] as const

// Map a yfinance `quoteType` to Securo's asset type. Lives here (not the
// backend) so if we ever swap the market-price provider the service stays
// clean — all provider-specific vocabulary is translated at the edge.
function assetTypeFromQuoteType(quoteType: string | null | undefined): string {
  switch ((quoteType || '').toUpperCase()) {
    case 'EQUITY':
      return 'stock'
    case 'ETF':
      return 'etf'
    case 'CRYPTOCURRENCY':
      return 'crypto'
    case 'MUTUALFUND':
    case 'INDEX':
      return 'fund'
    default:
      return 'investment'
  }
}
// `real_estate` -> `assets.typeRealEstate`. Shared by the type dropdown and
// the holdings table row so the two i18n lookups never drift apart.
function assetTypeI18nKey(type: string): string {
  return `assets.type${type.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase()).replace(/^./, c => c.toUpperCase())}`
}
const VALUATION_METHODS = ['manual', 'growth_rule', 'market_price'] as const
const GROWTH_TYPES = ['percentage', 'absolute'] as const
const GROWTH_FREQUENCIES = ['daily', 'weekly', 'monthly', 'yearly'] as const

// Column template shared by the holdings table header + rows so they align:
// Ativo · Quant. · Preço Médio · Preço Atual · Rentab. · Saldo · % · actions.
const HOLDINGS_GRID = 'minmax(0,2.4fr) 0.7fr 1.1fr 1fr 0.9fr 1.3fr 0.6fr 4.5rem'

// Surface the backend's actual error message (FastAPI puts it in
// response.data.detail) instead of a generic toast. Makes failures
// diagnosable — e.g. the oversell guard message, or a "Not Found" when a
// transaction endpoint is missing because the backend is older than the
// frontend (issue #315) — rather than a cryptic "Error".
function assetErrorMessage(e: unknown, fallback: string): string {
  const resp = (e as { response?: { data?: { detail?: unknown }; status?: number } })?.response
  const detail = resp?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  return resp?.status ? `${fallback} (${resp.status})` : fallback
}

// Shared by the ledger's add/edit-transaction dialog and the "add transaction
// to this holding" dialog: no shorting, so a sell can't exceed what's held.
function isOversell(kind: 'buy' | 'sell', quantity: string, heldUnits: number): boolean {
  return kind === 'sell' && !!quantity && parseFloat(quantity) > heldUnits
}

// The ledger total preview ("qty × price ± fee") shown in both buy/sell
// dialogs — identical math and markup, kept in one place so they can't drift.
function TxTotalPreview({ quantity, price, fee, kind, currency, locale }: {
  quantity: string; price: string; fee: string; kind: 'buy' | 'sell'; currency: string; locale: string
}) {
  const { t } = useTranslation()
  if (!quantity || !price || parseFloat(quantity) <= 0) return null
  const total = parseFloat(quantity) * parseFloat(price) + (fee ? parseFloat(fee) : 0) * (kind === 'buy' ? 1 : -1)
  return (
    <div className="flex items-center justify-between p-3 rounded-lg border border-border bg-muted/30">
      <span className="text-xs font-medium text-muted-foreground">{t('assets.txTotal')}</span>
      <span className="text-sm font-bold tabular-nums text-foreground">{formatCurrency(total, currency, locale)}</span>
    </div>
  )
}

// One row of the holdings table. All props are primitives/stable callbacks
// (see AssetsPage's useCallback-wrapped handlers), so memo() lets an
// unrelated parent re-render — e.g. a keystroke in the Add Asset dialog —
// skip every row except the one actually toggled/edited.
const HoldingRow = memo(function HoldingRow({
  asset,
  portfolioTotalPrimary,
  userCurrency,
  locale,
  dateLocale,
  mask,
  canWrite,
  isExpanded,
  onToggleExpand,
  onAddTransaction,
  onMoveAsset,
  onEdit,
  onDelete,
  onChanged,
}: {
  asset: Asset
  portfolioTotalPrimary: number
  userCurrency: string
  locale: string
  dateLocale: string
  mask: (v: string) => string
  canWrite: boolean
  isExpanded: boolean
  onToggleExpand: (id: string) => void
  onAddTransaction: (id: string) => void
  onMoveAsset: (asset: Asset) => void
  onEdit: (asset: Asset) => void
  onDelete: (id: string) => void
  onChanged: () => void
}) {
  const { t } = useTranslation()
  const config = getTypeConfig(asset.type)
  const Icon = config.icon
  const isSynced = asset.source !== 'manual'
  const isMarketPriced = asset.valuation_method === 'market_price'
  const isProviderOwned = isSynced && !isMarketPriced
  const hasCost = asset.average_price != null && asset.total_invested != null
  const returnPct =
    hasCost && asset.gain_loss != null && asset.total_invested
      ? (asset.gain_loss / asset.total_invested) * 100
      : null
  const pctOfPortfolio =
    portfolioTotalPrimary > 0 && asset.current_value_primary != null
      ? (asset.current_value_primary / portfolioTotalPrimary) * 100
      : null
  const needsBuys = isMarketPriced && !hasCost && !asset.sell_date

  return (
    <div className="border-b border-border last:border-b-0">
      <div
        className="grid items-center gap-2 px-3 py-3 cursor-pointer hover:bg-muted/20 transition-colors text-sm"
        style={{ gridTemplateColumns: HOLDINGS_GRID }}
        onClick={() => onToggleExpand(asset.id)}
      >
        {/* Ativo */}
        <div className="flex items-center gap-2.5 min-w-0">
          <AssetIcon logoUrl={asset.logo_url} Icon={Icon} colorClass={config.color} bgClass={config.bg} size={16} tile="w-8 h-8" />
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="font-semibold text-foreground truncate">{asset.ticker && !asset.ticker.startsWith('TD:') ? asset.ticker : asset.name}</span>
              {needsBuys && (
                <Badge
                  variant="outline"
                  className="text-[9px] px-1 py-0 text-amber-600 border-amber-300 bg-amber-50 dark:bg-amber-950/30 gap-0.5 shrink-0"
                  title={t('assets.noPriceWarning')}
                >
                  <AlertTriangle size={9} />
                  {t('assets.noPriceBadge')}
                </Badge>
              )}
              {asset.sell_date && (
                <Badge variant="outline" className="text-[9px] px-1 py-0 text-rose-600 border-rose-200">{t('assets.sold')}</Badge>
              )}
              {isSynced && !isMarketPriced && (
                <Badge variant="outline" className="text-[9px] px-1 py-0 text-sky-600 border-sky-200">{t('assets.synced')}</Badge>
              )}
            </div>
            <span className="text-[11px] text-muted-foreground truncate block">{asset.ticker && !asset.ticker.startsWith('TD:') ? asset.name : (asset.ticker?.startsWith('TD:') ? 'Tesouro Direto' : t(assetTypeI18nKey(asset.type)))}</span>
          </div>
        </div>
        {/* Quant. */}
        <div className="text-right tabular-nums text-muted-foreground">
          {asset.units != null ? mask(`${asset.units}`) : '—'}
        </div>
        {/* Preço Médio */}
        <div className="text-right tabular-nums">
          {asset.average_price != null ? mask(formatCurrency(asset.average_price, asset.currency, locale)) : (
            needsBuys && canWrite ? (
              <button
                onClick={(e) => { e.stopPropagation(); onAddTransaction(asset.id) }}
                className="text-[11px] font-medium text-primary hover:underline"
              >
                + {t('assets.addBuys')}
              </button>
            ) : <span className="text-muted-foreground">—</span>
          )}
        </div>
        {/* Preço Atual */}
        <div className="text-right tabular-nums text-muted-foreground">
          {asset.last_price != null ? mask(formatCurrency(asset.last_price, asset.currency, locale)) : '—'}
        </div>
        {/* Rentabilidade */}
        <div className="text-right tabular-nums">
          {returnPct != null ? (
            <span className={returnPct >= 0 ? 'text-emerald-600' : 'text-rose-500'}>
              {returnPct >= 0 ? '+' : ''}{returnPct.toFixed(1)}%
            </span>
          ) : <span className="text-muted-foreground">—</span>}
        </div>
        {/* Saldo */}
        <div className="text-right tabular-nums">
          {asset.current_value != null ? (
            <>
              <span className="font-semibold text-foreground">{mask(formatCurrency(asset.current_value, asset.currency, locale))}</span>
              {asset.current_value_primary != null && asset.currency !== userCurrency && (
                <span className="block text-[10px] text-muted-foreground">{mask(formatCurrency(asset.current_value_primary, userCurrency, locale))}</span>
              )}
            </>
          ) : <span className="text-muted-foreground">—</span>}
        </div>
        {/* % carteira */}
        <div className="text-right tabular-nums text-muted-foreground">
          {pctOfPortfolio != null ? `${pctOfPortfolio.toFixed(1)}%` : '—'}
        </div>
        {/* actions */}
        <div className="flex items-center justify-end gap-0.5">
          {canWrite && (
            <>
              <button onClick={(e) => { e.stopPropagation(); onMoveAsset(asset) }} title={t('assets.moveToWallet')} className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted transition-colors">
                <FolderInput size={13} />
              </button>
              <button onClick={(e) => { e.stopPropagation(); if (!isProviderOwned) onEdit(asset) }} disabled={isProviderOwned} title={isProviderOwned ? t('assets.syncedReadOnly') : t('common.edit')} className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-30 disabled:cursor-not-allowed">
                <Pencil size={13} />
              </button>
              <button onClick={(e) => { e.stopPropagation(); if (!isProviderOwned) onDelete(asset.id) }} disabled={isProviderOwned} title={isProviderOwned ? t('assets.syncedReadOnly') : t('common.delete')} className="p-1 rounded text-muted-foreground hover:text-rose-600 hover:bg-rose-50 transition-colors disabled:opacity-30 disabled:cursor-not-allowed">
                <Trash2 size={13} />
              </button>
            </>
          )}
          {isExpanded ? <ChevronUp size={15} className="text-muted-foreground" /> : <ChevronDown size={15} className="text-muted-foreground" />}
        </div>
      </div>

      {isExpanded && (
        isMarketPriced ? (
          <>
            {/* Value-evolution chart on top, then the buy/sell ledger. */}
            <AssetDetail assetId={asset.id} currency={asset.currency} locale={locale} dateLocale={dateLocale} purchasePrice={asset.purchase_price} purchaseDate={asset.purchase_date} valuationMethod={asset.valuation_method} canWrite={canWrite} chartOnly />
            <HoldingLedger
              asset={asset}
              locale={locale}
              dateLocale={dateLocale}
              mask={mask}
              canWrite={canWrite}
              onAdd={() => onAddTransaction(asset.id)}
              onChanged={onChanged}
            />
          </>
        ) : (
          <AssetDetail assetId={asset.id} currency={asset.currency} locale={locale} dateLocale={dateLocale} purchasePrice={asset.purchase_price} purchaseDate={asset.purchase_date} valuationMethod={asset.valuation_method} canWrite={canWrite} />
        )
      )}
    </div>
  )
})

type AssetDialogMode = { kind: 'create' } | { kind: 'edit'; asset: Asset } | null

// Create/Edit Asset dialog, extracted to its own component so its form
// state doesn't live on AssetsPage — before this, every keystroke here
// re-rendered the entire page (holdings table, wallets, chart) because
// that state lived there instead. Now typing only re-renders this dialog.
const AssetDialog = memo(function AssetDialog({
  mode,
  onClose,
  sortedWallets,
  supportedCurrencies,
  userCurrency,
  locale,
  dateLocale,
  onRequestCreateWallet,
  createWalletPending,
  pendingWalletAssignment,
  onChanged,
}: {
  mode: AssetDialogMode
  onClose: () => void
  sortedWallets: AssetGroup[]
  supportedCurrencies: Array<{ code: string; symbol: string; name: string; flag: string }> | undefined
  userCurrency: string
  locale: string
  dateLocale: string
  onRequestCreateWallet: () => void
  createWalletPending: boolean
  pendingWalletAssignment: { id: string; nonce: number } | null
  onChanged: () => void
}) {
  const { t } = useTranslation()
  const open = mode !== null

  const [editingAsset, setEditingAsset] = useState<Asset | null>(null)
  const [formName, setFormName] = useState('')
  const [formType, setFormType] = useState<string>('other')
  const [formCurrency, setFormCurrency] = useState(userCurrency)
  const [formGroupId, setFormGroupId] = useState<string>('')
  const [formMethod, setFormMethod] = useState<string>('manual')
  const [formPurchaseDate, setFormPurchaseDate] = useState<string>('')
  const [formPurchasePrice, setFormPurchasePrice] = useState('')
  const [formSellDate, setFormSellDate] = useState<string>('')
  const [formSellPrice, setFormSellPrice] = useState('')
  const [formCurrentValue, setFormCurrentValue] = useState('')
  const [formGrowthType, setFormGrowthType] = useState<string>('percentage')
  const [formGrowthRate, setFormGrowthRate] = useState('')
  const [formGrowthFrequency, setFormGrowthFrequency] = useState<string>('monthly')
  const [formGrowthStartDate, setFormGrowthStartDate] = useState<string>('')
  // Market-price form state
  const [formTickerQuery, setFormTickerQuery] = useState('')
  const [tickerMatches, setTickerMatches] = useState<MarketSymbolMatch[]>([])
  const [tickerSearchLoading, setTickerSearchLoading] = useState(false)
  const [selectedQuote, setSelectedQuote] = useState<MarketSymbolQuote | null>(null)
  // Tracks the symbol just picked from the dropdown, synchronously — unlike
  // selectedQuote (set only after the async marketQuote resolves), this lets
  // the search effect below bail out immediately instead of racing the quote
  // fetch and re-populating the dropdown with the ticker the user just chose.
  const pickedSymbolRef = useRef<string | null>(null)
  const [formUnits, setFormUnits] = useState('')
  // Per-unit purchase price for the opening buy of a market-priced holding.
  // Defaults to the live quote (buying at market now) and is the SAME input
  // model as the buy/sell ledger — no total-purchase-price for tickers, so
  // "Add asset" and "Add transaction" stay consistent.
  const [formUnitPrice, setFormUnitPrice] = useState('')
  const [quoteLoading, setQuoteLoading] = useState(false)
  const [pendingGrowthSave, setPendingGrowthSave] = useState<Record<string, unknown> | null>(null)

  function resetMarketPriceForm() {
    pickedSymbolRef.current = null
    setFormTickerQuery('')
    setTickerMatches([])
    setSelectedQuote(null)
    setFormUnits('')
    setFormUnitPrice('')
    setQuoteLoading(false)
    setTickerSearchLoading(false)
  }

  // Reset (create) or populate (edit) the form whenever the dialog is
  // asked to open in a new mode — replaces the old imperative
  // openCreate()/openEdit() calls now that AssetsPage just flips `mode`.
  useEffect(() => {
    if (!mode) return
    if (mode.kind === 'create') {
      setEditingAsset(null)
      setFormName('')
      setFormType('other')
      setFormCurrency(userCurrency)
      setFormGroupId('')
      setFormMethod('manual')
      setFormPurchaseDate('')
      setFormPurchasePrice('')
      setFormSellDate('')
      setFormSellPrice('')
      setFormCurrentValue('')
      setFormGrowthType('percentage')
      setFormGrowthRate('')
      setFormGrowthFrequency('monthly')
      setFormGrowthStartDate('')
      resetMarketPriceForm()
    } else {
      const asset = mode.asset
      setEditingAsset(asset)
      setFormName(asset.name)
      setFormType(asset.type)
      setFormCurrency(asset.currency)
      setFormGroupId(asset.group_id ?? '')
      setFormMethod(asset.valuation_method)
      setFormPurchaseDate(asset.purchase_date ?? '')
      setFormPurchasePrice(asset.purchase_price?.toString() ?? '')
      setFormSellDate(asset.sell_date ?? '')
      setFormSellPrice(asset.sell_price?.toString() ?? '')
      setFormCurrentValue('')
      setFormGrowthType(asset.growth_type ?? 'percentage')
      setFormGrowthRate(asset.growth_rate?.toString() ?? '')
      setFormGrowthFrequency(asset.growth_frequency ?? 'monthly')
      setFormGrowthStartDate(asset.growth_start_date ?? '')
      resetMarketPriceForm()
      if (asset.valuation_method === 'market_price' && asset.ticker) {
        setFormTickerQuery(asset.ticker)
        setFormUnits(asset.units?.toString() ?? '')
        // Synthesize a quote from the cached fields so the preview shows
        // immediately — we skip a round-trip to yfinance on edit open.
        if (asset.last_price != null) {
          setSelectedQuote({
            symbol: asset.ticker,
            name: asset.name,
            exchange: asset.ticker_exchange,
            currency: asset.currency,
            price: asset.last_price,
            quote_type: null,
          })
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- resetMarketPriceForm only touches local setters/refs
  }, [mode, userCurrency])

  // Applies the wallet id from a "+ New Wallet" flow started inside this
  // dialog — see AssetsPage's pendingAssignWalletToFormRef for the other
  // half. Keyed on the nonce (not just the id) so re-creating a wallet
  // with the same id twice in a row still re-fires.
  useEffect(() => {
    if (pendingWalletAssignment) setFormGroupId(pendingWalletAssignment.id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingWalletAssignment?.nonce])

  const createMutation = useMutation({
    mutationFn: (data: Parameters<typeof assets.create>[0]) => assets.create(data),
    onSuccess: () => {
      onChanged()
      onClose()
      toast.success(t('assets.created'))
    },
    onError: (e) => toast.error(assetErrorMessage(e, t('common.error'))),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, _regenerateGrowth, ...data }: Partial<Asset> & { id: string; _regenerateGrowth?: boolean }) =>
      assets.update(id, data, { regenerateGrowth: _regenerateGrowth }),
    onSuccess: () => {
      onChanged()
      onClose()
      setEditingAsset(null)
      toast.success(t('assets.updated'))
    },
    onError: (e) => toast.error(assetErrorMessage(e, t('common.error'))),
  })

  const refreshPriceMutation = useMutation({
    mutationFn: (id: string) => assets.refreshPrice(id),
    onSuccess: (updated) => {
      // Sync the dialog's preview to the fresh quote so the user sees the
      // new price without closing the dialog. The list + chart refetch
      // via our standard helper.
      setSelectedQuote({
        symbol: updated.ticker || '',
        name: updated.name,
        exchange: updated.ticker_exchange,
        currency: updated.currency,
        price: updated.last_price ?? 0,
        quote_type: null,
      })
      setEditingAsset(updated)
      onChanged()
      toast.success(t('assets.priceRefreshed'))
    },
    onError: (e) => toast.error(assetErrorMessage(e, t('common.error'))),
  })

  // Compute projected current value for growth_rule preview in the form
  const projectedGrowthValue = useMemo(() => {
    if (formMethod !== 'growth_rule') return null
    const baseAmount = parseFloat(formPurchasePrice)
    const rate = parseFloat(formGrowthRate)
    if (!baseAmount || !rate || !formGrowthFrequency) return null

    const startDate = formGrowthStartDate || formPurchaseDate
    if (!startDate) return null

    const today = new Date()
    today.setHours(0, 0, 0, 0)
    let current = baseAmount
    let d = new Date(startDate + 'T00:00:00')

    let iterations = 0
    while (iterations < 10000) {
      const next = new Date(d)
      if (formGrowthFrequency === 'daily') next.setDate(next.getDate() + 1)
      else if (formGrowthFrequency === 'weekly') next.setDate(next.getDate() + 7)
      else if (formGrowthFrequency === 'monthly') next.setMonth(next.getMonth() + 1)
      else if (formGrowthFrequency === 'yearly') next.setFullYear(next.getFullYear() + 1)
      else break
      if (next > today) break
      if (formGrowthType === 'percentage') {
        current = current * (1 + rate / 100)
      } else {
        current = current + rate
      }
      d = next
      iterations++
    }
    return Math.round(current * 100) / 100
  }, [formMethod, formPurchasePrice, formGrowthRate, formGrowthType, formGrowthFrequency, formGrowthStartDate, formPurchaseDate])

  // Debounced ticker search. Runs only when the market-price method is
  // selected and the query is non-trivial — keeps the autocomplete snappy
  // without flooding the yfinance-backed endpoint.
  useEffect(() => {
    if (formMethod !== 'market_price') return
    const q = formTickerQuery.trim()
    // Don't search if the field matches a just-picked symbol — checked via
    // ref (not selectedQuote) because selectedQuote only lands after the
    // async marketQuote call resolves, which can race this debounced search.
    if (pickedSymbolRef.current && q === pickedSymbolRef.current) return
    if (q.length < 1) {
      setTickerMatches([])
      return
    }
    setTickerSearchLoading(true)
    const handle = window.setTimeout(async () => {
      try {
        const results = await assets.marketSearch(q, 10)
        setTickerMatches(results)
      } catch {
        setTickerMatches([])
      } finally {
        setTickerSearchLoading(false)
      }
    }, 300)
    return () => window.clearTimeout(handle)
  }, [formMethod, formTickerQuery, selectedQuote])

  async function pickTickerMatch(match: MarketSymbolMatch) {
    pickedSymbolRef.current = match.symbol
    setTickerMatches([])
    setFormTickerQuery(match.symbol)
    setQuoteLoading(true)
    try {
      const quote = await assets.marketQuote(match.symbol)
      setSelectedQuote(quote)
      // Prefill the unit price with the live quote — "buying at market now"
      // is the common case; the user overrides it with their real cost.
      // Trim float noise to the DB's 6-decimal scale (39.41999… → 39.42).
      setFormUnitPrice(String(Number(quote.price.toFixed(6))))
      // Auto-fill name/currency from the authoritative quote so the user
      // doesn't have to think about it — they can still edit name after.
      if (!formName || formName === (selectedQuote?.name ?? selectedQuote?.symbol ?? '')) {
        setFormName(quote.name || quote.symbol)
      }
      setFormCurrency(quote.currency)
      // Classify the asset from the quote type (EQUITY → stock, etc.) so
      // the Tipo dropdown lands on something meaningful by default. We
      // skip this when the user already picked a non-default type, so
      // manual overrides stick.
      const suggestedType = assetTypeFromQuoteType(quote.quote_type)
      if (formType === 'other' || formType === 'investment') {
        setFormType(suggestedType)
      }
    } catch {
      toast.error(t('common.error'))
      setSelectedQuote(null)
    } finally {
      setQuoteLoading(false)
    }
  }

  function buildPayload() {
    const isMarket = formMethod === 'market_price'
    const payload: Record<string, unknown> = {
      name: formName,
      type: formType,
      currency: formCurrency,
      group_id: formGroupId || null,
      valuation_method: formMethod,
      purchase_date: formPurchaseDate || null,
      // Tickers have no total purchase price — the cost basis is derived from
      // the unit-price buy (and then the ledger). Only manual/growth assets
      // carry a total purchase price.
      purchase_price: isMarket ? null : (formPurchasePrice ? parseFloat(formPurchasePrice) : null),
      sell_date: isMarket ? null : (formSellDate || null),
      sell_price: isMarket ? null : (formSellPrice ? parseFloat(formSellPrice) : null),
    }

    if (formMethod === 'growth_rule') {
      payload.growth_type = formGrowthType
      payload.growth_rate = formGrowthRate ? parseFloat(formGrowthRate) : null
      payload.growth_frequency = formGrowthFrequency
      payload.growth_start_date = formGrowthStartDate || null
    }

    if (isMarket) {
      payload.ticker = (selectedQuote?.symbol || formTickerQuery || '').toUpperCase()
      payload.ticker_exchange = selectedQuote?.exchange ?? null
      payload.units = formUnits ? parseFloat(formUnits) : null
      // Opening buy price per unit (defaults to the live quote on the server
      // when omitted). Only meaningful on create.
      if (!editingAsset) {
        payload.unit_price = formUnitPrice ? parseFloat(formUnitPrice) : null
      }
    }


    if (!editingAsset && formCurrentValue) {
      payload.current_value = parseFloat(formCurrentValue)
    }

    return payload
  }

  function hasGrowthParamsChanged(): boolean {
    if (!editingAsset || editingAsset.valuation_method !== 'growth_rule') return false
    return (
      formGrowthType !== (editingAsset.growth_type ?? 'percentage') ||
      formGrowthRate !== (editingAsset.growth_rate?.toString() ?? '') ||
      formGrowthFrequency !== (editingAsset.growth_frequency ?? 'monthly') ||
      formGrowthStartDate !== (editingAsset.growth_start_date ?? '') ||
      formPurchasePrice !== (editingAsset.purchase_price?.toString() ?? '') ||
      formPurchaseDate !== (editingAsset.purchase_date ?? '')
    )
  }

  function handleSave() {
    const payload = buildPayload()

    if (editingAsset) {
      // If growth params changed, ask confirmation before regenerating
      if (hasGrowthParamsChanged() && editingAsset.value_count > 0) {
        setPendingGrowthSave(payload)
        return
      }
      updateMutation.mutate({ id: editingAsset.id, ...payload } as Partial<Asset> & { id: string })
    } else {
      createMutation.mutate(payload as Parameters<typeof assets.create>[0])
    }
  }

  function confirmRegenerateGrowth() {
    if (!editingAsset || !pendingGrowthSave) return
    updateMutation.mutate(
      { id: editingAsset.id, ...pendingGrowthSave, _regenerateGrowth: true } as Partial<Asset> & { id: string },
    )
    setPendingGrowthSave(null)
  }

  return (
    <>
      {/* Create/Edit Dialog */}
      <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingAsset ? t('assets.editAsset') : t('assets.addAsset')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            {/* Name */}
            <div className="space-y-2">
              <Label htmlFor="asset-name">{t('assets.name')}</Label>
              <Input id="asset-name" value={formName} onChange={e => setFormName(e.target.value)} />
            </div>

            {/* Wallet picker — lets users place the asset in a specific
                wallet at creation time instead of dropping it in
                "Ungrouped" and moving it after (issue #138). */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="asset-wallet">{t('assets.wallet')}</Label>
                <button
                  type="button"
                  className="text-xs font-medium text-primary hover:underline disabled:opacity-50 disabled:no-underline"
                  disabled={createWalletPending}
                  onClick={onRequestCreateWallet}
                >
                  + {t('assets.newWallet')}
                </button>
              </div>
              <Select value={formGroupId || '__none__'} onValueChange={v => setFormGroupId(v === '__none__' ? '' : v)}>
                <SelectTrigger id="asset-wallet" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">{t('assets.noWallet')}</SelectItem>
                  {sortedWallets.map(w => (
                    <SelectItem key={w.id} value={w.id}>{w.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Type + Currency */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="asset-type">{t('assets.type')}</Label>
                <Select value={formType} onValueChange={setFormType}>
                  <SelectTrigger id="asset-type" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ASSET_TYPES.map(at => (
                      <SelectItem key={at} value={at}>
                        {t(assetTypeI18nKey(at))}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="asset-currency">{t('assets.currency')}</Label>
                <Select value={formCurrency} disabled={formMethod === 'market_price'} onValueChange={setFormCurrency}>
                  <SelectTrigger id="asset-currency" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(supportedCurrencies ?? [{ code: userCurrency, symbol: userCurrency, name: userCurrency, flag: '' }]).map((c) => (
                      <SelectItem key={c.code} value={c.code}>{c.flag} {c.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Valuation Method — locked on edit */}
            <div className="space-y-2">
              <Label>{t('assets.valuationMethod')}</Label>
              <div className="grid gap-2 grid-cols-3">
                {VALUATION_METHODS.map(m => (
                  <button
                    key={m}
                    type="button"
                    disabled={!!editingAsset}
                    className={`px-3 py-2.5 rounded-lg text-sm font-medium border transition-all ${
                      formMethod === m
                        ? 'border-primary bg-primary/10 text-primary shadow-sm'
                        : 'border-border text-muted-foreground hover:border-primary/50 hover:bg-muted/50'
                    } ${editingAsset ? 'opacity-50 cursor-not-allowed' : ''}`}
                    onClick={() => !editingAsset && setFormMethod(m)}
                  >
                    {m === 'market_price'
                      ? t('assets.marketPrice')
                      : m === 'growth_rule'
                        ? t('assets.growthRule')
                        : t('assets.manual')}
                  </button>
                ))}
              </div>
            </div>

            {/* Market Price (yfinance) — ticker search + quantity */}
            {formMethod === 'market_price' && (
              <div className="space-y-3 p-3.5 rounded-xl border border-primary/20 bg-primary/5">
                <div className="space-y-2">
                  <Label htmlFor="asset-ticker">{t('assets.ticker')}</Label>
                  <div className="relative">
                    <Input
                      id="asset-ticker"
                      placeholder={t('assets.tickerPlaceholder')}
                      value={formTickerQuery}
                      disabled={!!editingAsset}
                      onChange={e => {
                        pickedSymbolRef.current = null
                        setFormTickerQuery(e.target.value)
                        // Clear the quote so we don't keep the old preview
                        // while the user is editing the symbol — prevents
                        // a stale price from being saved accidentally.
                        if (selectedQuote && e.target.value.toUpperCase() !== selectedQuote.symbol) {
                          setSelectedQuote(null)
                        }
                      }}
                    />
                    {tickerMatches.length > 0 && !editingAsset && (
                      <div className="absolute z-20 mt-1 w-full max-h-60 overflow-y-auto rounded-lg border border-border bg-popover shadow-lg">
                        {tickerMatches.map(match => {
                          // Tesouro bonds carry an internal TD:* symbol — show
                          // the readable name instead of the hash for those.
                          const isBond = match.symbol.startsWith('TD:')
                          return (
                          <button
                            key={`${match.symbol}-${match.exchange ?? ''}`}
                            type="button"
                            onClick={() => pickTickerMatch(match)}
                            className="flex flex-col w-full text-left px-3 py-2 hover:bg-muted transition-colors"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-semibold text-sm truncate">{isBond ? (match.name ?? match.symbol) : match.symbol}</span>
                              {match.exchange && (
                                <span className="text-xs text-muted-foreground shrink-0">{match.exchange}</span>
                              )}
                            </div>
                            {match.name && !isBond && (
                              <span className="text-xs text-muted-foreground truncate">{match.name}</span>
                            )}
                          </button>
                          )
                        })}
                      </div>
                    )}
                    {tickerSearchLoading && (
                      <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground pointer-events-none">
                        {t('common.loading')}
                      </span>
                    )}
                  </div>
                </div>

                {selectedQuote && (
                  <div className="rounded-lg border border-border bg-card p-3 text-sm">
                    <div className="flex items-center justify-between">
                      <div className="flex flex-col min-w-0">
                        <span className="font-semibold truncate">{selectedQuote.symbol.startsWith('TD:') ? (selectedQuote.name ?? selectedQuote.symbol) : selectedQuote.symbol}</span>
                        {selectedQuote.name && !selectedQuote.symbol.startsWith('TD:') && (
                          <span className="text-xs text-muted-foreground truncate">{selectedQuote.name}</span>
                        )}
                        {/* Staleness hint — only meaningful when editing an
                            existing asset (last_price_at is set). Hidden
                            during create because the quote is inline-live. */}
                        {editingAsset?.last_price_at && (
                          <span className="text-[10px] text-muted-foreground mt-0.5">
                            {t('assets.lastUpdated', { when: formatRelativeTime(editingAsset.last_price_at, dateLocale) })}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <div className="text-right">
                          <div className="text-base font-bold tabular-nums">
                            {formatCurrency(selectedQuote.price, selectedQuote.currency, locale)}
                          </div>
                          {selectedQuote.exchange && (
                            <div className="text-[10px] text-muted-foreground uppercase tracking-wide">
                              {selectedQuote.exchange}
                            </div>
                          )}
                        </div>
                        {/* Manual refresh — only on edit. Daily cron handles
                            the rest; this button is the escape hatch when a
                            user wants a fresh quote right now. */}
                        {editingAsset && (
                          <button
                            type="button"
                            onClick={() => refreshPriceMutation.mutate(editingAsset.id)}
                            disabled={refreshPriceMutation.isPending}
                            title={t('assets.refreshPrice')}
                            className="p-1.5 rounded-md text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                          >
                            <RefreshCw
                              size={14}
                              className={refreshPriceMutation.isPending ? 'animate-spin' : ''}
                            />
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {!editingAsset ? (
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-2">
                      <Label htmlFor="asset-units">{t('assets.quantity')}</Label>
                      <Input
                        id="asset-units"
                        type="number"
                        step="any"
                        min="0"
                        value={formUnits}
                        onChange={e => setFormUnits(e.target.value)}
                        placeholder="10"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="asset-unit-price">{t('assets.unitPrice')}</Label>
                      <Input
                        id="asset-unit-price"
                        type="number"
                        step="any"
                        min="0"
                        value={formUnitPrice}
                        onChange={e => setFormUnitPrice(e.target.value)}
                        placeholder={selectedQuote ? String(selectedQuote.price) : '0.00'}
                      />
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <Label htmlFor="asset-units">{t('assets.quantity')}</Label>
                    <Input id="asset-units" type="number" step="any" min="0" value={formUnits} onChange={e => setFormUnits(e.target.value)} placeholder="10" />
                  </div>
                )}

                {/* Buy total — same qty × unit price model as the ledger, so
                    the value matches the Add-transaction dialog exactly. */}
                {!editingAsset && formUnits && parseFloat(formUnits) > 0 && (selectedQuote || formUnitPrice) && (
                  <div className="flex items-center justify-between p-3 rounded-lg border border-primary/30 bg-primary/10">
                    <span className="text-xs font-medium text-primary/80">
                      {t('assets.txTotal')}
                    </span>
                    <span className="text-lg font-bold tabular-nums text-primary">
                      {formatCurrency(
                        (parseFloat(formUnitPrice) || selectedQuote?.price || 0) * parseFloat(formUnits),
                        selectedQuote?.currency || formCurrency,
                        locale,
                      )}
                    </span>
                  </div>
                )}

                {quoteLoading && (
                  <div className="text-xs text-muted-foreground">{t('common.loading')}</div>
                )}
              </div>
            )}


            {/* Growth Rule Settings */}
            {formMethod === 'growth_rule' && (
              <div className="space-y-3 p-3.5 rounded-xl border border-primary/20 bg-primary/5">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="asset-growth-type">{t('assets.growthType')}</Label>
                    <Select value={formGrowthType} onValueChange={setFormGrowthType}>
                      <SelectTrigger id="asset-growth-type" className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {GROWTH_TYPES.map(gt => (
                          <SelectItem key={gt} value={gt}>{t(`assets.${gt}`)}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="asset-growth-rate">{t('assets.growthRate')}</Label>
                    <div className="relative">
                      <Input id="asset-growth-rate" type="number" step="any" value={formGrowthRate} onChange={e => setFormGrowthRate(e.target.value)} className={formGrowthType === 'percentage' ? 'pr-8' : ''} />
                      {formGrowthType === 'percentage' && (
                        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground pointer-events-none">%</span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="asset-growth-frequency">{t('assets.growthFrequency')}</Label>
                    <Select value={formGrowthFrequency} onValueChange={setFormGrowthFrequency}>
                      <SelectTrigger id="asset-growth-frequency" className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {GROWTH_FREQUENCIES.map(gf => (
                          <SelectItem key={gf} value={gf}>{t(`assets.${gf}`)}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="asset-growth-start-date">{t('assets.growthStartDate')}</Label>
                    <DatePickerInput id="asset-growth-start-date" value={formGrowthStartDate} onChange={setFormGrowthStartDate} />
                  </div>
                </div>
              </div>
            )}

            {/* Purchase Info. For tickers the cost comes from the unit-price
                buy above, so we only ask for the purchase (buy) date here and
                hide the total-price field. Manual assets keep both. */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="asset-purchase-date">{t('assets.purchaseDate')}</Label>
                <DatePickerInput id="asset-purchase-date" value={formPurchaseDate} onChange={setFormPurchaseDate} />
              </div>
              {formMethod !== 'market_price' && (
                <div className="space-y-2">
                  <Label htmlFor="asset-purchase-price">{t('assets.purchasePrice')}</Label>
                  <Input id="asset-purchase-price" type="number" step="0.01" value={formPurchasePrice} onChange={e => setFormPurchasePrice(e.target.value)} />
                </div>
              )}
            </div>

            {/* Sell Info — manual assets only. Tickers record sells through the
                buy/sell ledger, not the create form. */}
            {formMethod !== 'market_price' && (
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="asset-sell-date">{t('assets.sellDate')}</Label>
                  <DatePickerInput id="asset-sell-date" value={formSellDate} onChange={setFormSellDate} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="asset-sell-price">{t('assets.sellPrice')}</Label>
                  <Input id="asset-sell-price" type="number" step="0.01" value={formSellPrice} onChange={e => setFormSellPrice(e.target.value)} />
                </div>
              </div>
            )}

            {/* Current Value — manual only */}
            {!editingAsset && formMethod === 'manual' && (
              <div className="space-y-2">
                <Label htmlFor="asset-current-value">{t('assets.currentValue')}</Label>
                <Input
                  id="asset-current-value"
                  type="number"
                  step="any"
                  value={formCurrentValue}
                  onChange={e => setFormCurrentValue(e.target.value)}
                />
              </div>
            )}

            {/* Projected Value — growth rule preview */}
            {formMethod === 'growth_rule' && projectedGrowthValue != null && (() => {
              const base = parseFloat(formPurchasePrice) || 0
              const isLoss = projectedGrowthValue < base
              const diff = projectedGrowthValue - base
              return (
                <div className={`flex items-center justify-between p-3.5 rounded-xl border ${isLoss ? 'bg-rose-50 dark:bg-rose-950/30 border-rose-200 dark:border-rose-800' : 'bg-emerald-50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-800'}`}>
                  <div>
                    <span className="text-xs font-medium text-muted-foreground">{t('assets.currentValue')}</span>
                    {base > 0 && (
                      <p className={`text-[11px] tabular-nums font-medium mt-0.5 ${isLoss ? 'text-rose-500' : 'text-emerald-600'}`}>
                        {diff >= 0 ? '+' : ''}{formatCurrency(diff, formCurrency, locale)}
                      </p>
                    )}
                  </div>
                  <span className={`text-xl font-bold tabular-nums ${isLoss ? 'text-rose-600' : 'text-emerald-600'}`}>
                    {formatCurrency(projectedGrowthValue, formCurrency, locale)}
                  </span>
                </div>
              )
            })()}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button
              onClick={handleSave}
              disabled={
                !formName
                || createMutation.isPending
                || updateMutation.isPending
                // Market-price guard: must have a resolved ticker + quantity.
                || (formMethod === 'market_price'
                  && !editingAsset
                  && (!selectedQuote || !formUnits || parseFloat(formUnits) <= 0))
              }
            >
              {t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Regenerate Growth Confirmation */}
      <Dialog open={!!pendingGrowthSave} onOpenChange={() => setPendingGrowthSave(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('assets.confirmRegenerateTitle')}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">{t('assets.confirmRegenerate')}</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPendingGrowthSave(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              onClick={confirmRegenerateGrowth}
              disabled={updateMutation.isPending}
            >
              {t('assets.regenerate')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
})

export default function AssetsPage() {
  const { t } = useTranslation()
  const locale = useDisplayLocale()
  const dateLocale = useDateLocale()
  const { mask } = usePrivacyMode()
  const { user } = useAuth()
  const { canWrite } = useWorkspace()
  const userCurrency = user?.preferences?.currency_display ?? 'USD'
  const queryClient = useQueryClient()

  const { data: supportedCurrencies } = useQuery({
    queryKey: ['currencies'],
    queryFn: currenciesApi.list,
    staleTime: Infinity,
  })

  const [activeTab, setActiveTab] = useState<'holdings' | 'transactions'>('holdings')
  // Holding id for the lightweight "add transaction to this holding" dialog,
  // opened from the holdings table ("+ add buys") and the inline ledger.
  const [addTxAssetId, setAddTxAssetId] = useState<string | null>(null)
  // Drives the Create/Edit Asset dialog (a separate component — see
  // AssetDialog above — so typing in it doesn't re-render this whole page).
  const [assetDialogMode, setAssetDialogMode] = useState<AssetDialogMode>(null)
  const openAssetDialog = useCallback((asset: Asset) => setAssetDialogMode({ kind: 'edit', asset }), [])
  // Set when a wallet gets created from inside the asset dialog's
  // "+ New Wallet" link, so the new id can flow back down once created.
  const [pendingWalletAssignment, setPendingWalletAssignment] = useState<{ id: string; nonce: number } | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  // Stable prop for the memoized HoldingRow — functional update avoids
  // needing expandedId in the dep array.
  const onToggleExpand = useCallback((id: string) => {
    setExpandedId(prev => prev === id ? null : id)
  }, [])

  // Wallet (AssetGroup) dialog state
  const [walletDialogOpen, setWalletDialogOpen] = useState(false)
  const [editingWallet, setEditingWallet] = useState<AssetGroup | null>(null)
  const [walletFormName, setWalletFormName] = useState('')
  const [walletFormColor, setWalletFormColor] = useState('#0EA5E9')
  const [deletingWalletId, setDeletingWalletId] = useState<string | null>(null)
  // Collapsed wallet IDs — default is expanded (empty set), user can collapse manually
  const [collapsedWallets, setCollapsedWallets] = useState<Set<string>>(new Set())
  // Sold Assets section — collapsed by default so a portfolio with a long
  // sell history doesn't clutter the page; the count stays visible in the
  // header either way.
  const [showSoldAssets, setShowSoldAssets] = useState(false)
  // Asset being moved to a wallet (null = no picker open)
  const [movingAsset, setMovingAsset] = useState<Asset | null>(null)

  // Tracks "+ New wallet" clicked from inside the asset dialog so the
  // newly-created wallet auto-fills the picker on success (see
  // pendingWalletAssignment above, which carries the new id back down).
  const pendingAssignWalletToFormRef = useRef(false)

  const { data: rawAssetsList, isLoading, isError: assetsLoadError } = useQuery({
    queryKey: ['assets'],
    queryFn: () => assets.list(false),
  })

  // Active Collection filter (issue #105): when a collection is active, scope
  // the Assets page to the assets in its wallets (asset_groups). A collection
  // with no wallets → no assets shown. "All accounts" (null) → show everything.
  const { activeWalletIds } = useCollectionFilter()
  const assetsList = useMemo(() => {
    if (!activeWalletIds) return rawAssetsList
    const allowed = new Set(activeWalletIds)
    return (rawAssetsList ?? []).filter((a) => a.group_id && allowed.has(a.group_id))
  }, [rawAssetsList, activeWalletIds])

  const { data: rawPortfolioData, isLoading: portfolioLoading } = useQuery({
    queryKey: ['portfolio-trend'],
    queryFn: () => assets.portfolioTrend(),
  })
  // Clicking a wallet in the holdings list scopes the chart above to just
  // that wallet ("drill in"); clicking the same wallet again clears it.
  const [chartFocusWalletId, setChartFocusWalletId] = useState<string | null>(null)
  const onWalletClick = useCallback((id: string) => {
    setChartFocusWalletId(prev => prev === id ? null : id)
  }, [])

  // Scope the portfolio chart + total to the active collection's wallets
  // and/or the clicked wallet. Trend rows are keyed by asset id, so we keep
  // only the in-scope asset columns and recompute each row's `_total`.
  const portfolioData = useMemo(() => {
    if (!activeWalletIds && !chartFocusWalletId) return rawPortfolioData
    if (!rawPortfolioData) return rawPortfolioData
    const allowed = activeWalletIds ? new Set(activeWalletIds) : null
    const keptAssets = rawPortfolioData.assets.filter((a) => {
      if (!a.group_id) return false
      if (chartFocusWalletId && a.group_id !== chartFocusWalletId) return false
      if (allowed && !allowed.has(a.group_id)) return false
      return true
    })
    const keptIds = new Set(keptAssets.map((a) => a.id))
    const trend = rawPortfolioData.trend.map((row) => {
      const next: Record<string, unknown> = { date: (row as { date: unknown }).date }
      let total = 0
      for (const [k, v] of Object.entries(row)) {
        if (k === 'date' || k === '_total') continue
        if (keptIds.has(k)) {
          next[k] = v
          total += Number(v) || 0
        }
      }
      next._total = total
      return next
    })
    const lastTotal = trend.length ? Number((trend[trend.length - 1] as { _total?: number })._total) || 0 : 0
    return { ...rawPortfolioData, assets: keptAssets, trend, total: lastTotal }
  }, [rawPortfolioData, activeWalletIds, chartFocusWalletId])

  // Memoized so `assetsByGroup` below (which depends on activeAssets) can
  // actually skip recomputing across unrelated re-renders — a plain
  // .filter() here would hand it a new array reference every render and
  // silently defeat its useMemo cache.
  const activeAssets = useMemo(
    () => assetsList?.filter(a => !a.sell_date && !a.is_archived) ?? [],
    [assetsList],
  )
  const soldAssets = useMemo(
    () => assetsList?.filter(a => a.sell_date) ?? [],
    [assetsList],
  )

  // Total portfolio return (today), in the user's primary currency. Derives
  // each asset's invested amount from current_value_primary - gain_loss_primary
  // rather than needing a separate "invested_primary" field — those two are
  // already stamped by the API (assets.py list_assets) for any asset with a
  // known cost basis, same-currency assets falling back to their native
  // amounts since primary equals native there.
  const { totalInvestedPrimary, totalGainPrimary } = useMemo(() => {
    let invested = 0
    let gain = 0
    for (const a of activeAssets) {
      if (a.purchase_price == null) continue
      const g = a.gain_loss_primary ?? a.gain_loss ?? 0
      const cv = a.current_value_primary ?? a.current_value ?? 0
      invested += cv - g
      gain += g
    }
    return { totalInvestedPrimary: invested, totalGainPrimary: gain }
  }, [activeAssets])
  const portfolioReturnPct = totalInvestedPrimary > 0 ? (totalGainPrimary / totalInvestedPrimary) * 100 : null

  // Publish a snapshot of what's on the Assets page so the global chat
  // (⌘J) can answer "what does this chart mean / what are these
  // wallets?" without needing the user to spell it out.
  // Sold/archived assets are excluded here — their `current_value` is a
  // stale snapshot from before the sale, not part of the live portfolio.
  const totalValue = activeAssets.reduce(
    (acc: number, a: { current_value?: number | null }) => acc + Number(a.current_value || 0),
    0,
  )
  // Portfolio total in the user's primary currency — denominator for the
  // "% da carteira" column in the holdings table.
  const portfolioTotalPrimary = activeAssets.reduce(
    (acc, a) => acc + Number(a.current_value_primary ?? a.current_value ?? 0),
    0,
  )
  const byType: Record<string, number> = {}
  for (const a of activeAssets as Array<{ type?: string; current_value?: number | null }>) {
    if (!a.type) continue
    byType[a.type] = (byType[a.type] || 0) + Number(a.current_value || 0)
  }
  const portfolioTotal = (portfolioData as { total?: number } | undefined)?.total
  const assetsCtxKey = `${assetsList?.length ?? 0}:${totalValue.toFixed(2)}:${portfolioTotal ?? ''}`
  useRegisterPageChatContext(
    {
      path: '/assets',
      label: 'Assets',
      summary:
        `Portfolio overview page. ${assetsList?.length ?? 0} assets totaling ` +
        `~${totalValue.toLocaleString(locale, { style: 'currency', currency: userCurrency })} ` +
        `(by current_value). The portfolio chart shows value over time grouped by wallet or asset.`,
      totals_by_type: byType,
      asset_count: assetsList?.length ?? 0,
      total_value: Number(totalValue.toFixed(2)),
      hint: 'For exact per-asset numbers, use the get_net_worth or list_assets tools.',
    },
    assetsCtxKey,
  )

  // `refetchQueries` (vs. `invalidateQueries`) forces an immediate refetch
  // regardless of stale-state heuristics. Our global staleTime of 5 min
  // combined with the dialog-close re-render was sometimes leaving the
  // asset list showing pre-edit data until the user manually reloaded.
  // Wrapped in useCallback so it's a stable prop for the memoized HoldingRow.
  const refetchAssetViews = useCallback(() => {
    queryClient.refetchQueries({ queryKey: ['assets'] })
    queryClient.refetchQueries({ queryKey: ['portfolio-trend'] })
    queryClient.refetchQueries({ queryKey: ['dashboard'] })
  }, [queryClient])

  const deleteMutation = useMutation({
    mutationFn: (id: string) => assets.delete(id),
    onSuccess: () => {
      refetchAssetViews()
      setDeletingId(null)
      if (expandedId === deletingId) setExpandedId(null)
      toast.success(t('assets.deleted'))
    },
    onError: (e) => toast.error(assetErrorMessage(e, t('common.error'))),
  })

  const { data: rawWalletsList } = useQuery({
    queryKey: ['asset-groups'],
    queryFn: () => assetGroups.list(),
  })
  const walletsList = useMemo(() => {
    if (!activeWalletIds) return rawWalletsList
    const allowed = new Set(activeWalletIds)
    return (rawWalletsList ?? []).filter((w) => allowed.has(w.id))
  }, [rawWalletsList, activeWalletIds])

  const createWalletMutation = useMutation({
    mutationFn: (data: { name: string; color: string }) =>
      assetGroups.create({ name: data.name, color: data.color, icon: 'wallet' }),
    onSuccess: (created) => {
      queryClient.refetchQueries({ queryKey: ['asset-groups'] })
      setWalletDialogOpen(false)
      setEditingWallet(null)
      if (pendingAssignWalletToFormRef.current) {
        setPendingWalletAssignment({ id: created.id, nonce: Date.now() })
        pendingAssignWalletToFormRef.current = false
      }
      toast.success(t('assets.walletCreated'))
    },
    onError: (e) => toast.error(assetErrorMessage(e, t('common.error'))),
  })

  const updateWalletMutation = useMutation({
    mutationFn: ({ id, ...data }: { id: string; name: string; color: string }) =>
      assetGroups.update(id, { name: data.name, color: data.color }),
    onSuccess: () => {
      queryClient.refetchQueries({ queryKey: ['asset-groups'] })
      setWalletDialogOpen(false)
      setEditingWallet(null)
      toast.success(t('assets.walletUpdated'))
    },
    onError: (e) => toast.error(assetErrorMessage(e, t('common.error'))),
  })

  const deleteWalletMutation = useMutation({
    mutationFn: (id: string) => assetGroups.delete(id),
    onSuccess: () => {
      // Deleting a wallet un-groups its assets (backend sets group_id=null).
      queryClient.refetchQueries({ queryKey: ['asset-groups'] })
      queryClient.refetchQueries({ queryKey: ['assets'] })
      setDeletingWalletId(null)
      toast.success(t('assets.walletDeleted'))
    },
    onError: (e) => toast.error(assetErrorMessage(e, t('common.error'))),
  })

  const moveAssetMutation = useMutation({
    mutationFn: ({ id, groupId }: { id: string; groupId: string | null }) =>
      assets.update(id, { group_id: groupId } as Partial<Asset>),
    onSuccess: () => {
      queryClient.refetchQueries({ queryKey: ['assets'] })
      queryClient.refetchQueries({ queryKey: ['asset-groups'] })
      setMovingAsset(null)
      toast.success(t('assets.moved'))
    },
    onError: (e) => toast.error(assetErrorMessage(e, t('common.error'))),
  })

  // Consolidated holdings table (issue #235). One row per holding (ticker),
  // Investidor10/Status Invest style: Ativo · Quant. · Preço Médio ·
  // Preço Atual · Rentabilidade · Saldo · % da carteira. Market-priced rows
  // are fully populated; holdings with no recorded cost show "—" for the
  // cost-based columns and offer a one-tap way to add their buys.
  // Column header for a holdings section — same grid template as the rows.
  function renderHoldingsHeader() {
    return (
      <div
        className="grid items-center gap-2 px-3 py-2 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider border-b border-border"
        style={{ gridTemplateColumns: HOLDINGS_GRID }}
      >
        <div>{t('assets.colAsset')}</div>
        <div className="text-right">{t('assets.colQuantity')}</div>
        <div className="text-right">{t('assets.colAvgPrice')}</div>
        <div className="text-right">{t('assets.colCurrentPrice')}</div>
        <div className="text-right">{t('assets.colReturn')}</div>
        <div className="text-right">{t('assets.colBalance')}</div>
        <div className="text-right">{t('assets.colPortfolioPct')}</div>
        <div />
      </div>
    )
  }

  // Wrap a set of holding rows in a horizontally-scrollable table shell so the
  // columns stay aligned (and usable on narrow screens).
  function renderHoldingsTable(rows: Asset[]) {
    return (
      <div className="rounded-xl border border-border bg-card shadow-sm overflow-x-auto">
        <div className="min-w-[720px]">
          {renderHoldingsHeader()}
          {rows.map(asset => (
            <HoldingRow
              key={asset.id}
              asset={asset}
              portfolioTotalPrimary={portfolioTotalPrimary}
              userCurrency={userCurrency}
              locale={locale}
              dateLocale={dateLocale}
              mask={mask}
              canWrite={canWrite}
              isExpanded={expandedId === asset.id}
              onToggleExpand={onToggleExpand}
              onAddTransaction={setAddTxAssetId}
              onMoveAsset={setMovingAsset}
              onEdit={openAssetDialog}
              onDelete={setDeletingId}
              onChanged={refetchAssetViews}
            />
          ))}
        </div>
      </div>
    )
  }

  // Bucket active assets by group_id so each wallet renders with its
  // total and collapse toggle. Un-grouped actives go under a synthetic
  // bucket rendered at the end.
  const assetsByGroup = useMemo(() => {
    const map = new Map<string | null, Asset[]>()
    for (const a of activeAssets) {
      const key = a.group_id ?? null
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(a)
    }
    return map
  }, [activeAssets])

  const sortedWallets = useMemo(() => {
    return (walletsList ?? []).slice().sort((a, b) => a.position - b.position || a.name.localeCompare(b.name))
  }, [walletsList])

  const ungroupedAssets = assetsByGroup.get(null) ?? []

  function toggleWalletCollapse(id: string) {
    setCollapsedWallets(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function openCreateWallet() {
    setEditingWallet(null)
    setWalletFormName('')
    setWalletFormColor('#0EA5E9')
    setWalletDialogOpen(true)
  }

  function openEditWallet(wallet: AssetGroup) {
    setEditingWallet(wallet)
    setWalletFormName(wallet.name)
    setWalletFormColor(wallet.color)
    setWalletDialogOpen(true)
  }

  function handleSaveWallet() {
    const name = walletFormName.trim()
    if (!name) return
    if (editingWallet) {
      updateWalletMutation.mutate({ id: editingWallet.id, name, color: walletFormColor })
    } else {
      createWalletMutation.mutate({ name, color: walletFormColor })
    }
  }

  function renderWalletSection(wallet: AssetGroup, walletAssets: Asset[]) {
    const isCollapsed = collapsedWallets.has(wallet.id)
    const isFocused = chartFocusWalletId === wallet.id
    const isSynced = wallet.source !== 'manual'
    // Sum in wallet's reported current_value (already computed by backend).
    // Fall back to the wallet's own rollup only when there are no assets to
    // sum locally — a genuine zero total from `reduce` must not be treated
    // as falsy and overridden by a possibly-stale backend value.
    const perAssetTotal = walletAssets.reduce((s, a) => s + (a.current_value_primary ?? a.current_value ?? 0), 0)
    const total = walletAssets.length > 0 ? perAssetTotal : (wallet.current_value_primary ?? wallet.current_value ?? 0)

    // Only show the institution as a subtitle when it's actually
    // additional information — if the user hasn't renamed the wallet,
    // name and institution are identical and the subtitle would be
    // redundant noise.
    const showInstitutionSubtitle =
      !!wallet.institution_name && wallet.institution_name !== wallet.name

    return (
      <div key={wallet.id} className="space-y-2">
        <div className={`flex items-center gap-3 px-1 rounded-lg ${isFocused ? 'ring-1 ring-primary/40 bg-primary/5' : ''}`}>
          <button
            onClick={() => toggleWalletCollapse(wallet.id)}
            className="flex items-center gap-1 shrink-0"
            title={isCollapsed ? t('common.expand') : t('common.collapse')}
          >
            {isCollapsed ? (
              <ChevronRight size={14} className="text-muted-foreground" />
            ) : (
              <ChevronDown size={14} className="text-muted-foreground" />
            )}
          </button>
          <button
            onClick={() => onWalletClick(wallet.id)}
            title={t('assets.focusWalletChart')}
            className="flex items-center gap-2 flex-1 min-w-0 group"
          >
            <div
              className="w-6 h-6 rounded-md flex items-center justify-center shrink-0"
              style={{ backgroundColor: `${wallet.color}20` }}
            >
              <Wallet size={13} style={{ color: wallet.color }} />
            </div>
            <div className="flex flex-col items-start min-w-0 flex-1">
              <div className="flex items-center gap-2 min-w-0 w-full">
                <span className="text-sm font-semibold text-foreground truncate">{wallet.name}</span>
                <span className="text-xs text-muted-foreground shrink-0">
                  · {walletAssets.length} {t('assets.itemsCount')}
                </span>
              </div>
              {showInstitutionSubtitle && (
                <span className="text-[11px] text-muted-foreground truncate flex items-center gap-1">
                  <RefreshCw size={9} />
                  {t('assets.syncedFrom', { source: wallet.institution_name })}
                </span>
              )}
            </div>
          </button>
          <span className="text-sm font-bold tabular-nums text-foreground shrink-0">
            {mask(formatCurrency(total, userCurrency, locale))}
          </span>
          {canWrite && (
            <>
              <button
                onClick={() => openEditWallet(wallet)}
                className="p-1 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                title={t('assets.editWallet')}
              >
                <Pencil size={12} />
              </button>
              {!isSynced && (
                <button
                  onClick={() => setDeletingWalletId(wallet.id)}
                  className="p-1 rounded-lg text-muted-foreground hover:text-rose-600 hover:bg-rose-50 transition-colors"
                  title={t('assets.deleteWallet')}
                >
                  <Trash2 size={12} />
                </button>
              )}
            </>
          )}
        </div>
        {!isCollapsed && walletAssets.length > 0 && (
          <div className="pl-4">
            {renderHoldingsTable(walletAssets)}
          </div>
        )}
        {!isCollapsed && walletAssets.length === 0 && (
          <div className="pl-4 py-3 text-xs text-muted-foreground italic">
            {t('assets.emptyWallet')}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        section={t('assets.title')}
        title={t('assets.title')}
        action={
          canWrite ? (
            <div className="flex items-center gap-2">
              <Button onClick={openCreateWallet} variant="outline" className="gap-1.5">
                <Wallet size={16} />
                {t('assets.newWallet')}
              </Button>
              <Button onClick={() => setAssetDialogMode({ kind: 'create' })} className="gap-1.5">
                <Plus size={16} />
                {t('assets.addAsset')}
              </Button>
            </div>
          ) : undefined
        }
      />

      {/* Holdings (consolidated by ticker) vs. the buy/sell ledger (#235) */}
      <div className="inline-flex items-center rounded-lg border border-border p-0.5 bg-muted/40">
        <button
          onClick={() => setActiveTab('holdings')}
          className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${activeTab === 'holdings' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
        >
          {t('assets.tabHoldings')}
        </button>
        <button
          onClick={() => setActiveTab('transactions')}
          className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${activeTab === 'transactions' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
        >
          {t('assets.tabTransactions')}
        </button>
      </div>

      {activeTab === 'transactions' ? (
        <AssetTransactionsTab
          holdings={assetsList ?? []}
          wallets={sortedWallets}
          locale={locale}
          dateLocale={dateLocale}
          mask={mask}
          canWrite={canWrite}
          onChanged={refetchAssetViews}
        />
      ) : (
      <>
      {/* Portfolio Chart */}
      {chartFocusWalletId && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>{t('assets.chartFilteredByWallet', { wallet: sortedWallets.find(w => w.id === chartFocusWalletId)?.name ?? '' })}</span>
          <button
            type="button"
            onClick={() => setChartFocusWalletId(null)}
            className="font-medium text-primary hover:underline"
          >
            {t('assets.clearChartFilter')}
          </button>
        </div>
      )}
      {portfolioLoading ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : (
        portfolioData && portfolioData.trend.length > 0 && (
          <PortfolioChart
            data={portfolioData}
            wallets={sortedWallets}
            currency={userCurrency}
            locale={locale}
            dateLocale={dateLocale}
            mask={mask}
            focusedWalletId={chartFocusWalletId}
            onWalletClick={onWalletClick}
            returnPct={portfolioReturnPct}
            returnAmount={totalGainPrimary}
          />
        )
      )}

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-xl" />)}
        </div>
      ) : assetsLoadError ? (
        // Distinct from the "no assets" empty state below — a failed fetch
        // must never render as "you have zero assets" on a finance page.
        <div className="text-center py-16">
          <AlertTriangle className="mx-auto h-12 w-12 text-amber-500/70 mb-3" />
          <p className="text-muted-foreground">{t('assets.loadError')}</p>
        </div>
      ) : (
        <div className="space-y-6">
          {/* Wallets (active assets grouped) */}
          {(sortedWallets.length > 0 || ungroupedAssets.length > 0) && (
            <div className="space-y-4">
              {sortedWallets.map(w => renderWalletSection(w, assetsByGroup.get(w.id) ?? []))}

              {ungroupedAssets.length > 0 && (
                <div className="space-y-2">
                  <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-1">
                    {sortedWallets.length > 0 ? t('assets.ungrouped') : t('assets.activeAssets')}
                  </h3>
                  {renderHoldingsTable(ungroupedAssets)}
                </div>
              )}
            </div>
          )}

          {/* Sold Assets — collapsed by default (see showSoldAssets) */}
          {soldAssets.length > 0 && (
            <div className="space-y-2">
              <button
                type="button"
                onClick={() => setShowSoldAssets(v => !v)}
                className="flex items-center gap-1.5 px-1 text-xs font-semibold text-muted-foreground uppercase tracking-wider hover:text-foreground transition-colors"
              >
                {showSoldAssets ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                {t('assets.soldAssets')}
                <span className="normal-case font-normal">· {soldAssets.length} {t('assets.itemsCount')}</span>
              </button>
              {showSoldAssets && renderHoldingsTable(soldAssets)}
            </div>
          )}

          {/* Only the true first-run empty state: no wallets to show their own
              per-wallet empty message, no ungrouped assets, no sold assets.
              When wallets exist (even empty ones), their own "empty" line
              below each header is sufficient — showing this panel too would
              be redundant. */}
          {sortedWallets.length === 0 && activeAssets.length === 0 && soldAssets.length === 0 && (
            <div className="text-center py-16">
              <Package className="mx-auto h-12 w-12 text-muted-foreground/40 mb-3" />
              <p className="text-muted-foreground">{t('assets.noAssets')}</p>
            </div>
          )}
        </div>
      )}
      </>
      )}

      <AssetDialog
        mode={assetDialogMode}
        onClose={() => setAssetDialogMode(null)}
        sortedWallets={sortedWallets}
        supportedCurrencies={supportedCurrencies}
        userCurrency={userCurrency}
        locale={locale}
        dateLocale={dateLocale}
        onRequestCreateWallet={() => {
          pendingAssignWalletToFormRef.current = true
          openCreateWallet()
        }}
        createWalletPending={createWalletMutation.isPending}
        pendingWalletAssignment={pendingWalletAssignment}
        onChanged={refetchAssetViews}
      />

      {/* Delete Confirmation */}
      <Dialog open={!!deletingId} onOpenChange={() => setDeletingId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('assets.confirmDeleteTitle')}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">{t('assets.confirmDelete')}</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeletingId(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => deletingId && deleteMutation.mutate(deletingId)}
              disabled={deleteMutation.isPending}
            >
              {t('common.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Wallet Create/Edit Dialog */}
      <Dialog open={walletDialogOpen} onOpenChange={setWalletDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingWallet ? t('assets.editWallet') : t('assets.newWallet')}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="wallet-name">{t('assets.walletName')}</Label>
              <Input
                id="wallet-name"
                value={walletFormName}
                onChange={e => setWalletFormName(e.target.value)}
                placeholder={t('assets.walletNamePlaceholder')}
                autoFocus
              />
              {editingWallet?.institution_name && editingWallet.source !== 'manual' && (
                <p className="text-[11px] text-muted-foreground flex items-center gap-1">
                  <RefreshCw size={10} />
                  {t('assets.syncedFromHint', { source: editingWallet.institution_name })}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="wallet-color">{t('assets.walletColor')}</Label>
              <Input
                id="wallet-color"
                type="color"
                value={walletFormColor}
                onChange={e => setWalletFormColor(e.target.value)}
                className="h-9 w-20 px-1 py-1"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setWalletDialogOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              onClick={handleSaveWallet}
              disabled={!walletFormName.trim() || createWalletMutation.isPending || updateWalletMutation.isPending}
            >
              {t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Wallet Confirmation */}
      <Dialog open={!!deletingWalletId} onOpenChange={() => setDeletingWalletId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('assets.confirmDeleteWalletTitle')}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">{t('assets.confirmDeleteWallet')}</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeletingWalletId(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => deletingWalletId && deleteWalletMutation.mutate(deletingWalletId)}
              disabled={deleteWalletMutation.isPending}
            >
              {t('common.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Move Asset to Wallet Picker */}
      <Dialog open={!!movingAsset} onOpenChange={() => setMovingAsset(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('assets.moveToWallet')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-1 max-h-80 overflow-y-auto">
            <button
              onClick={() => movingAsset && moveAssetMutation.mutate({ id: movingAsset.id, groupId: null })}
              disabled={!movingAsset?.group_id || moveAssetMutation.isPending}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-left"
            >
              <div className="w-6 h-6 rounded-md flex items-center justify-center bg-muted">
                <Package size={13} className="text-muted-foreground" />
              </div>
              <span className="text-sm text-foreground">{t('assets.noWallet')}</span>
            </button>
            {sortedWallets.map(w => (
              <button
                key={w.id}
                onClick={() => movingAsset && moveAssetMutation.mutate({ id: movingAsset.id, groupId: w.id })}
                disabled={movingAsset?.group_id === w.id || moveAssetMutation.isPending}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-left"
              >
                <div
                  className="w-6 h-6 rounded-md flex items-center justify-center"
                  style={{ backgroundColor: `${w.color}20` }}
                >
                  <Wallet size={13} style={{ color: w.color }} />
                </div>
                <span className="text-sm text-foreground flex-1 truncate">{w.name}</span>
                <span className="text-xs text-muted-foreground">{w.asset_count}</span>
              </button>
            ))}
            {sortedWallets.length === 0 && (
              <p className="text-xs text-muted-foreground italic px-3 py-2">
                {t('assets.noWalletsHint')}
              </p>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Add a buy/sell to an existing holding (from the holdings table /
          inline ledger). Brand-new tickers go through Add Asset / the
          Transactions tab. */}
      <AddHoldingTransactionDialog
        assetId={addTxAssetId}
        holding={(assetsList ?? []).find((a) => a.id === addTxAssetId) ?? null}
        locale={locale}
        onClose={() => setAddTxAssetId(null)}
        onChanged={refetchAssetViews}
      />
    </div>
  )
}

const PORTFOLIO_COLORS = ['#6366F1', '#F43F5E', '#F59E0B', '#10B981', '#8B5CF6', '#EC4899', '#06B6D4', '#84CC16']

// Memoized: without this, every keystroke in the Add Asset dialog (state
// lives on the parent AssetsPage) re-rendered this recharts tree too, even
// though its props (data/wallets are already useMemo'd upstream) hadn't
// changed. Props are all primitives/memoized values, so shallow-equal
// bailout is safe and effective.
const PortfolioChart = memo(function PortfolioChart({ data, wallets, currency, locale: loc, dateLocale: dateLoc, mask, focusedWalletId, onWalletClick, returnPct, returnAmount }: {
  data: { assets: { id: string; name: string; type: string; group_id: string | null }[]; trend: Record<string, unknown>[]; total: number }
  wallets: AssetGroup[]
  currency: string
  locale: string
  dateLocale: string
  mask: (v: string) => string
  // Clicking a wallet's legend entry scopes the chart to just that wallet
  // (only meaningful in "By Wallet" mode — each entry there is one wallet).
  focusedWalletId: string | null
  onWalletClick: (walletId: string) => void
  // Total unrealized gain/loss vs. cost basis, today, across all active
  // assets with a known purchase price — null when no asset has one.
  returnPct: number | null
  returnAmount: number
}) {
  const { t } = useTranslation()
  // Default to wallet mode: with many synced CDBs the asset view turns
  // into a cluttered rainbow legend that's hard to parse. Keep stacked as
  // the default drawing style, while letting users switch to true lines when
  // they need to compare each wallet/asset's own value instead of the running
  // cumulative total.
  const [mode, setMode] = useState<'wallet' | 'asset'>('wallet')
  const [drawMode, setDrawMode] = useState<'stacked' | 'lines'>('stacked')
  const [viewMode, setViewMode] = useState<'value' | 'return'>('value')
  const [period, setPeriod] = useState<'3M' | '6M' | '1Y' | 'ALL'>('ALL')
  const isStacked = drawMode === 'stacked'

  const formatCompact = (v: number) => {
    const abs = Math.abs(v)
    if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
    if (abs >= 1_000) return `${(v / 1_000).toFixed(abs >= 10_000 ? 0 : 1)}k`
    return v.toLocaleString(loc, { maximumFractionDigits: 0 })
  }

  // Zoom the chart to a trailing window ending at the last data point (not
  // "today") so a workspace with no recent activity doesn't look truncated.
  // The header Total/Return stat is intentionally NOT re-scoped by this —
  // it always reflects the live portfolio, only the chart below zooms.
  const periodTrend = useMemo(() => {
    if (period === 'ALL' || data.trend.length === 0) return data.trend
    const months = period === '3M' ? 3 : period === '6M' ? 6 : 12
    const lastDate = new Date((data.trend[data.trend.length - 1].date as string) + 'T00:00:00')
    const cutoff = new Date(lastDate)
    cutoff.setMonth(cutoff.getMonth() - months)
    const cutoffStr = cutoff.toISOString().slice(0, 10)
    return data.trend.filter(r => (r.date as string) >= cutoffStr)
  }, [data.trend, period])

  // Portfolio return % over time — (value - invested) / invested per date.
  // A single aggregate line (not broken out by wallet/asset): with
  // contributions arriving at different times, per-wallet "return" would mix
  // new capital with actual gains in a way that's more confusing than useful.
  const returnTrend = useMemo(() => {
    return periodTrend.map(row => {
      const total = Number(row._total) || 0
      const invested = Number(row._invested) || 0
      return {
        date: row.date as string,
        return_pct: invested > 0 ? ((total - invested) / invested) * 100 : null,
        total,
        invested,
      }
    })
  }, [periodTrend])

  // Compute the series list and rewrite trend rows based on the selected
  // mode. Wallet mode rolls all assets sharing a group_id into a single
  // series (using the wallet's own color); ungrouped assets keep their
  // individual lines so nothing disappears from the chart.
  const { series, displayTrend } = useMemo(() => {
    if (mode === 'asset') {
      const s = data.assets.map((a, i) => ({
        key: a.id,
        name: a.name,
        color: PORTFOLIO_COLORS[i % PORTFOLIO_COLORS.length],
        sourceAssetIds: [a.id],
      }))
      return { series: s, displayTrend: periodTrend }
    }

    const walletById = new Map<string, AssetGroup>()
    for (const w of wallets) walletById.set(w.id, w)

    const groupBuckets = new Map<string, string[]>()
    const ungroupedAssetIds: string[] = []
    for (const a of data.assets) {
      if (a.group_id) {
        if (!groupBuckets.has(a.group_id)) groupBuckets.set(a.group_id, [])
        groupBuckets.get(a.group_id)!.push(a.id)
      } else {
        ungroupedAssetIds.push(a.id)
      }
    }

    // Preserve wallet display order. Falls back to insertion order for
    // wallets that show up in the data but aren't in the wallets list
    // (e.g. race conditions between queries).
    const orderedGroupIds = [
      ...wallets.map(w => w.id).filter(id => groupBuckets.has(id)),
      ...Array.from(groupBuckets.keys()).filter(id => !walletById.has(id)),
    ]

    const s: { key: string; name: string; color: string; sourceAssetIds: string[] }[] = []
    let fallbackColorIdx = 0
    for (const gid of orderedGroupIds) {
      const wallet = walletById.get(gid)
      const assetIds = groupBuckets.get(gid)!
      s.push({
        key: `w_${gid}`,
        name: wallet?.name ?? t('assets.ungrouped'),
        color: wallet?.color ?? PORTFOLIO_COLORS[fallbackColorIdx++ % PORTFOLIO_COLORS.length],
        sourceAssetIds: assetIds,
      })
    }
    for (const aid of ungroupedAssetIds) {
      const asset = data.assets.find(a => a.id === aid)
      s.push({
        key: aid,
        name: asset?.name ?? aid,
        color: PORTFOLIO_COLORS[fallbackColorIdx++ % PORTFOLIO_COLORS.length],
        sourceAssetIds: [aid],
      })
    }

    const newTrend = periodTrend.map(row => {
      const newRow: Record<string, unknown> = { date: row.date, _total: row._total }
      for (const entry of s) {
        let sum = 0
        for (const aid of entry.sourceAssetIds) {
          sum += (row[aid] as number) ?? 0
        }
        newRow[entry.key] = sum
      }
      return newRow
    })

    return { series: s, displayTrend: newTrend }
  }, [mode, data, wallets, t, periodTrend])
  const sortedSeries = useMemo(() => {
    const lastRow = displayTrend[displayTrend.length - 1]
    if (!lastRow) return series
    return [...series].sort((a, b) => {
      const av = Math.abs((lastRow[a.key] as number) ?? 0)
      const bv = Math.abs((lastRow[b.key] as number) ?? 0)
      return bv - av || a.name.localeCompare(b.name)
    })
  }, [series, displayTrend])

  return (
    <div className="border border-border rounded-xl bg-card shadow-sm p-5">
      <div className="flex flex-col gap-3 mb-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-foreground">{t('assets.portfolioValue')}</h3>
          <div className="flex flex-wrap items-center gap-2">
            <div role="group" aria-label={t('assets.chartValueMode')} className="inline-flex items-center rounded-lg border border-border p-0.5 bg-muted/40">
              <button
                type="button"
                aria-pressed={viewMode === 'value'}
                onClick={() => setViewMode('value')}
                className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${viewMode === 'value' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
              >
                {t('assets.chartValue')}
              </button>
              <button
                type="button"
                aria-pressed={viewMode === 'return'}
                onClick={() => setViewMode('return')}
                className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${viewMode === 'return' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
              >
                {t('assets.chartReturn')}
              </button>
            </div>
            {viewMode === 'value' && (
              <>
                <div role="group" aria-label={t('assets.chartGroupMode')} className="inline-flex items-center rounded-lg border border-border p-0.5 bg-muted/40">
                  <button
                    type="button"
                    aria-pressed={mode === 'wallet'}
                    onClick={() => setMode('wallet')}
                    className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${mode === 'wallet' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
                  >
                    {t('assets.chartByWallet')}
                  </button>
                  <button
                    type="button"
                    aria-pressed={mode === 'asset'}
                    onClick={() => setMode('asset')}
                    className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${mode === 'asset' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
                  >
                    {t('assets.chartByAsset')}
                  </button>
                </div>
                <div role="group" aria-label={t('assets.chartDrawMode')} className="inline-flex items-center rounded-lg border border-border p-0.5 bg-muted/40">
                  <button
                    type="button"
                    aria-pressed={drawMode === 'stacked'}
                    onClick={() => setDrawMode('stacked')}
                    className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${drawMode === 'stacked' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
                  >
                    {t('assets.chartStacked')}
                  </button>
                  <button
                    type="button"
                    aria-pressed={drawMode === 'lines'}
                    onClick={() => setDrawMode('lines')}
                    className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${drawMode === 'lines' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
                  >
                    {t('assets.chartLines')}
                  </button>
                </div>
              </>
            )}
            <div role="group" aria-label={t('assets.chartPeriod')} className="inline-flex items-center rounded-lg border border-border p-0.5 bg-muted/40">
              {(['3M', '6M', '1Y', 'ALL'] as const).map(p => (
                <button
                  key={p}
                  type="button"
                  aria-pressed={period === p}
                  onClick={() => setPeriod(p)}
                  className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${period === p ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
                >
                  {p === 'ALL' ? t('assets.periodAll') : p}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="text-left sm:text-right">
          <span className="text-xs text-muted-foreground">{t('assets.total')}</span>
          <p className="text-lg font-bold tabular-nums text-foreground">
            {mask(formatCurrency(data.total, currency, loc))}
          </p>
          {returnPct != null && (
            <p className={`text-xs font-medium tabular-nums ${returnPct >= 0 ? 'text-emerald-600' : 'text-rose-500'}`}>
              {returnPct >= 0 ? '+' : ''}{returnPct.toFixed(1)}% ({mask(formatCurrency(returnAmount, currency, loc))})
            </p>
          )}
        </div>
      </div>
      {viewMode === 'value' ? (
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={displayTrend} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
            <defs>
              {isStacked && sortedSeries.map(s => (
                <linearGradient key={s.key} id={`portfolio-grad-${s.key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={s.color} stopOpacity={0.5} />
                  <stop offset="100%" stopColor={s.color} stopOpacity={0.1} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" strokeOpacity={0.5} />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v: string) => new Date(v + 'T00:00:00').toLocaleDateString(dateLoc, { month: 'short', year: '2-digit' })}
            />
            <YAxis
              tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
              axisLine={false}
              tickLine={false}
              width={56}
              tickFormatter={(v: number) => mask(formatCompact(v))}
            />
            <RechartsTooltip
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null
                const row = displayTrend.find(r => r.date === label)
                const dateTotal = row ? ((row._total as number) ?? 0) : 0
                const items = sortedSeries
                  .map(s => {
                    const val = row ? ((row[s.key] as number) ?? 0) : 0
                    return { key: s.key, name: s.name, value: val, color: s.color }
                  })
                  .filter(item => item.value !== 0)
                if (items.length === 0) return null
                return (
                  <div style={{ background: 'var(--card)', color: 'var(--foreground)', border: '1px solid var(--border)', borderRadius: '0.75rem', fontSize: '12px', boxShadow: '0 4px 12px rgba(0,0,0,0.08)', padding: '10px 12px' }}>
                    <p style={{ fontWeight: 600, marginBottom: 6 }}>
                      {new Date(label + 'T00:00:00').toLocaleDateString(dateLoc, { day: 'numeric', month: 'long', year: 'numeric' })}
                    </p>
                    {items.map(item => (
                      <div key={item.key} style={{ display: 'flex', justifyContent: 'space-between', gap: 16, marginBottom: 2 }}>
                        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: item.color, display: 'inline-block' }} />
                          {item.name}
                        </span>
                        <span style={{ fontWeight: 500, fontVariantNumeric: 'tabular-nums' }}>{mask(formatCurrency(item.value, currency, loc))}</span>
                      </div>
                    ))}
                    <div style={{ borderTop: '1px solid var(--border)', marginTop: 6, paddingTop: 6, display: 'flex', justifyContent: 'space-between', fontWeight: 700 }}>
                      <span>{t('assets.total')}</span>
                      <span style={{ fontVariantNumeric: 'tabular-nums' }}>{mask(formatCurrency(dateTotal, currency, loc))}</span>
                    </div>
                  </div>
                )
              }}
            />
            {/* Stacked mode shows cumulative bands; line mode plots each series' own value. */}
            {sortedSeries.map(s => (
              <Area
                key={s.key}
                type="monotone"
                dataKey={s.key}
                stackId={isStacked ? 'portfolio' : undefined}
                stroke={s.color}
                strokeWidth={isStacked ? 1 : 2}
                fill={isStacked ? `url(#portfolio-grad-${s.key})` : 'none'}
                dot={false}
                activeDot={{ r: 3, strokeWidth: 1.5, fill: 'var(--card)' }}
              />
            ))}
            {/* Hidden total for tooltip. Kept out of the chart in line mode so the
                Y axis scales to the largest single series instead of the portfolio
                total, which would otherwise squash every line against the baseline. */}
            <Area dataKey="_total" stroke="none" fill="none" dot={false} activeDot={false} hide={!isStacked} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      ) : (
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <RechartsLineChart data={returnTrend} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" strokeOpacity={0.5} />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v: string) => new Date(v + 'T00:00:00').toLocaleDateString(dateLoc, { month: 'short', year: '2-digit' })}
            />
            <YAxis
              tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
              axisLine={false}
              tickLine={false}
              width={48}
              tickFormatter={(v: number) => `${v.toFixed(0)}%`}
            />
            <ReferenceLine y={0} stroke="var(--border)" />
            <RechartsTooltip
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null
                const row = returnTrend.find(r => r.date === label)
                if (!row || row.return_pct == null) return null
                return (
                  <div style={{ background: 'var(--card)', color: 'var(--foreground)', border: '1px solid var(--border)', borderRadius: '0.75rem', fontSize: '12px', boxShadow: '0 4px 12px rgba(0,0,0,0.08)', padding: '10px 12px' }}>
                    <p style={{ fontWeight: 600, marginBottom: 6 }}>
                      {new Date(label + 'T00:00:00').toLocaleDateString(dateLoc, { day: 'numeric', month: 'long', year: 'numeric' })}
                    </p>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, marginBottom: 2 }}>
                      <span>{t('assets.chartReturn')}</span>
                      <span style={{ fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: row.return_pct >= 0 ? 'var(--chart-positive, #10b981)' : 'var(--chart-negative, #f43f5e)' }}>
                        {row.return_pct >= 0 ? '+' : ''}{row.return_pct.toFixed(1)}%
                      </span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16 }}>
                      <span>{t('assets.total')}</span>
                      <span style={{ fontVariantNumeric: 'tabular-nums' }}>{mask(formatCurrency(row.total, currency, loc))}</span>
                    </div>
                  </div>
                )
              }}
            />
            <Line
              type="monotone"
              dataKey="return_pct"
              stroke="var(--primary)"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 3, strokeWidth: 1.5, fill: 'var(--card)' }}
              connectNulls
            />
          </RechartsLineChart>
        </ResponsiveContainer>
      </div>
      )}
      {/* Legend — in wallet mode, each entry is clickable to scope the
          chart above to just that wallet (issue: "click a wallet in the
          legend and the graph shows only that wallet"). Only meaningful
          for the Value view — Return is a single aggregate line. */}
      {viewMode === 'value' && (
      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3 px-1">
        {sortedSeries.map(s => {
          const walletId = mode === 'wallet' && s.key.startsWith('w_') ? s.key.slice(2) : null
          const isFocused = walletId != null && walletId === focusedWalletId
          const content = (
            <>
              <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: s.color }} />
              <span className={`text-[11px] ${isFocused ? 'text-foreground font-medium' : 'text-muted-foreground'}`}>{s.name}</span>
            </>
          )
          return walletId ? (
            <button
              key={s.key}
              type="button"
              onClick={() => onWalletClick(walletId)}
              title={t('assets.focusWalletChart')}
              className={`flex items-center gap-1.5 rounded px-1 -mx-1 hover:bg-muted/50 transition-colors ${isFocused ? 'bg-muted/50' : ''}`}
            >
              {content}
            </button>
          ) : (
            <div key={s.key} className="flex items-center gap-1.5">
              {content}
            </div>
          )
        })}
      </div>
      )}
    </div>
  )
})

// Marker drawn on the value chart where a buy (green) or sell (red) happened.
// Recharts calls this per data point; non-trade points render an empty group.
function renderAssetTradeDot(props: {
  cx?: number; cy?: number; index?: number; payload?: { trades?: AssetTransaction[] }
}) {
  const { cx, cy, index, payload } = props
  const trades = payload?.trades
  if (cx == null || cy == null || !trades || trades.length === 0) {
    return <g key={`td-${index}`} />
  }
  const hasBuy = trades.some(t => t.kind === 'buy')
  const hasSell = trades.some(t => t.kind === 'sell')
  const color = hasSell && !hasBuy ? '#F43F5E' : hasBuy && !hasSell ? '#10B981' : '#6366F1'
  return (
    <circle key={`td-${index}`} cx={cx} cy={cy} r={4} fill={color} stroke="var(--card)" strokeWidth={1.5} />
  )
}

// Memoized for the same reason as PortfolioChart — all props here are
// primitives, so a shallow-equal bailout skips re-rendering an expanded
// holding's chart/ledger on unrelated parent-state changes (e.g. typing in
// the Add Asset dialog).
const AssetDetail = memo(function AssetDetail({ assetId, currency, locale: loc, dateLocale: dateLoc, purchasePrice, purchaseDate, valuationMethod, canWrite, chartOnly = false }: {
  assetId: string; currency: string; locale: string; dateLocale: string
  purchasePrice: number | null; purchaseDate: string | null
  valuationMethod: string
  canWrite: boolean
  // When true, render only the value-evolution chart (used above the ledger
  // for market-priced holdings) — no manual value form / value-history list.
  chartOnly?: boolean
}) {
  const { t } = useTranslation()
  const { mask } = usePrivacyMode()
  const queryClient = useQueryClient()

  const [valueAmount, setValueAmount] = useState('')
  const [valueDate, setValueDate] = useState(localDateString)

  // Shared by add/delete-value mutations below — both need every view that
  // could show this asset's value to reflect the change immediately.
  function refetchAssetValueViews() {
    queryClient.refetchQueries({ queryKey: ['assets'] })
    queryClient.refetchQueries({ queryKey: ['asset-values', assetId] })
    queryClient.refetchQueries({ queryKey: ['asset-trend', assetId] })
    queryClient.refetchQueries({ queryKey: ['portfolio-trend'] })
    queryClient.refetchQueries({ queryKey: ['dashboard'] })
  }

  const { data: values, isLoading: valuesLoading } = useQuery({
    queryKey: ['asset-values', assetId],
    queryFn: () => assets.values(assetId),
  })

  const { data: trend } = useQuery({
    queryKey: ['asset-trend', assetId],
    queryFn: () => assets.valueTrend(assetId),
  })

  // Build full trend: purchase point + stored values
  const trendWithPurchase = useMemo(() => {
    if (!trend) return []
    let result = [...trend]

    // Prepend purchase point if it predates the first value
    if (purchasePrice && purchaseDate) {
      if (result.length === 0 || purchaseDate < result[0].date) {
        result = [{ date: purchaseDate, amount: purchasePrice }, ...result]
      }
    }

    return result
  }, [trend, purchasePrice, purchaseDate])

  // Buy/sell markers on the value chart (shares the ledger's query cache).
  // Without these, a jump in the line could be either a price move or a
  // quantity change — the markers label "you bought/sold here".
  const { data: assetTrades } = useQuery({
    queryKey: ['asset-transactions', assetId],
    queryFn: () => assets.transactions(assetId),
    enabled: valuationMethod === 'market_price',
  })
  const chartData = useMemo(() => {
    const pts = trendWithPurchase.map(p => ({ ...p, trades: [] as AssetTransaction[] }))
    if (!assetTrades || pts.length === 0) return pts
    for (const tx of assetTrades) {
      const txTime = new Date(tx.date + 'T00:00:00').getTime()
      let best = 0
      let bestDiff = Infinity
      for (let i = 0; i < pts.length; i++) {
        const diff = Math.abs(new Date(pts[i].date + 'T00:00:00').getTime() - txTime)
        if (diff < bestDiff) { bestDiff = diff; best = i }
      }
      pts[best].trades.push(tx)
    }
    return pts
  }, [trendWithPurchase, assetTrades])

  // Build value history with purchase as the initial entry
  const valuesWithPurchase = useMemo(() => {
    if (!values) return []
    if (!purchasePrice || !purchaseDate) return values
    const hasPurchaseValue = values.some(v => v.date === purchaseDate && v.amount === purchasePrice)
    if (hasPurchaseValue) return values
    const purchaseEntry: AssetValue = {
      id: 'purchase',
      asset_id: assetId,
      amount: purchasePrice,
      date: purchaseDate,
      source: 'purchase',
    }
    return [...values, purchaseEntry]
  }, [values, purchasePrice, purchaseDate, assetId])

  const addValueMutation = useMutation({
    mutationFn: ({ assetId: id, ...data }: { assetId: string; amount: number; date: string }) =>
      assets.addValue(id, data),
    onSuccess: () => {
      refetchAssetValueViews()
      setValueAmount('')
      toast.success(t('assets.valueAdded'))
    },
    onError: (e) => toast.error(assetErrorMessage(e, t('common.error'))),
  })

  const deleteValueMutation = useMutation({
    mutationFn: (valueId: string) => assets.deleteValue(valueId),
    onSuccess: () => {
      refetchAssetValueViews()
      toast.success(t('assets.valueDeleted'))
    },
    onError: (e) => toast.error(assetErrorMessage(e, t('common.error'))),
  })

  // Determine chart color based on trend direction
  const trendIsPositive = trendWithPurchase.length >= 2
    ? trendWithPurchase[trendWithPurchase.length - 1].amount >= trendWithPurchase[0].amount
    : true
  const chartColor = trendIsPositive ? '#10B981' : '#F43F5E'

  const hasChart = trendWithPurchase.length > 1
  // In chart-only mode (market-priced holdings, paired with the ledger) there's
  // nothing to show until the value series has at least two points.
  if (chartOnly && !hasChart) return null

  return (
    <div className="border-t border-border px-5 py-5 space-y-5 bg-muted/5">
      {/* Value Trend Chart */}
      {hasChart && (
        <div>
          <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-3">{t('assets.valueTrend')}</p>
          <div className="h-44 -mx-1">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id={`gradient-${assetId}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={chartColor} stopOpacity={0.2} />
                    <stop offset="100%" stopColor={chartColor} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" strokeOpacity={0.5} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(v: string) => new Date(v + 'T00:00:00').toLocaleDateString(dateLoc, { month: 'short', year: '2-digit' })}
                />
                <YAxis
                  tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
                  axisLine={false}
                  tickLine={false}
                  width={56}
                  domain={['dataMin', 'dataMax']}
                  tickFormatter={(v: number) => {
                    const abs = Math.abs(v)
                    let formatted: string
                    if (abs >= 1_000_000) formatted = `${(v / 1_000_000).toFixed(1)}M`
                    else if (abs >= 1_000) formatted = `${(v / 1_000).toFixed(abs >= 10_000 ? 0 : 1)}k`
                    else formatted = v.toLocaleString(loc, { maximumFractionDigits: 0 })
                    return mask(formatted)
                  }}
                />
                <RechartsTooltip
                  content={({ active, payload, label }) => {
                    if (!active || !payload?.length) return null
                    const pt = payload[0].payload as { amount?: number; trades?: AssetTransaction[] }
                    return (
                      <div style={{ background: 'var(--card)', color: 'var(--foreground)', border: '1px solid var(--border)', borderRadius: '0.75rem', fontSize: '12px', boxShadow: '0 4px 12px rgba(0,0,0,0.08)', padding: '8px 10px' }}>
                        <p style={{ fontWeight: 600, marginBottom: 4 }}>
                          {new Date(String(label) + 'T00:00:00').toLocaleDateString(dateLoc, { day: 'numeric', month: 'long', year: 'numeric' })}
                        </p>
                        <div style={{ fontVariantNumeric: 'tabular-nums' }}>{mask(formatCurrency(pt.amount ?? 0, currency, loc))}</div>
                        {pt.trades?.map((tx) => (
                          <div key={tx.id} style={{ marginTop: 3, fontSize: 11, fontWeight: 500, color: tx.kind === 'buy' ? '#10B981' : '#F43F5E' }}>
                            {tx.kind === 'buy' ? t('assets.txBuy') : t('assets.txSell')} {mask(`${tx.quantity}`)} × {mask(formatCurrency(tx.price, currency, loc))}
                          </div>
                        ))}
                      </div>
                    )
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="amount"
                  stroke={chartColor}
                  strokeWidth={2}
                  fill={`url(#gradient-${assetId})`}
                  dot={renderAssetTradeDot}
                  activeDot={{ r: 4, strokeWidth: 2, fill: 'var(--card)', stroke: chartColor }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Add Value Form — only for manual assets */}
      {!chartOnly && valuationMethod === 'manual' && canWrite && <div className="flex items-end gap-2">
        <div className="flex-1">
          <Label htmlFor={`asset-value-amount-${assetId}`} className="text-[11px] text-muted-foreground">{t('assets.amount')}</Label>
          <Input
            id={`asset-value-amount-${assetId}`}
            type="number"
            step="any"
            value={valueAmount}
            onChange={e => setValueAmount(e.target.value)}
            placeholder="0.00"
            className="h-8 text-sm"
          />
        </div>
        <div className="w-36">
          <Label htmlFor={`asset-value-date-${assetId}`} className="text-[11px] text-muted-foreground">{t('assets.date')}</Label>
          <DatePickerInput id={`asset-value-date-${assetId}`} value={valueDate} onChange={setValueDate} />
        </div>
        <Button
          size="sm"
          className="h-8 px-3 text-xs"
          disabled={!valueAmount || addValueMutation.isPending}
          onClick={() => {
            if (valueAmount) {
              addValueMutation.mutate({
                assetId,
                amount: parseFloat(valueAmount),
                date: valueDate,
              })
            }
          }}
        >
          <Plus size={14} className="mr-1" />
          {t('assets.addValue')}
        </Button>
      </div>}

      {/* Value History */}
      {!chartOnly && <div>
        <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">{t('assets.valueHistory')}</p>
        {valuesLoading ? (
          <Skeleton className="h-20 w-full rounded-lg" />
        ) : valuesWithPurchase.length > 0 ? (
          <div className="rounded-lg border border-border overflow-hidden divide-y divide-border">
            {valuesWithPurchase.map((v: AssetValue, idx: number) => {
              const isPurchase = v.source === 'purchase'
              // Calculate change from previous entry (next in array since sorted desc)
              const prev = valuesWithPurchase[idx + 1]
              const change = prev ? v.amount - prev.amount : null
              const changePct = prev && prev.amount !== 0 ? (change! / prev.amount) * 100 : null

              return (
                <div key={v.id} className={`flex items-center justify-between py-2 px-3 transition-colors ${isPurchase ? 'bg-primary/5' : 'hover:bg-muted/30'}`}>
                  <div className="flex items-center gap-3 min-w-0">
                    <span className="text-sm tabular-nums font-semibold text-foreground">
                      {mask(formatCurrency(v.amount, currency, loc))}
                    </span>
                    {change != null && (
                      <span className={`text-[11px] tabular-nums font-medium ${change >= 0 ? 'text-emerald-600' : 'text-rose-500'}`}>
                        {change >= 0 ? '+' : ''}{mask(formatCurrency(change, currency, loc))}
                        {changePct != null && ` (${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%)`}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Badge variant={isPurchase ? 'default' : 'outline'} className={`text-[10px] px-1.5 py-0 ${isPurchase ? 'bg-primary/15 text-primary border-primary/30' : ''}`}>
                      {t(`assets.source${v.source.charAt(0).toUpperCase() + v.source.slice(1)}`)}
                    </Badge>
                    <span className="text-[11px] text-muted-foreground tabular-nums">
                      {new Date(v.date + 'T00:00:00').toLocaleDateString(dateLoc)}
                    </span>
                    {valuationMethod === 'manual' && v.source === 'manual' && canWrite && (
                      <button
                        onClick={() => deleteValueMutation.mutate(v.id)}
                        className="p-1 rounded text-muted-foreground/40 hover:text-rose-600 transition-colors"
                        disabled={deleteValueMutation.isPending}
                        title={t('common.delete')}
                      >
                        <Trash2 size={12} />
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground py-3 text-center">{t('dashboard.noData')}</p>
        )}
      </div>}
    </div>
  )
})

// Transactions tab (issue #235): the buy/sell ledger behind the consolidated
// holdings. Lists every transaction across the portfolio and lets users add a
// buy (to a new or existing ticker), record a sell, or edit/delete entries.
// Each mutation recomputes the affected holding's preço médio server-side.
function AssetTransactionsTab({
  holdings,
  wallets,
  locale,
  dateLocale,
  mask,
  canWrite,
  onChanged,
}: {
  holdings: Asset[]
  wallets: AssetGroup[]
  locale: string
  dateLocale: string
  mask: (v: string) => string
  canWrite: boolean
  onChanged: () => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const { data: txs, isLoading } = useQuery({
    queryKey: ['asset-transactions'],
    queryFn: () => assets.allTransactions(),
  })

  const marketHoldings = useMemo(
    () => holdings.filter((h) => h.valuation_method === 'market_price' && !h.sell_date),
    [holdings],
  )
  // Market holdings that exist but have no recorded buys → flagged in amber so
  // the user knows their average price / return can't be computed yet.
  const holdingsWithoutCost = useMemo(
    () => marketHoldings.filter((h) => h.average_price == null && h.units != null),
    [marketHoldings],
  )

  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingTx, setEditingTx] = useState<AssetTransaction | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  // Form state
  const [formKind, setFormKind] = useState<'buy' | 'sell'>('buy')
  const [formHolding, setFormHolding] = useState<string>('__new__')
  const [formTicker, setFormTicker] = useState('')
  const [formGroupId, setFormGroupId] = useState<string>('')
  const [formQuantity, setFormQuantity] = useState('')
  const [formPrice, setFormPrice] = useState('')
  const [formFee, setFormFee] = useState('')
  const [formDate, setFormDate] = useState<string>(localDateString)

  function afterChange() {
    queryClient.refetchQueries({ queryKey: ['asset-transactions'] })
    onChanged()
  }

  const saveMutation = useMutation({
    mutationFn: async () => {
      const quantity = parseFloat(formQuantity)
      const price = parseFloat(formPrice)
      const fee = formFee ? parseFloat(formFee) : 0
      if (editingTx) {
        return assets.updateTransaction(editingTx.id, {
          kind: formKind,
          quantity,
          price,
          fee,
          date: formDate,
        })
      }
      if (formHolding === '__new__') {
        return assets.buy({
          ticker: formTicker.trim().toUpperCase(),
          quantity,
          price,
          fee,
          date: formDate,
          group_id: formGroupId || null,
        })
      }
      return assets.addTransaction(formHolding, { kind: formKind, quantity, price, fee, date: formDate })
    },
    onSuccess: () => {
      afterChange()
      setDialogOpen(false)
      setEditingTx(null)
      toast.success(t('assets.txSaved'))
    },
    onError: (e) => toast.error(assetErrorMessage(e, t('common.error'))),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => assets.deleteTransaction(id),
    onSuccess: () => {
      afterChange()
      setDeletingId(null)
      toast.success(t('assets.txDeleted'))
    },
    onError: (e) => toast.error(assetErrorMessage(e, t('common.error'))),
  })

  function openAdd() {
    setEditingTx(null)
    setFormKind('buy')
    setFormHolding(marketHoldings.length > 0 ? marketHoldings[0].id : '__new__')
    setFormTicker('')
    setFormGroupId('')
    setFormQuantity('')
    setFormPrice('')
    setFormFee('')
    setFormDate(localDateString())
    setDialogOpen(true)
  }

  function openEdit(tx: AssetTransaction) {
    setEditingTx(tx)
    setFormKind(tx.kind)
    setFormHolding(tx.asset_id)
    setFormQuantity(`${tx.quantity}`)
    setFormPrice(`${tx.price}`)
    setFormFee(tx.fee ? `${tx.fee}` : '')
    setFormDate(tx.date)
    setDialogOpen(true)
  }

  function openAddForHolding(holdingId: string) {
    setEditingTx(null)
    setFormKind('buy')
    setFormHolding(holdingId)
    setFormTicker('')
    setFormGroupId('')
    setFormQuantity('')
    setFormPrice('')
    setFormFee('')
    setFormDate(localDateString())
    setDialogOpen(true)
  }

  const isNewTicker = !editingTx && formHolding === '__new__'
  // Warn before a sell that exceeds the held quantity (no shorting). Only on a
  // fresh sell into an existing holding; edits are validated server-side.
  const selectedHolding = marketHoldings.find((h) => h.id === formHolding)
  const selectedHeldUnits = selectedHolding?.units ?? 0
  const selectedCurrency = (editingTx ? holdings.find((h) => h.id === editingTx.asset_id)?.currency : selectedHolding?.currency) ?? 'USD'
  const oversell =
    !editingTx && !isNewTicker && isOversell(formKind, formQuantity, selectedHeldUnits)
  const canSave =
    !!formQuantity &&
    parseFloat(formQuantity) > 0 &&
    !!formPrice &&
    (isNewTicker ? !!formTicker.trim() : true) &&
    !oversell &&
    !saveMutation.isPending

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">{t('assets.txTabHint')}</p>
        {canWrite && (
          <Button onClick={openAdd} className="gap-1.5">
            <Plus size={16} />
            {t('assets.addTransaction')}
          </Button>
        )}
      </div>

      {/* Holdings with no recorded buys — flagged in amber so the user knows
          the average price / return is missing until they add their purchases. */}
      {holdingsWithoutCost.length > 0 && (
        <div className="space-y-1.5">
          {holdingsWithoutCost.map((h) => (
            <div
              key={h.id}
              className="flex items-center gap-3 px-4 py-2.5 rounded-lg border border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/20"
            >
              <AlertTriangle size={16} className="text-amber-500 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-amber-900 dark:text-amber-200 truncate">
                  {h.ticker || h.name}
                </p>
                <p className="text-[11px] text-amber-700 dark:text-amber-300/80">
                  {t('assets.noPriceWarning')}
                </p>
              </div>
              {canWrite && (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 px-2.5 text-xs border-amber-400 text-amber-700 hover:bg-amber-100 dark:text-amber-300 dark:hover:bg-amber-900/40 shrink-0"
                  onClick={() => openAddForHolding(h.id)}
                >
                  {t('assets.addBuys')}
                </Button>
              )}
            </div>
          ))}
        </div>
      )}

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-12 rounded-lg" />)}
        </div>
      ) : (txs ?? []).length === 0 ? (
        holdingsWithoutCost.length === 0 ? (
          <div className="text-center py-16">
            <TrendingUp className="mx-auto h-12 w-12 text-muted-foreground/40 mb-3" />
            <p className="text-muted-foreground">{t('assets.noTransactions')}</p>
          </div>
        ) : null
      ) : (
        <div className="rounded-xl border border-border overflow-hidden divide-y divide-border">
          {(txs ?? []).map((tx) => {
            const total = tx.quantity * tx.price
            const cur = tx.currency ?? 'USD'
            return (
              <div key={tx.id} className="flex items-center gap-3 px-4 py-3 hover:bg-muted/20 transition-colors">
                <Badge
                  variant="outline"
                  className={`text-[10px] px-1.5 py-0 shrink-0 ${tx.kind === 'buy' ? 'text-emerald-600 border-emerald-200' : 'text-rose-600 border-rose-200'}`}
                >
                  {tx.kind === 'buy' ? t('assets.txBuy') : t('assets.txSell')}
                </Badge>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-foreground truncate">
                    {tx.ticker || tx.asset_name}
                  </p>
                  <p className="text-[11px] text-muted-foreground tabular-nums">
                    {new Date(tx.date + 'T00:00:00').toLocaleDateString(dateLocale)} ·{' '}
                    {mask(`${tx.quantity}`)} × {mask(formatCurrency(tx.price, cur, locale))}
                  </p>
                </div>
                <div className="text-right shrink-0">
                  <p className="text-sm font-semibold tabular-nums text-foreground">
                    {mask(formatCurrency(total, cur, locale))}
                  </p>
                  {tx.fee > 0 && (
                    <p className="text-[10px] text-muted-foreground tabular-nums">
                      {t('assets.txFee')} {mask(formatCurrency(tx.fee, cur, locale))}
                    </p>
                  )}
                </div>
                {canWrite && (
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => openEdit(tx)}
                      title={t('common.edit')}
                      className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      onClick={() => setDeletingId(tx.id)}
                      title={t('common.delete')}
                      className="p-1.5 rounded-lg text-muted-foreground hover:text-rose-600 hover:bg-rose-50 transition-colors"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Add / Edit transaction dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{editingTx ? t('assets.editTransaction') : t('assets.addTransaction')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            {/* Holding picker — only when adding (kind is locked on edit too) */}
            {!editingTx && (
              <div className="space-y-2">
                <Label htmlFor="tx-holding">{t('assets.holding')}</Label>
                <Select
                  value={formHolding}
                  onValueChange={(v) => {
                    setFormHolding(v)
                    if (v === '__new__') setFormKind('buy')
                  }}
                >
                  <SelectTrigger id="tx-holding" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__new__">{t('assets.newTicker')}</SelectItem>
                    {marketHoldings.map((h) => (
                      <SelectItem key={h.id} value={h.id}>
                        {h.ticker || h.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {isNewTicker && (
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="tx-ticker">{t('assets.ticker')}</Label>
                  <Input
                    id="tx-ticker"
                    value={formTicker}
                    onChange={(e) => setFormTicker(e.target.value)}
                    placeholder={t('assets.tickerPlaceholder')}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="tx-wallet">{t('assets.wallet')}</Label>
                  <Select value={formGroupId || '__none__'} onValueChange={(v) => setFormGroupId(v === '__none__' ? '' : v)}>
                    <SelectTrigger id="tx-wallet" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__none__">{t('assets.noWallet')}</SelectItem>
                      {wallets.map((w) => (
                        <SelectItem key={w.id} value={w.id}>{w.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            )}

            {/* Buy/Sell toggle — only for existing holdings (can't sell a new ticker) */}
            {!isNewTicker && (
              <div className="space-y-2">
                <Label>{t('assets.txType')}</Label>
                <div className="grid grid-cols-2 gap-2">
                  {(['buy', 'sell'] as const).map((k) => (
                    <button
                      key={k}
                      type="button"
                      className={`px-3 py-2 rounded-lg text-sm font-medium border transition-all ${formKind === k ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:border-primary/50'}`}
                      onClick={() => setFormKind(k)}
                    >
                      {k === 'buy' ? t('assets.txBuy') : t('assets.txSell')}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="tx-quantity">{t('assets.quantity')}</Label>
                <Input id="tx-quantity" type="number" step="any" min="0" value={formQuantity} onChange={(e) => setFormQuantity(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="tx-unit-price">{t('assets.unitPrice')}</Label>
                <Input id="tx-unit-price" type="number" step="any" min="0" value={formPrice} onChange={(e) => setFormPrice(e.target.value)} />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="tx-fee">{t('assets.fee')}</Label>
                <Input id="tx-fee" type="number" step="any" min="0" value={formFee} onChange={(e) => setFormFee(e.target.value)} placeholder="0" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="tx-date">{t('assets.date')}</Label>
                <DatePickerInput id="tx-date" value={formDate} onChange={setFormDate} />
              </div>
            </div>

            {oversell && (
              <p className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
                <AlertTriangle size={13} className="shrink-0" />
                {t('assets.oversellWarning', { available: selectedHeldUnits })}
              </p>
            )}
            <TxTotalPreview quantity={formQuantity} price={formPrice} fee={formFee} kind={formKind} currency={selectedCurrency} locale={locale} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>{t('common.cancel')}</Button>
            <Button onClick={() => saveMutation.mutate()} disabled={!canSave}>{t('common.save')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation */}
      <Dialog open={!!deletingId} onOpenChange={() => setDeletingId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('assets.confirmDeleteTxTitle')}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">{t('assets.confirmDeleteTx')}</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeletingId(null)}>{t('common.cancel')}</Button>
            <Button variant="destructive" onClick={() => deletingId && deleteMutation.mutate(deletingId)} disabled={deleteMutation.isPending}>
              {t('common.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// Inline buy/sell ledger shown when a holding row is expanded (the
// "Lançamentos" of the reference). Lists the holding's transactions and
// offers a one-tap add — the consolidated row above is recomputed server-side.
function HoldingLedger({
  asset,
  locale,
  dateLocale,
  mask,
  canWrite,
  onAdd,
  onChanged,
}: {
  asset: Asset
  locale: string
  dateLocale: string
  mask: (v: string) => string
  canWrite: boolean
  onAdd: () => void
  onChanged: () => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: txs, isLoading } = useQuery({
    queryKey: ['asset-transactions', asset.id],
    queryFn: () => assets.transactions(asset.id),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => assets.deleteTransaction(id),
    onSuccess: () => {
      queryClient.refetchQueries({ queryKey: ['asset-transactions', asset.id] })
      queryClient.refetchQueries({ queryKey: ['asset-transactions'] })
      onChanged()
      toast.success(t('assets.txDeleted'))
    },
    onError: (e) => toast.error(assetErrorMessage(e, t('common.error'))),
  })

  return (
    <div className="border-t border-border bg-muted/10 px-4 py-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
          {t('assets.ledgerTitle')}
        </p>
        {canWrite && (
          <Button size="sm" variant="outline" className="h-7 px-2 text-xs gap-1" onClick={onAdd}>
            <Plus size={13} />
            {t('assets.addTransaction')}
          </Button>
        )}
      </div>
      {isLoading ? (
        <Skeleton className="h-16 w-full rounded-lg" />
      ) : (txs ?? []).length === 0 ? (
        <p className="text-xs text-muted-foreground py-2">{t('assets.noLedgerYet')}</p>
      ) : (
        <div className="rounded-lg border border-border overflow-hidden divide-y divide-border bg-card">
          {(txs ?? []).map((tx) => (
            <div key={tx.id} className="flex items-center gap-3 px-3 py-2">
              <Badge
                variant="outline"
                className={`text-[9px] px-1 py-0 shrink-0 ${tx.kind === 'buy' ? 'text-emerald-600 border-emerald-200' : 'text-rose-600 border-rose-200'}`}
              >
                {tx.kind === 'buy' ? t('assets.txBuy') : t('assets.txSell')}
              </Badge>
              <span className="text-[11px] text-muted-foreground tabular-nums flex-1">
                {new Date(tx.date + 'T00:00:00').toLocaleDateString(dateLocale)} ·{' '}
                {mask(`${tx.quantity}`)} × {mask(formatCurrency(tx.price, asset.currency, locale))}
              </span>
              <span className="text-xs font-semibold tabular-nums text-foreground">
                {mask(formatCurrency(tx.quantity * tx.price, asset.currency, locale))}
              </span>
              {canWrite && (
                <button
                  onClick={() => deleteMutation.mutate(tx.id)}
                  disabled={deleteMutation.isPending}
                  className="p-1 rounded text-muted-foreground/50 hover:text-rose-600 transition-colors"
                  title={t('common.delete')}
                >
                  <Trash2 size={12} />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// Lightweight dialog to add a buy/sell to an already-existing holding. Used by
// the holdings table ("+ add buys") and the inline ledger.
function AddHoldingTransactionDialog({
  assetId,
  holding,
  locale,
  onClose,
  onChanged,
}: {
  assetId: string | null
  holding: Asset | null
  locale: string
  onClose: () => void
  onChanged: () => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<'buy' | 'sell'>('buy')
  const [quantity, setQuantity] = useState('')
  const [price, setPrice] = useState('')
  const [fee, setFee] = useState('')
  const [date, setDate] = useState(localDateString)

  useEffect(() => {
    if (assetId) {
      setKind('buy')
      setQuantity('')
      setPrice('')
      setFee('')
      setDate(localDateString())
    }
  }, [assetId])

  const saveMutation = useMutation({
    mutationFn: () =>
      assets.addTransaction(assetId!, {
        kind,
        quantity: parseFloat(quantity),
        price: parseFloat(price),
        fee: fee ? parseFloat(fee) : 0,
        date,
      }),
    onSuccess: () => {
      queryClient.refetchQueries({ queryKey: ['asset-transactions'] })
      if (assetId) queryClient.refetchQueries({ queryKey: ['asset-transactions', assetId] })
      onChanged()
      onClose()
      toast.success(t('assets.txSaved'))
    },
    onError: (e) => toast.error(assetErrorMessage(e, t('common.error'))),
  })

  const cur = holding?.currency ?? 'USD'
  const heldUnits = holding?.units ?? 0
  const oversell = isOversell(kind, quantity, heldUnits)
  const canSave = !!quantity && parseFloat(quantity) > 0 && !!price && !oversell && !saveMutation.isPending

  return (
    <Dialog open={!!assetId} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {t('assets.addTransaction')}{holding ? ` · ${holding.ticker || holding.name}` : ''}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>{t('assets.txType')}</Label>
            <div className="grid grid-cols-2 gap-2">
              {(['buy', 'sell'] as const).map((k) => (
                <button
                  key={k}
                  type="button"
                  className={`px-3 py-2 rounded-lg text-sm font-medium border transition-all ${kind === k ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:border-primary/50'}`}
                  onClick={() => setKind(k)}
                >
                  {k === 'buy' ? t('assets.txBuy') : t('assets.txSell')}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="htx-quantity">{t('assets.quantity')}</Label>
              <Input id="htx-quantity" type="number" step="any" min="0" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="htx-unit-price">{t('assets.unitPrice')}</Label>
              <Input id="htx-unit-price" type="number" step="any" min="0" value={price} onChange={(e) => setPrice(e.target.value)} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="htx-fee">{t('assets.fee')}</Label>
              <Input id="htx-fee" type="number" step="any" min="0" value={fee} onChange={(e) => setFee(e.target.value)} placeholder="0" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="htx-date">{t('assets.date')}</Label>
              <DatePickerInput id="htx-date" value={date} onChange={setDate} />
            </div>
          </div>
          {oversell && (
            <p className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
              <AlertTriangle size={13} className="shrink-0" />
              {t('assets.oversellWarning', { available: heldUnits })}
            </p>
          )}
          <TxTotalPreview quantity={quantity} price={price} fee={fee} kind={kind} currency={cur} locale={locale} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={() => saveMutation.mutate()} disabled={!canSave}>{t('common.save')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
