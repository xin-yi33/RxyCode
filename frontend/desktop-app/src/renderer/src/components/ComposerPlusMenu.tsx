import { Check, Folder, Lightbulb, Paperclip, Target } from 'lucide-react'
import { useI18n } from '../../../i18n/I18nContext.tsx'

interface ComposerPlusMenuProps {
  open: boolean
  planMode: boolean
  onClose: () => void
  onAttachFile: () => void
  onPickWorkspace: () => void
  onOpenGoal: () => void
  onTogglePlanMode: () => void
}

function ComposerPlusMenu({
  open,
  planMode,
  onClose,
  onAttachFile,
  onPickWorkspace,
  onOpenGoal,
  onTogglePlanMode
}: ComposerPlusMenuProps): React.JSX.Element | null {
  const { t } = useI18n()
  if (!open) return null
  return (
    <div className="composer-plus-menu" role="menu" data-testid="composer-plus-menu">
      <p className="composer-plus-heading">{t('composerAdd')}</p>
      <button type="button" role="menuitem" data-testid="plus-attach" onClick={() => { onAttachFile(); onClose() }}>
        <Paperclip aria-hidden="true" size={16} />
        <span>
          <strong>{t('attachFile')}</strong>
          <small>{t('attachFileHint')}</small>
        </span>
      </button>
      <button type="button" role="menuitem" data-testid="plus-workspace" onClick={() => { onPickWorkspace(); onClose() }}>
        <Folder aria-hidden="true" size={16} />
        <span>
          <strong>{t('useInProject')}</strong>
          <small>{t('useInProjectHint')}</small>
        </span>
      </button>
      <button type="button" role="menuitem" data-testid="plus-goal" onClick={() => { onOpenGoal(); onClose() }}>
        <Target aria-hidden="true" size={16} />
        <span>
          <strong>{t('goal')}</strong>
          <small>{t('goalHint')}</small>
        </span>
      </button>
      <button
        type="button"
        role="menuitem"
        data-testid="plus-plan-mode"
        className={planMode ? 'is-active' : undefined}
        onClick={() => { onTogglePlanMode(); onClose() }}
      >
        <Lightbulb aria-hidden="true" size={16} />
        <span>
          <strong>{t('planMode')}</strong>
          <small>{planMode ? t('planModeOnHint') : t('planModeOffHint')}</small>
        </span>
        {planMode ? <Check aria-hidden="true" size={14} /> : null}
      </button>
    </div>
  )
}

export default ComposerPlusMenu
