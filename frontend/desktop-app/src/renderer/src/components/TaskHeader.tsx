import { FolderGit2, GitBranch, Sparkles } from 'lucide-react'
import { useI18n } from '../../../i18n/I18nContext.tsx'

interface TaskHeaderProps {
  title: string
  workspaceRoot: string
  modelLabel: string
  runState: string
}

function TaskHeader({
  title,
  workspaceRoot,
  modelLabel,
  runState
}: TaskHeaderProps): React.JSX.Element {
  const { t } = useI18n()
  return (
    <header className="task-header">
      <div>
        <p className="task-kicker">{t('task')}</p>
        <h1>{title}</h1>
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
        <span className={'task-status state-' + runState}>{runState.replace('_', ' ')}</span>
      </div>
    </header>
  )
}

export default TaskHeader
