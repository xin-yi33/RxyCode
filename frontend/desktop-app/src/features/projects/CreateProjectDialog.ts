import { Monitor, X } from 'lucide-react'
import { createElement, type ReactElement } from 'react'
import {
  canAdvanceProjectType,
  canSubmitLocalProject,
  projectNameFromFolder,
  type CreateProjectDraft
} from './createProject.ts'

export function CreateProjectDialog(props: {
  draft: CreateProjectDraft
  onChange: (next: CreateProjectDraft) => void
  onPickFolder: () => void
  onCancel: () => void
  onSubmit: () => void
}): ReactElement {
  if (props.draft.step === 'type') {
    return createElement(
      'div',
      { className: 'create-project-overlay', 'data-testid': 'create-project', role: 'dialog' },
      createElement('button', { type: 'button', className: 'sheet-backdrop', 'aria-label': '关闭', onClick: props.onCancel }),
      createElement(
        'div',
        { className: 'create-project-dialog' },
        createElement(
          'header',
          { className: 'create-project-head' },
          createElement('h2', null, '创建项目'),
          createElement('button', { type: 'button', className: 'create-project-close', onClick: props.onCancel }, createElement(X, { size: 16 }))
        ),
        createElement('p', { className: 'create-project-kicker' }, '项目类型'),
        createElement(
          'div',
          { className: 'create-project-kinds' },
          createElement(
            'button',
            {
              type: 'button',
              className: 'create-project-kind' + (props.draft.kind === 'local' ? ' is-selected' : ''),
              'data-testid': 'create-project-local',
              onClick: () => props.onChange({ ...props.draft, kind: 'local' })
            },
            createElement(Monitor, { size: 22, 'aria-hidden': true }),
            createElement('span', { className: 'create-project-radio', 'aria-hidden': true }),
            createElement('strong', null, '本地'),
            createElement('span', null, '在你的电脑上编辑、运行和测试文件')
          ),
          createElement(
            'button',
            {
              type: 'button',
              className: 'create-project-kind' + (props.draft.kind === 'remote' ? ' is-selected' : ''),
              'data-testid': 'create-project-remote',
              onClick: () => props.onChange({ ...props.draft, kind: 'remote' })
            },
            createElement('span', { className: 'create-project-globe', 'aria-hidden': true }, '◎'),
            createElement('span', { className: 'create-project-radio', 'aria-hidden': true }),
            createElement('strong', null, '远程'),
            createElement('span', null, '选择已连接计算机上的文件夹')
          )
        ),
        createElement(
          'footer',
          { className: 'create-project-foot' },
          createElement(
            'button',
            {
              type: 'button',
              className: 'create-project-next',
              'data-testid': 'create-project-next',
              disabled: !canAdvanceProjectType(props.draft),
              onClick: () => props.onChange({ ...props.draft, step: 'details' })
            },
            '下一步'
          )
        )
      )
    )
  }
  return createElement(
    'div',
    { className: 'create-project-overlay', 'data-testid': 'create-project', role: 'dialog' },
    createElement('button', { type: 'button', className: 'sheet-backdrop', 'aria-label': '关闭', onClick: props.onCancel }),
    createElement(
      'div',
      { className: 'create-project-dialog' },
      createElement(
        'header',
        { className: 'create-project-head' },
        createElement('h2', null, '创建项目'),
        createElement('button', { type: 'button', className: 'create-project-close', onClick: props.onCancel }, createElement(X, { size: 16 }))
      ),
      createElement('input', {
        className: 'create-project-name',
        'data-testid': 'create-project-name',
        placeholder: '项目名称',
        value: props.draft.name,
        onChange: (event: { target: { value: string } }) => props.onChange({ ...props.draft, name: event.target.value })
      }),
      createElement('p', { className: 'create-project-kicker' }, '源文件夹'),
      createElement('input', {
        className: 'create-project-folder-path',
        'data-testid': 'create-project-folder-path',
        placeholder: '文件夹路径',
        value: props.draft.folder,
        onChange: (event: { target: { value: string } }) => {
          const folder = event.target.value
          props.onChange({
            ...props.draft,
            folder,
            name: props.draft.name.trim() === '' ? projectNameFromFolder(folder) : props.draft.name
          })
        }
      }),
      createElement(
        'button',
        {
          type: 'button',
          className: 'create-project-folder',
          'data-testid': 'create-project-folder',
          onClick: props.onPickFolder
        },
        props.draft.folder === '' ? '添加 RxyCode 可读取和编辑的文件夹' : props.draft.folder
      ),
      createElement(
        'footer',
        { className: 'create-project-foot' },
        createElement('button', { type: 'button', className: 'create-project-cancel', onClick: props.onCancel }, '取消'),
        createElement(
          'button',
          {
            type: 'button',
            className: 'create-project-submit',
            'data-testid': 'create-project-submit',
            disabled: !canSubmitLocalProject(props.draft),
            onClick: props.onSubmit
          },
          '创建项目'
        )
      )
    )
  )
}
