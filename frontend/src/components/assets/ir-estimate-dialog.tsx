import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { assets as assetsApi } from '@/lib/api'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { formatCurrency } from '@/lib/format'
import { AlertTriangle } from 'lucide-react'

const TAX_CATEGORY_LABEL_KEY: Record<string, string> = {
  renda_fixa: 'assets.taxCategory.renda_fixa',
  fii: 'assets.taxCategory.fii',
  acoes_etfs_cripto: 'assets.taxCategory.acoes_etfs_cripto',
}

export function IREstimateDialog({
  open,
  onOpenChange,
  userCurrency,
  locale,
  mask,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  userCurrency: string
  locale: string
  mask: (v: string) => string
}) {
  const { t } = useTranslation()
  const { data, isLoading } = useQuery({
    queryKey: ['ir-estimate'],
    queryFn: () => assetsApi.irEstimate(),
    enabled: open,
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('assets.irEstimateTitle')}</DialogTitle>
        </DialogHeader>

        {data?.applicable !== false && (
          <div className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-950/30 p-3 text-xs text-amber-800 dark:text-amber-300">
            <AlertTriangle size={14} className="shrink-0 mt-0.5" />
            <span>{data?.disclaimer ?? t('assets.irEstimateDisclaimerFallback')}</span>
          </div>
        )}

        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : data && !data.applicable ? (
          <p className="text-sm text-muted-foreground py-6 text-center">{t('assets.irEstimateNotApplicable')}</p>
        ) : !data || data.assets.length === 0 ? (
          <p className="text-sm text-muted-foreground py-6 text-center">{t('assets.irEstimateEmpty')}</p>
        ) : (
          <div className="space-y-3">
            <div className="max-h-80 overflow-y-auto rounded-lg border border-border divide-y divide-border">
              {data.assets.map((a) => (
                <div key={a.asset_id} className="p-3 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <span className="font-medium text-foreground truncate">{a.ticker || a.name}</span>
                      <span className="ml-2 text-[11px] text-muted-foreground">
                        {t(TAX_CATEGORY_LABEL_KEY[a.tax_category] ?? a.tax_category)}
                        {a.days_held != null && ` · ${a.days_held}${t('assets.daysShort')}`}
                        {' · '}{a.rate_pct}%
                      </span>
                    </div>
                    <span className="font-semibold tabular-nums text-foreground shrink-0">
                      {mask(formatCurrency(a.estimated_tax, userCurrency, locale))}
                    </span>
                  </div>
                  {a.note && <p className="mt-1 text-[11px] text-muted-foreground">{a.note}</p>}
                </div>
              ))}
            </div>
            <div className="flex items-center justify-between px-1">
              <span className="text-sm font-medium text-muted-foreground">{t('assets.irEstimateTotal')}</span>
              <span className="text-lg font-bold tabular-nums text-foreground">
                {mask(formatCurrency(data.total_estimated_tax, userCurrency, locale))}
              </span>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
