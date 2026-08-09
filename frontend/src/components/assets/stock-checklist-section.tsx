import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { assets as assetsApi } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { CheckCircle2, XCircle, HelpCircle, Settings2 } from 'lucide-react'
import { toast } from 'sonner'
import type { Asset, StockChecklistStatus } from '@/types'

const STATUS_CONFIG: Record<string, { colorClass: string; icon: typeof CheckCircle2 }> = {
  aprovado: { colorClass: 'text-emerald-600 border-emerald-300 bg-emerald-50 dark:bg-emerald-950/30', icon: CheckCircle2 },
  rever: { colorClass: 'text-amber-600 border-amber-300 bg-amber-50 dark:bg-amber-950/30', icon: HelpCircle },
  a_evitar: { colorClass: 'text-rose-600 border-rose-300 bg-rose-50 dark:bg-rose-950/30', icon: XCircle },
  nao_avaliado: { colorClass: 'text-muted-foreground border-border bg-muted/30', icon: HelpCircle },
}

const CRITERION_KEYS = ['roe', 'revenue_cagr', 'profit_cagr', 'net_debt_to_ebitda'] as const

const DEFAULT_THRESHOLDS = { roe_min: 15, revenue_cagr_min: 0, profit_cagr_min: 0, net_debt_ebitda_max: 2 }

/**
 * Deterministic stock checklist — only rendered for individual stocks
 * (Asset.type === 'stock'). Criteria come from GET .../stock-checklist;
 * thresholds are editable inputs, not fixed. Sector/industry are shown as
 * info only, never a pass/fail row.
 */
export function StockChecklistSection({ asset, canWrite }: { asset: Asset; canWrite: boolean }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [thresholds, setThresholds] = useState(DEFAULT_THRESHOLDS)
  const [showThresholds, setShowThresholds] = useState(false)

  const { data: result, isLoading } = useQuery({
    queryKey: ['stock-checklist', asset.id, thresholds],
    queryFn: () => assetsApi.stockChecklist(asset.id, thresholds),
  })

  const overrideMutation = useMutation({
    mutationFn: (status: StockChecklistStatus | null) => assetsApi.update(asset.id, { stock_checklist_status: status }),
    onSuccess: () => {
      queryClient.refetchQueries({ queryKey: ['assets'] })
      toast.success(t('assets.checklistOverrideSaved'))
    },
  })

  if (isLoading) {
    return <Skeleton className="h-24 w-full" />
  }
  if (!result) return null

  const effectiveStatus = result.manual_override ?? result.overall_status
  const config = STATUS_CONFIG[effectiveStatus] ?? STATUS_CONFIG.nao_avaliado
  const StatusIcon = config.icon

  return (
    <div className="rounded-lg border border-border p-3 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">{t('assets.checklistTitle')}</span>
          <Badge variant="outline" className={`text-[10px] px-1.5 py-0 gap-1 ${config.colorClass}`}>
            <StatusIcon size={11} />
            {t(`assets.checklistStatus.${effectiveStatus}`)}
          </Badge>
          {result.manual_override && (
            <span className="text-[10px] text-muted-foreground">{t('assets.checklistManualBadge')}</span>
          )}
        </div>
        <button
          onClick={() => setShowThresholds((v) => !v)}
          className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
          title={t('assets.checklistAdjustThresholds')}
        >
          <Settings2 size={13} />
        </button>
      </div>

      {(result.sector || result.industry) && (
        <div className="text-[11px] text-muted-foreground">
          {[result.sector, result.industry].filter(Boolean).join(' · ')}
        </div>
      )}

      {showThresholds && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <ThresholdInput label={t('assets.checklistCriteria.roe')} value={thresholds.roe_min} onChange={(v) => setThresholds((th) => ({ ...th, roe_min: v }))} />
          <ThresholdInput label={t('assets.checklistCriteria.revenue_cagr')} value={thresholds.revenue_cagr_min} onChange={(v) => setThresholds((th) => ({ ...th, revenue_cagr_min: v }))} />
          <ThresholdInput label={t('assets.checklistCriteria.profit_cagr')} value={thresholds.profit_cagr_min} onChange={(v) => setThresholds((th) => ({ ...th, profit_cagr_min: v }))} />
          <ThresholdInput label={t('assets.checklistCriteria.net_debt_to_ebitda')} value={thresholds.net_debt_ebitda_max} onChange={(v) => setThresholds((th) => ({ ...th, net_debt_ebitda_max: v }))} />
        </div>
      )}

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {CRITERION_KEYS.map((key) => {
          const criterion = result.criteria.find((c) => c.key === key)
          const status = criterion?.status ?? 'not_evaluated'
          const cfg = status === 'pass' ? STATUS_CONFIG.aprovado : status === 'fail' ? STATUS_CONFIG.a_evitar : STATUS_CONFIG.nao_avaliado
          const Icon = cfg.icon
          return (
            <div key={key} className={`rounded-md border px-2 py-1.5 ${cfg.colorClass}`}>
              <div className="flex items-center gap-1 text-[10px] font-medium">
                <Icon size={11} />
                {t(`assets.checklistCriteria.${key}`)}
              </div>
              <div className="text-[11px] tabular-nums mt-0.5">
                {criterion?.value != null
                  ? key === 'net_debt_to_ebitda'
                    ? `${criterion.value.toFixed(2)}x`
                    : `${criterion.value.toFixed(1)}%`
                  : t('assets.checklistNotEvaluated')}
              </div>
            </div>
          )
        })}
      </div>

      {canWrite && (
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-muted-foreground">{t('assets.checklistManualOverride')}</span>
          <Select
            value={result.manual_override ?? '__auto__'}
            onValueChange={(v) => overrideMutation.mutate(v === '__auto__' ? null : (v as StockChecklistStatus))}
          >
            <SelectTrigger className="h-7 w-40 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__auto__">{t('assets.checklistAuto')}</SelectItem>
              <SelectItem value="aprovado">{t('assets.checklistStatus.aprovado')}</SelectItem>
              <SelectItem value="rever">{t('assets.checklistStatus.rever')}</SelectItem>
              <SelectItem value="a_evitar">{t('assets.checklistStatus.a_evitar')}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      )}
    </div>
  )
}

function ThresholdInput({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div>
      <label className="text-[10px] text-muted-foreground block mb-0.5">{label}</label>
      <Input
        type="number"
        step="0.1"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-7 text-xs"
      />
    </div>
  )
}
