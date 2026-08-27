import { useEffect, useState } from 'react'
import { useI18n } from '../../../i18n/I18nContext.tsx'
import type { QuestionRequest } from '@rxycode/protocol-client'

interface QuestionModalProps {
  request: QuestionRequest
  onAnswer: (answer: string) => void
  onCancel: () => void
}

function QuestionModal({ request, onAnswer, onCancel }: QuestionModalProps): React.JSX.Element {
  const { t } = useI18n()
  const options = request.options ?? []
  const hasOptions = options.length > 0
  const [draft, setDraft] = useState('')

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      onCancel()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onCancel])

  return (
    <div className="approval-overlay">
      <div className="approval-dialog" role="dialog" aria-modal="true">
        <div className="approval-header">
          <span className="approval-title">{request.header || t('needChoice')}</span>
        </div>
        <div className="approval-action">{request.question}</div>
        {hasOptions ? (
          <div className="approval-actions" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
            {options.map((option) => (
              <button
                key={option.value}
                type="button"
                className="approval-approve"
                onClick={() => onAnswer(option.value)}
              >
                {option.label}
              </button>
            ))}
            <button type="button" className="approval-reject" onClick={onCancel}>
              {t('cancel')}
            </button>
          </div>
        ) : (
          <form
            className="approval-actions"
            style={{ flexDirection: 'column', alignItems: 'stretch' }}
            onSubmit={(event) => {
              event.preventDefault()
              onAnswer(draft.trim())
            }}
          >
            <input
              autoFocus
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={t('answerPlaceholder')}
            />
            <div className="approval-actions">
              <button type="submit" className="approval-approve" disabled={!draft.trim()}>
                {t('submitAnswer')}
              </button>
              <button type="button" className="approval-reject" onClick={onCancel}>
                {t('cancel')}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

export default QuestionModal
