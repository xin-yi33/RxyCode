import { useEffect, useState } from 'react'
import { useI18n } from '../../../i18n/I18nContext.tsx'
import type { ApprovalActionScope, ApprovalExpiryHours } from '../lib/approvalPolicy.mts'
import type { ApprovalRequestItem } from '../lib/conversationStore.mts'

interface ApprovalModalProps {
  item: ApprovalRequestItem
  onApprove: () => void
  onReject: () => void
  onAlwaysAllow: (scope: ApprovalActionScope, expiresInHours: ApprovalExpiryHours) => void
  onDismiss: () => void
}

function ApprovalModal({
  item,
  onApprove,
  onReject,
  onAlwaysAllow,
  onDismiss
}: ApprovalModalProps): React.JSX.Element {
  const { t } = useI18n()
  const [formOpen, setFormOpen] = useState(false)
  const [scope, setScope] = useState<ApprovalActionScope>('exact')
  const [expiresInHours, setExpiresInHours] = useState<ApprovalExpiryHours>(24)
  const expiryOptions: Array<{ value: ApprovalExpiryHours; label: string }> = [
    { value: 1, label: t('expiry1h') },
    { value: 24, label: t('expiry24h') },
    { value: 168, label: t('expiry7d') }
  ]
  const scopeOptions: Array<{ value: ApprovalActionScope; label: string; hint: string }> = [
    { value: 'exact', label: t('scopeExact'), hint: t('scopeExactHint') },
    { value: 'prefix', label: t('scopePrefix'), hint: t('scopePrefixHint') },
    { value: 'any', label: t('scopeAny'), hint: t('scopeAnyHint') }
  ]

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      onDismiss()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onDismiss])

  if (item.status === 'error') {
    return (
      <div className="approval-overlay">
        <div className="approval-dialog error" role="dialog" aria-modal="true">
          <div className="approval-header">
            <span className="approval-title">{t('approvalFailed')}</span>
          </div>
          <div className="approval-action">{item.action}</div>
          <div className="approval-error-message">
            {item.error ?? t('approvalDisconnect')}
          </div>
          <div className="approval-actions">
            <button type="button" className="approval-dismiss" onClick={onDismiss}>
              {t('close')}
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="approval-overlay">
      <div className="approval-dialog" role="dialog" aria-modal="true">
        <div className="approval-header">
          <span className={`approval-risk ${item.riskLevel.toLowerCase()}`}>{item.riskLevel}</span>
          <span className="approval-title">{t('approvalRequest')}</span>
        </div>
        <div className="approval-action">{item.action}</div>
        {item.details !== undefined && Object.keys(item.details).length > 0 && (
          <pre className="approval-details">{JSON.stringify(item.details, null, 2)}</pre>
        )}

        {item.status === 'submitting' ? (
          <div className="approval-submitting">{t('submitting')}</div>
        ) : formOpen ? (
          <div className="approval-scope-form">
            <div className="approval-form-label">{t('alwaysAllowScope')}</div>
            {scopeOptions.map((option) => (
              <label key={option.value} className="approval-scope-option">
                <input
                  type="radio"
                  name="approval-scope"
                  value={option.value}
                  checked={scope === option.value}
                  onChange={() => setScope(option.value)}
                />
                <span>
                  <span className="approval-scope-name">{option.label}</span>
                  <span className="approval-scope-hint">{option.hint}</span>
                </span>
              </label>
            ))}
            <div className="approval-form-label">{t('expiry')}</div>
            <select
              className="approval-expiry"
              value={expiresInHours}
              onChange={(event) =>
                setExpiresInHours(Number(event.target.value) as ApprovalExpiryHours)
              }
            >
              {expiryOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <div className="approval-actions">
              <button
                type="button"
                className="save-rule"
                onClick={() => onAlwaysAllow(scope, expiresInHours)}
              >
                {t('saveAndAllow')}
              </button>
              <button type="button" className="cancel-rule" onClick={() => setFormOpen(false)}>
                {t('cancel')}
              </button>
            </div>
          </div>
        ) : (
          <div className="approval-actions">
            <button type="button" className="approve" onClick={onApprove}>
              {t('approve')}
            </button>
            <button type="button" className="reject" onClick={onReject}>
              {t('reject')}
            </button>
            <button type="button" className="always-allow" onClick={() => setFormOpen(true)}>
              {t('alwaysAllow')}…
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export default ApprovalModal
