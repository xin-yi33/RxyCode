import { Check, ChevronRight, Folder, Lightbulb, Paperclip, Plus, Target } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useI18n } from '../../../i18n/I18nContext.tsx'
import type { TeamRecord } from '../../../features/team/team.visual.ts'
import { teamOneLiner } from '../../../features/team/team.model.ts'
import { teamPortraitSrc } from '../../../features/team/team.portraits.ts'
import { TeamDetailCard } from '../../../features/team/TeamPicker.ts'

interface ComposerPlusMenuProps {
  open: boolean
  planMode: boolean
  teams?: readonly TeamRecord[]
  activeTeamId?: string | null
  onClose: () => void
  onAttachFile: () => void
  onPickWorkspace: () => void
  onOpenGoal: () => void
  onTogglePlanMode: () => void
  onSummonTeam?: (teamId: string) => void
  onCreateTeam?: () => void
}

function TeamAvatar({ teamId, name }: { teamId: string; name: string }): React.JSX.Element {
  const src = teamPortraitSrc(teamId)
  if (src !== null && src !== '') {
    return <img className="summon-avatar" src={src} alt="" aria-hidden="true" />
  }
  return <span className="summon-avatar summon-avatar-fallback" aria-hidden="true">{name.trim().slice(0, 1) || '?'}</span>
}

function ComposerPlusMenu({
  open,
  planMode,
  teams = [],
  activeTeamId = null,
  onClose,
  onAttachFile,
  onPickWorkspace,
  onOpenGoal,
  onTogglePlanMode,
  onSummonTeam,
  onCreateTeam
}: ComposerPlusMenuProps): React.JSX.Element | null {
  const { t } = useI18n()
  const [view, setView] = useState<'root' | 'summon' | 'detail'>('root')
  const [detailId, setDetailId] = useState<string | null>(null)
  useEffect(() => {
    if (!open) {
      setView('root')
      setDetailId(null)
    }
  }, [open])
  if (!open) return null
  const detail = teams.find((team) => team.id === detailId) ?? null
  const featured = teams.find((team) => team.id === activeTeamId) ?? teams[0] ?? null
  return (
    <div className="composer-plus-menu" role="menu" data-testid="composer-plus-menu" data-view={view}>
      {view === 'root' ? (
        <>
          <p className="composer-plus-heading">{t('composerAdd')}</p>
          <button type="button" role="menuitem" data-testid="plus-attach" onClick={() => { onAttachFile(); onClose(); setView('root') }}>
            <Paperclip aria-hidden="true" size={16} />
            <span>
              <strong>{t('attachFile')}</strong>
              <small>{t('attachFileHint')}</small>
            </span>
          </button>
          <button type="button" role="menuitem" data-testid="plus-workspace" onClick={() => { onPickWorkspace(); onClose(); setView('root') }}>
            <Folder aria-hidden="true" size={16} />
            <span>
              <strong>{t('useInProject')}</strong>
              <small>{t('useInProjectHint')}</small>
            </span>
          </button>
          <button type="button" role="menuitem" data-testid="plus-goal" onClick={() => { onOpenGoal(); onClose(); setView('root') }}>
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
            onClick={() => { onTogglePlanMode(); onClose(); setView('root') }}
          >
            <Lightbulb aria-hidden="true" size={16} />
            <span>
              <strong>{t('planMode')}</strong>
              <small>{planMode ? t('planModeOnHint') : t('planModeOffHint')}</small>
            </span>
            {planMode ? <Check aria-hidden="true" size={14} /> : null}
          </button>
          <button
            type="button"
            role="menuitem"
            className="summon-entry"
            data-testid="plus-summon-team"
            onClick={() => setView('summon')}
          >
            {featured !== undefined && featured !== null ? (
              <TeamAvatar teamId={featured.id} name={featured.name} />
            ) : (
              <span className="summon-avatar summon-avatar-fallback" aria-hidden="true">+</span>
            )}
            <span>
              <strong>{featured?.name ?? t('summonTeam')}</strong>
              <small>{featured !== undefined && featured !== null ? teamOneLiner(featured) : t('summonTeamHint')}</small>
            </span>
            <ChevronRight aria-hidden="true" size={16} />
          </button>
        </>
      ) : null}
      {view === 'summon' ? (
        <div className="summon-flyout" data-testid="plus-summon-flyout">
          <p className="composer-plus-heading">{t('recentSummoned')}</p>
          {teams.map((team) => (
            <button
              key={team.id}
              type="button"
              role="menuitem"
              className={'summon-entry' + (team.id === activeTeamId ? ' is-active' : '')}
              data-testid={`plus-summon-${team.id}`}
              onClick={() => {
                setDetailId(team.id)
                setView('detail')
              }}
            >
              <TeamAvatar teamId={team.id} name={team.name} />
              <span>
                <strong>{team.name}</strong>
                <small>{teamOneLiner(team)}</small>
              </span>
              {team.id === activeTeamId ? <Check aria-hidden="true" size={14} /> : null}
            </button>
          ))}
          <button
            type="button"
            role="menuitem"
            className="summon-entry summon-others"
            data-testid="plus-summon-others"
            onClick={() => setView('root')}
          >
            <span className="summon-plus-badge" aria-hidden="true"><Plus size={14} /></span>
            <span>
              <strong>{t('summonOtherExperts')}</strong>
            </span>
          </button>
          <button
            type="button"
            role="menuitem"
            data-testid="plus-create-team"
            onClick={() => {
              onCreateTeam?.()
              onClose()
              setView('root')
            }}
          >
            <span>
              <strong>{t('createTeam')}</strong>
              <small>{t('createTeamHint')}</small>
            </span>
          </button>
          <button type="button" role="menuitem" data-testid="plus-summon-back" onClick={() => setView('root')}>
            <span><strong>{t('cancel')}</strong></span>
          </button>
        </div>
      ) : null}
      {view === 'detail' && detail !== null ? (
        <div className="composer-plus-team-detail" data-testid="plus-team-detail">
          <TeamDetailCard team={detail} />
          <button
            type="button"
            data-testid="plus-summon-use"
            onClick={() => {
              onSummonTeam?.(detail.id)
              onClose()
              setView('root')
            }}
          >
            {t('summonTeam')}
          </button>
          <button type="button" onClick={() => setView('summon')}>{t('cancel')}</button>
        </div>
      ) : null}
    </div>
  )
}

export default ComposerPlusMenu
