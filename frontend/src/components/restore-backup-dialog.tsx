import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useNavigate } from 'react-router-dom'
import { backup as backupApi, type BackupPreview } from '@/lib/api'
import { useWorkspace } from '@/contexts/workspace-context'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Upload, FileArchive } from 'lucide-react'

// Entity keys that map onto an existing nav label — everything else in
// entity_counts gets folded into a single "+ N other records" line rather
// than adding a dozen more translation keys just for a confirmation dialog.
const ENTITY_LABEL_KEY: Record<string, string> = {
  accounts: 'nav.accounts',
  transactions: 'nav.transactions',
  categories: 'nav.categories',
  budgets: 'nav.budgets',
  rules: 'nav.rules',
  recurring_transactions: 'nav.recurring',
  assets: 'nav.assets',
}

export function RestoreBackupDialog({
  open,
  onOpenChange,
  dateLocale,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  dateLocale: string
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { refresh, switchWorkspace } = useWorkspace()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<BackupPreview | null>(null)

  const previewMutation = useMutation({
    mutationFn: (f: File) => backupApi.restorePreview(f),
    onSuccess: setPreview,
    onError: (e) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(detail || t('backup.restoreInvalidFile'))
      setFile(null)
      setPreview(null)
    },
  })

  const restoreMutation = useMutation({
    mutationFn: () => backupApi.restore(file!),
    onSuccess: async (workspace) => {
      toast.success(t('backup.restoreSuccess', { name: workspace.name }))
      await refresh()
      await switchWorkspace(workspace.id)
      handleClose()
      navigate('/')
    },
    onError: (e) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(detail || t('backup.restoreError'))
    },
  })

  function handleFileSelect(f: File) {
    setFile(f)
    setPreview(null)
    previewMutation.mutate(f)
  }

  function handleClose() {
    setFile(null)
    setPreview(null)
    onOpenChange(false)
  }

  const knownEntries = preview
    ? Object.entries(preview.entity_counts).filter(([key, count]) => count > 0 && ENTITY_LABEL_KEY[key])
    : []
  const otherCount = preview
    ? Object.entries(preview.entity_counts)
        .filter(([key, count]) => count > 0 && !ENTITY_LABEL_KEY[key])
        .reduce((acc, [, count]) => acc + count, 0)
    : 0

  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : handleClose())}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('backup.restoreTitle')}</DialogTitle>
          <DialogDescription>{t('backup.restoreDescription')}</DialogDescription>
        </DialogHeader>

        {!file ? (
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border p-8 text-muted-foreground hover:border-primary hover:text-primary transition-colors"
          >
            <Upload size={24} />
            <span className="text-sm">{t('backup.restoreSelectFile')}</span>
          </button>
        ) : previewMutation.isPending ? (
          <div className="space-y-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : preview ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <FileArchive size={14} />
              <span className="truncate">{file.name}</span>
            </div>

            <div className="rounded-lg border border-border p-3 space-y-1.5 text-sm">
              <p className="font-medium text-foreground">{preview.workspace_name}</p>
              {preview.export_date && (
                <p className="text-[11px] text-muted-foreground">
                  {t('backup.restoreExportedAt', {
                    date: new Date(preview.export_date).toLocaleDateString(dateLocale, {
                      dateStyle: 'medium',
                    }),
                  })}
                </p>
              )}
              <ul className="text-[12px] text-muted-foreground pt-1 space-y-0.5">
                {knownEntries.map(([key, count]) => (
                  <li key={key}>{t(ENTITY_LABEL_KEY[key])}: {count}</li>
                ))}
                {otherCount > 0 && <li>{t('backup.restoreOtherRecords', { count: otherCount })}</li>}
              </ul>
            </div>

            <p className="text-[11px] text-muted-foreground">{t('backup.restoreNewWorkspaceNote')}</p>
          </div>
        ) : null}

        <input
          ref={fileInputRef}
          type="file"
          accept=".zip"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) handleFileSelect(f)
            e.target.value = ''
          }}
        />

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>{t('common.cancel')}</Button>
          <Button
            disabled={!preview || restoreMutation.isPending}
            onClick={() => restoreMutation.mutate()}
          >
            {restoreMutation.isPending ? t('common.loading') : t('backup.restoreConfirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
