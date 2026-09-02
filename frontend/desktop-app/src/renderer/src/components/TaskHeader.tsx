import { FolderGit2, GitBranch, Sparkles, Users } from 'lucide-react'
import { looksRecentWorkspace } from '../../../features/sessions/recentWorkspace.ts'
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
  const showWorkspace = !looksRecentWorkspace(workspaceRoot)
  return (
    <header className="task-header">
      <div>
        <p className="task-kicker">{t('task')}</p>
        <h1><TitleMarquee text={title} /></h1>
      </div>
      <div className="task-metadata" aria-label={t('task')}>
        {showWorkspace ? (
          <span title={workspaceRoot} data-testid="task-workspace">
            <FolderGit2 aria-hidden="true" size={14} />
            {workspaceRoot === '' ? t('noWorkspace') : workspaceRoot}
          </span>
        ) : null}
        {showWorkspace ? (
          <span>
            <GitBranch aria-hidden="true" size={14} />
            workspace
          </span>
        ) : null}
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
