import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { assets as assetsApi } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { formatCurrency } from '@/lib/format'
import { toast } from 'sonner'
import { Plus, Trash2 } from 'lucide-react'
import { AddIncomeDialog } from './add-income-dialog'

const KIND_LABEL_KEY: Record<string, string> = {
  dividendo: 'assets.incomeKind.dividendo',
  jcp: 'assets.incomeKind.jcp',
  rendimento: 'assets.incomeKind.rendimento',
  outro: 'assets.incomeKind.outro',
}

const MONTH_ABBR_INDEX = ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12']

function formatCompact(value: number, currency = 'USD', locale = 'en-US') {
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value)
}

export function AssetIncomeTab({
  userCurrency,
  locale,
  dateLocale,
  mask,
  canWrite,
}: {
  userCurrency: string
  locale: string
  dateLocale: string
  mask: (v: string) => string
  canWrite: boolean
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [year, setYear] = useState<number>(new Date().getFullYear())
  const [addOpen, setAddOpen] = useState(false)

  const { data: allSummary } = useQuery({
    queryKey: ['income', 'summary', 'all'],
    queryFn: () => assetsApi.income.summary(),
  })

  const years = useMemo(() => {
    const set = new Set(allSummary?.months.map((m) => Number(m.month.slice(0, 4))) ?? [])
    set.add(year)
    return Array.from(set).sort((a, b) => b - a)
  }, [allSummary, year])

  const { data: yearRows, isLoading } = useQuery({
    queryKey: ['income', 'list', year],
    queryFn: () => assetsApi.income.list(year),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => assetsApi.income.delete(id),
    onSuccess: () => {
      queryClient.refetchQueries({ queryKey: ['income'] })
      toast.success(t('assets.incomeDeleted'))
    },
    onError: () => toast.error(t('common.error')),
  })

  const chartData = useMemo(() => {
    const byMonth = new Map<string, number>()
    for (const m of allSummary?.months ?? []) {
      if (m.month.startsWith(`${year}-`)) byMonth.set(m.month.slice(5, 7), m.total)
    }
    return MONTH_ABBR_INDEX.map((m) => ({
      month: new Date(2000, Number(m) - 1, 1).toLocaleDateString(dateLocale, { month: 'short' }),
      total: byMonth.get(m) ?? 0,
    }))
  }, [allSummary, year, dateLocale])

  const yearTotal = chartData.reduce((acc, m) => acc + m.total, 0)

  const tooltipStyle = {
    background: 'var(--card)',
    color: 'var(--foreground)',
    border: '1px solid var(--border)',
    borderRadius: '0.75rem',
    boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
    fontSize: '12px',
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <Select value={String(year)} onValueChange={(v) => setYear(Number(v))}>
            <SelectTrigger className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {years.map((y) => (
                <SelectItem key={y} value={String(y)}>{y}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div>
            <span className="text-xs text-muted-foreground">{t('assets.incomeTotalYear')}</span>
            <p className="text-lg font-bold tabular-nums text-foreground">
              {mask(formatCurrency(yearTotal, userCurrency, locale))}
            </p>
          </div>
        </div>
        {canWrite && (
          <Button onClick={() => setAddOpen(true)} className="gap-1.5">
            <Plus size={16} />
            {t('assets.addIncome')}
          </Button>
        )}
      </div>

      <div className="h-56 rounded-lg border border-border p-3">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
            <XAxis
              dataKey="month"
              tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }}
              axisLine={false}
              tickLine={false}
              width={48}
              tickFormatter={(v: number) => formatCompact(v, userCurrency, locale)}
            />
            <Tooltip
              formatter={(value?: number) => mask(formatCurrency(value ?? 0, userCurrency, locale))}
              contentStyle={tooltipStyle}
              cursor={{ fill: 'var(--muted)' }}
            />
            <Bar dataKey="total" fill="#10B981" radius={[4, 4, 0, 0]} maxBarSize={28} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : !yearRows || yearRows.length === 0 ? (
        <p className="text-sm text-muted-foreground py-6 text-center">{t('assets.incomeEmpty')}</p>
      ) : (
        <div className="rounded-lg border border-border divide-y divide-border">
          {yearRows.map((row) => (
            <div key={row.id} className="p-2.5 text-sm flex items-center justify-between gap-2">
              <div className="min-w-0 flex items-center gap-2">
                <div>
                  <span className="font-medium text-foreground">{row.ticker || row.asset_name}</span>
                  {row.asset_sold && (
                    <Badge variant="outline" className="ml-1.5 text-[9px] px-1 py-0 text-rose-600 border-rose-200 dark:border-rose-800">
                      {t('assets.sold')}
                    </Badge>
                  )}
                  <div className="text-[11px] text-muted-foreground">
                    {t(KIND_LABEL_KEY[row.kind] ?? row.kind)} · {new Date(row.date + 'T00:00:00').toLocaleDateString(dateLocale)}
                    {row.source !== 'manual' && ` · ${t(`assets.incomeSource.${row.source}`, { defaultValue: row.source })}`}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-right">
                  <span className="block font-medium tabular-nums text-foreground">
                    {mask(formatCurrency(row.amount, row.currency || userCurrency, locale))}
                  </span>
                  {row.amount_primary != null && row.currency && row.currency !== userCurrency && (
                    <span className="block text-[10px] text-muted-foreground tabular-nums">
                      {mask(formatCurrency(row.amount_primary, userCurrency, locale))}
                    </span>
                  )}
                </span>
                {canWrite && (
                  <button
                    onClick={() => deleteMutation.mutate(row.id)}
                    className="p-1 rounded text-muted-foreground hover:text-rose-600 hover:bg-rose-50 transition-colors"
                    title={t('common.delete')}
                  >
                    <Trash2 size={13} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <AddIncomeDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        locale={locale}
        dateLocale={dateLocale}
        onSaved={() => queryClient.refetchQueries({ queryKey: ['income'] })}
      />
    </div>
  )
}
