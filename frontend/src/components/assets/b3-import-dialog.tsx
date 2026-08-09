import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { assets as assetsApi } from '@/lib/api'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { formatCurrency } from '@/lib/format'
import { Upload, FileText } from 'lucide-react'
import type { B3ImportPreviewResponse } from '@/types'

export function B3ImportDialog({
  open,
  onOpenChange,
  locale,
  onImported,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  locale: string
  onImported: () => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [preview, setPreview] = useState<B3ImportPreviewResponse | null>(null)
  const [fileName, setFileName] = useState<string | null>(null)

  const previewMutation = useMutation({
    mutationFn: (file: File) => assetsApi.importB3Preview(file),
    onSuccess: setPreview,
    onError: (e) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(detail || t('assets.b3ImportParseError'))
      setPreview(null)
      setFileName(null)
    },
  })

  const applyMutation = useMutation({
    mutationFn: () => assetsApi.importB3Apply(preview!.rows, preview!.income_rows),
    onSuccess: (result) => {
      queryClient.refetchQueries({ queryKey: ['assets'] })
      queryClient.refetchQueries({ queryKey: ['portfolio-trend'] })
      queryClient.refetchQueries({ queryKey: ['income'] })
      if (result.errors.length === 0) {
        const parts = [t('assets.b3ImportApplied', { count: result.applied_count })]
        if (result.income_applied_count > 0) {
          parts.push(t('assets.incomeFetchApplied', { count: result.income_applied_count }))
        }
        toast.success(parts.join(' '))
      } else {
        toast.warning(
          t('assets.b3ImportAppliedWithErrors', { applied: result.applied_count, errors: result.errors.length }),
        )
      }
      onImported()
      handleClose()
    },
    onError: () => toast.error(t('common.error')),
  })

  function handleFileSelect(file: File) {
    setFileName(file.name)
    setPreview(null)
    previewMutation.mutate(file)
  }

  function handleClose() {
    setPreview(null)
    setFileName(null)
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : handleClose())}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('assets.b3ImportTitle')}</DialogTitle>
        </DialogHeader>

        {!fileName ? (
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border p-8 text-muted-foreground hover:border-primary hover:text-primary transition-colors"
          >
            <Upload size={24} />
            <span className="text-sm">{t('assets.b3ImportSelectFile')}</span>
            <span className="text-[11px]">{t('assets.b3ImportHint')}</span>
          </button>
        ) : previewMutation.isPending ? (
          <div className="space-y-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : preview ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <FileText size={14} />
              <span className="truncate">{fileName}</span>
            </div>

            {preview.tickers.length === 0 && preview.income_rows.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">{t('assets.b3ImportNoRows')}</p>
            ) : preview.tickers.length > 0 ? (
              <div className="max-h-64 overflow-y-auto rounded-lg border border-border divide-y divide-border">
                {preview.tickers.map((tk) => (
                  <div key={tk.ticker} className="p-2.5 text-sm flex items-center justify-between gap-2">
                    <div>
                      <span className="font-medium text-foreground">{tk.ticker}</span>
                      <span className="ml-2 text-[11px] text-muted-foreground">
                        {tk.buy_quantity > 0 && `${t('assets.txBuy')} ${tk.buy_quantity} @ ${formatCurrency(tk.buy_average_price, 'BRL', locale)}`}
                        {tk.buy_quantity > 0 && tk.sell_quantity > 0 && ' · '}
                        {tk.sell_quantity > 0 && `${t('assets.txSell')} ${tk.sell_quantity} @ ${formatCurrency(tk.sell_average_price, 'BRL', locale)}`}
                      </span>
                    </div>
                    <span className="text-[11px] text-muted-foreground shrink-0">{tk.row_count}x</span>
                  </div>
                ))}
              </div>
            ) : null}

            {preview.income_rows.length > 0 && (
              <p className="text-[11px] text-muted-foreground">
                {t('assets.b3ImportIncomeFound', { count: preview.income_rows.length })}
              </p>
            )}

            {preview.skipped_count > 0 && (
              <p className="text-[11px] text-muted-foreground">
                {t('assets.b3ImportSkipped', { count: preview.skipped_count })}
                {' — '}
                {Object.entries(preview.skipped_kinds).map(([kind, n]) => `${kind} (${n})`).join(', ')}
              </p>
            )}
          </div>
        ) : null}

        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,.xlsx"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) handleFileSelect(file)
            e.target.value = ''
          }}
        />

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>{t('common.cancel')}</Button>
          <Button
            disabled={!preview || (preview.rows.length === 0 && preview.income_rows.length === 0) || applyMutation.isPending}
            onClick={() => applyMutation.mutate()}
          >
            {applyMutation.isPending ? t('common.saving') : t('assets.b3ImportConfirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
