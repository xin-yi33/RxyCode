import { useI18n } from '../../../i18n/I18nContext.tsx'
import type { ApprovalActionScope, ApprovalRule } from '../lib/approvalPolicy.mts'

interface ApprovalRulesModalProps {
  open: boolean
  rules: ApprovalRule[]
  onClose: () => void
  onRevoke: (ruleId: string) => void
}

function ApprovalRulesModal({
  open,
  rules,
  onClose,
  onRevoke
}: ApprovalRulesModalProps): React.JSX.Element | null {
  const { t } = useI18n()
  const scopeLabels: Record<ApprovalActionScope, string> = {
    any: t('scopeAny'),
    exact: t('scopeExact'),
    prefix: t('scopePrefix')
  }
  if (!open) return null
  return (
    <div className="approval-overlay">
      <div className="approval-dialog rules-dialog" role="dialog" aria-modal="true">
        <div className="approval-header">
          <span className="approval-title">{t('rulesTitle')}</span>
        </div>
        {rules.length === 0 ? (
          <div className="rules-empty">
            {t('rulesEmpty')}
          </div>
        ) : (
          <div className="rules-list">
            {rules.map((rule) => (
              <div key={rule.id} className="rule-item">
                <div className="rule-head">
                  <span className={`approval-risk ${rule.riskLevel.toLowerCase()}`}>
                    {rule.riskLevel}
                  </span>
                  <span className="rule-scope">{scopeLabels[rule.actionScope]}</span>
                  <button type="button" className="revoke-rule" onClick={() => onRevoke(rule.id)}>
                    {t('revoke')}
                  </button>
                </div>
                {rule.actionScope !== 'any' && <div className="rule-action">{rule.action}</div>}
                <div className="rule-meta">
                  工作区 {rule.workspaceRoot} · 有效期至 {new Date(rule.expiresAt).toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="approval-actions">
          <button type="button" className="rules-close" onClick={onClose}>
            关闭
          </button>
        </div>
      </div>
    </div>
  )
}

export default ApprovalRulesModal
