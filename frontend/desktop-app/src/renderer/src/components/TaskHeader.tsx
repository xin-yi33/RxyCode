import { FolderGit2, GitBranch, Sparkles, Users } from 'lucide-react'
import { TitleMarquee } from '../../../features/sessions/TitleMarquee.ts'
import { useI18n } from '../../../i18n/I18nContext.tsx'

interface TaskHeaderProps {
  title: string
  workspaceRoot: string
  modelLabel: string
  runState: string
  activeTeamLabel?: string | null
}

function TaskHeader({
  title,
  workspaceRoot,
  modelLabel,
  runState,
  activeTeamLabel
}: TaskHeaderProps): React.JSX.Element {
  const { t } = useI18n()
  return (
    <header className="task-header">
      <div>
        <p className="task-kicker">{t('task')}</p>
        <h1><TitleMarquee text={title} /></h1>
      </div>
      <div className="task-metadata" aria-label={t('task')}>
        <span title={workspaceRoot}>
          <FolderGit2 aria-hidden="true" size={14} />
          {workspaceRoot === '' ? t('noWorkspace') : workspaceRoot}
        </span>
        <span>
          <GitBranch aria-hidden="true" size={14} />
          workspace
        </span>
        <span>
          <Sparkles aria-hidden="true" size={14} />
          {modelLabel}
        </span>
        {activeTeamLabel != null && activeTeamLabel !== '' ? (
          <span className="task-team-badge" data-testid="task-team-badge">
            <Users aria-hidden="true" size={14} />
            {activeTeamLabel}
          </span>
        ) : null}
        <span className={'task-status state-' + runState}>{runState.replace('_', ' ')}</span>
      </div>
    </header>
  )
}

export default TaskHeader
