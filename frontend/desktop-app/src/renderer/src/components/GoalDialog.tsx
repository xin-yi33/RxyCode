import { useEffect, useRef } from 'react'
import { useI18n } from '../../../i18n/I18nContext.tsx'

interface GoalDialogProps {
  open: boolean
  value: string
  onChange: (value: string) => void
  onClose: () => void
  onSave: () => void
  onClear: () => void
}

function GoalDialog({
  open,
  value,
  onChange,
  onClose,
  onSave,
  onClear
}: GoalDialogProps): React.JSX.Element | null {
  const { t } = useI18n()
  const inputRef = useRef<HTMLTextAreaElement | null>(null)

  useEffect(() => {
    if (!open) return
    inputRef.current?.focus()
    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      event.stopPropagation()
      onClose()
    }
    window.addEventListener('keydown', closeOnEscape, true)
    return () => window.removeEventListener('keydown', closeOnEscape, true)
  }, [open, onClose])

  if (!open) return null
  return (
    <div
      className="confirm-overlay"
      role="presentation"
      data-testid="goal-dialog"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="confirm-dialog goal-dialog" role="dialog" aria-modal="true" aria-labelledby="goal-title">
        <h2 id="goal-title">{t('goalTitle')}</h2>
        <p>{t('goalBody')}</p>
        <textarea
          ref={inputRef}
          data-testid="goal-input"
          aria-label={t('goal')}
          placeholder="/goal 例如：把登录流程做成可演示的产品"
          value={value}
          rows={4}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
              event.preventDefault()
              onSave()
            }
          }}
        />
        <div className="confirm-actions">
          <button type="button" onClick={onClose}>{t('cancel')}</button>
          <button type="button" data-testid="goal-clear" onClick={onClear}>{t('clear')}</button>
          <button type="button" className="primary-action" data-testid="goal-save" onClick={onSave}>{t('goalSave')}</button>
        </div>
      </div>
    </div>
  )
}

export default GoalDialog
