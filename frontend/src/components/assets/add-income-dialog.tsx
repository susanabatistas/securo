import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { assets as assetsApi } from '@/lib/api'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { DatePickerInput } from '@/components/ui/date-picker-input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { formatCurrency } from '@/lib/format'
import { localDateString } from '@/lib/date-utils'
import { History, Trash2 } from 'lucide-react'
import type { AssetIncomeKind, DividendHistoryCandidate } from '@/types'

const INCOME_KINDS: AssetIncomeKind[] = ['dividendo', 'jcp', 'rendimento', 'outro']

export function AddIncomeDialog({
  open,
  onOpenChange,
  locale,
  dateLocale,
  onSaved,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  locale: string
  dateLocale: string
  onSaved: () => void
}) {
  const { t } = useTranslation()
  const [assetId, setAssetId] = useState('')
  const [mode, setMode] = useState<'manual' | 'fetch'>('manual')
  const [kind, setKind] = useState<AssetIncomeKind>('dividendo')
  const [amount, setAmount] = useState('')
  const [date, setDate] = useState(localDateString())
  const [candidates, setCandidates] = useState<DividendHistoryCandidate[] | null>(null)

  // All holdings, including sold/archived — a dividend can be logged for a
  // period when the position was still held, even if it's since been sold.
  // Only market-priced (ticker-backed) assets pay dividends in this model.
  const { data: allAssets, isLoading: assetsLoading } = useQuery({
    queryKey: ['assets-for-income-picker'],
    queryFn: () => assetsApi.list(true),
    enabled: open,
  })
  const pickable = useMemo(
    () => (allAssets ?? []).filter((a) => a.valuation_method === 'market_price'),
    [allAssets],
  )
  const selectedAsset = pickable.find((a) => a.id === assetId) ?? null

  const addMutation = useMutation({
    mutationFn: () => assetsApi.income.add(assetId, { kind, amount: parseFloat(amount), date }),
    onSuccess: () => {
      toast.success(t('assets.incomeSaved'))
      onSaved()
      handleClose()
    },
    onError: () => toast.error(t('common.error')),
  })

  const fetchPreviewMutation = useMutation({
    mutationFn: () => assetsApi.income.fetchPreview(assetId),
    onSuccess: (result) => setCandidates(result.candidates),
    onError: (e) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(detail || t('common.error'))
    },
  })

  const applyFetchMutation = useMutation({
    mutationFn: () => assetsApi.income.fetchApply(assetId, candidates ?? []),
    onSuccess: (rows) => {
      toast.success(t('assets.incomeFetchApplied', { count: rows.length }))
      onSaved()
      handleClose()
    },
    onError: () => toast.error(t('common.error')),
  })

  function handleClose() {
    setAssetId('')
    setMode('manual')
    setKind('dividendo')
    setAmount('')
    setDate(localDateString())
    setCandidates(null)
    onOpenChange(false)
  }

  function updateCandidate(index: number, patch: Partial<DividendHistoryCandidate>) {
    setCandidates((prev) => prev && prev.map((c, i) => (i === index ? { ...c, ...patch } : c)))
  }

  function removeCandidate(index: number) {
    setCandidates((prev) => prev && prev.filter((_, i) => i !== index))
  }

  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : handleClose())}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('assets.addIncomeTitle')}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="income-asset">{t('assets.incomeAssetLabel')}</Label>
            {assetsLoading ? (
              <Skeleton className="h-9 w-full" />
            ) : (
              <Select value={assetId} onValueChange={(v) => { setAssetId(v); setCandidates(null) }}>
                <SelectTrigger id="income-asset" className="w-full">
                  <SelectValue placeholder={t('assets.incomeAssetPlaceholder')} />
                </SelectTrigger>
                <SelectContent>
                  {pickable.map((a) => (
                    <SelectItem key={a.id} value={a.id}>
                      <span className="flex items-center gap-1.5">
                        {a.ticker || a.name}
                        {(a.sell_date || a.is_archived) && (
                          <span className="text-[10px] text-rose-600">({t('assets.sold')})</span>
                        )}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          {selectedAsset && (
            <>
              <div className="inline-flex items-center rounded-lg border border-border p-0.5 bg-muted/40">
                <button
                  type="button"
                  onClick={() => setMode('manual')}
                  className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${mode === 'manual' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
                >
                  {t('assets.incomeModeManual')}
                </button>
                <button
                  type="button"
                  onClick={() => setMode('fetch')}
                  className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${mode === 'fetch' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
                >
                  {t('assets.incomeModeFetch')}
                </button>
              </div>

              {mode === 'manual' ? (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-2">
                      <Label htmlFor="income-kind">{t('assets.incomeKindLabel')}</Label>
                      <Select value={kind} onValueChange={(v) => setKind(v as AssetIncomeKind)}>
                        <SelectTrigger id="income-kind" className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {INCOME_KINDS.map((k) => (
                            <SelectItem key={k} value={k}>{t(`assets.incomeKind.${k}`)}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="income-amount">{t('assets.incomeAmountLabel')} ({selectedAsset.currency})</Label>
                      <Input id="income-amount" type="number" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label>{t('assets.incomeDateLabel')}</Label>
                    <DatePickerInput value={date} onChange={setDate} />
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  {candidates === null ? (
                    <Button
                      variant="outline"
                      className="w-full gap-1.5"
                      disabled={fetchPreviewMutation.isPending}
                      onClick={() => fetchPreviewMutation.mutate()}
                    >
                      <History size={14} />
                      {fetchPreviewMutation.isPending ? t('common.saving') : t('assets.incomeFetchButton')}
                    </Button>
                  ) : candidates.length === 0 ? (
                    <p className="text-sm text-muted-foreground py-4 text-center">{t('assets.incomeFetchEmpty')}</p>
                  ) : (
                    <div className="max-h-64 overflow-y-auto rounded-lg border border-border divide-y divide-border">
                      {candidates.map((c, i) => (
                        <div key={`${c.date}-${i}`} className="p-2 flex items-center gap-2 text-sm">
                          <span className="text-xs text-muted-foreground w-24 shrink-0">
                            {new Date(c.date + 'T00:00:00').toLocaleDateString(dateLocale)}
                          </span>
                          <Select value={c.kind} onValueChange={(v) => updateCandidate(i, { kind: v as AssetIncomeKind })}>
                            <SelectTrigger className="h-7 text-xs flex-1">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {INCOME_KINDS.map((k) => (
                                <SelectItem key={k} value={k}>{t(`assets.incomeKind.${k}`)}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <span className="tabular-nums shrink-0">{formatCurrency(c.amount, selectedAsset.currency, locale)}</span>
                          <button onClick={() => removeCandidate(i)} className="p-1 text-muted-foreground hover:text-rose-600">
                            <Trash2 size={12} />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>{t('common.cancel')}</Button>
          {mode === 'manual' ? (
            <Button
              disabled={!assetId || !amount || parseFloat(amount) <= 0 || addMutation.isPending}
              onClick={() => addMutation.mutate()}
            >
              {addMutation.isPending ? t('common.saving') : t('common.save')}
            </Button>
          ) : (
            <Button
              disabled={!candidates || candidates.length === 0 || applyFetchMutation.isPending}
              onClick={() => applyFetchMutation.mutate()}
            >
              {applyFetchMutation.isPending ? t('common.saving') : t('assets.incomeFetchConfirm', { count: candidates?.length ?? 0 })}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
