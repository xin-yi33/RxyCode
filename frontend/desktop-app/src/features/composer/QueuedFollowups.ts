import { MoreHorizontal, RotateCw, Trash2 } from 'lucide-react'
import { createElement, useState, type ReactElement } from 'react'
import type { PendingItem } from './pending.queue.ts'

export function QueuedFollowups(props: {
  items: readonly PendingItem[]
  onSendNow: (id: string) => void
  onDelete: (id: string) => void
  onEdit: (id: string) => void
  onOpenSideChat: (id: string) => void
  onTurnOff: () => void
}): ReactElement | null {
  const [menuId, setMenuId] = useState<string | null>(null)
  if (props.items.length === 0) return null
  return createElement(
    'ul',
    { className: 'queued-followups', 'data-testid': 'queued-followups' },
    props.items.map((item) =>
      createElement(
        'li',
        { key: item.id, className: 'queued-followup', 'data-testid': `queued-followup-${item.id}` },
        createElement('span', { className: 'queued-followup-text' }, item.text),
        createElement(
          'div',
          { className: 'queued-followup-actions' },
          createElement(
            'button',
            {
              type: 'button',
              className: 'queued-followup-send-now',
              'data-testid': `queue-send-now-${item.id}`,
              title: '提交，但不中断模型运行',
              onClick: () => props.onSendNow(item.id)
            },
            createElement(RotateCw, { size: 14, 'aria-hidden': true }),
            '调整方向'
          ),
          createElement(
            'button',
            {
              type: 'button',
              className: 'queued-followup-icon',
              'data-testid': `queue-delete-${item.id}`,
              'aria-label': '删除排队的消息',
              onClick: () => props.onDelete(item.id)
            },
            createElement(Trash2, { size: 14, 'aria-hidden': true })
          ),
          createElement(
            'div',
            { className: 'queued-followup-more-wrap' },
            createElement(
              'button',
              {
                type: 'button',
                className: 'queued-followup-icon',
                'data-testid': `queue-more-${item.id}`,
                'aria-label': '排队消息操作',
                onClick: () => setMenuId((current) => (current === item.id ? null : item.id))
              },
              createElement(MoreHorizontal, { size: 14, 'aria-hidden': true })
            ),
            menuId === item.id
              ? createElement(
                  'div',
                  { className: 'queued-followup-menu', 'data-testid': `queue-menu-${item.id}` },
                  createElement(
                    'button',
                    { type: 'button', onClick: () => { props.onEdit(item.id); setMenuId(null) } },
                    '编辑消息'
                  ),
                  createElement(
                    'button',
                    { type: 'button', onClick: () => { props.onOpenSideChat(item.id); setMenuId(null) } },
                    '在侧边聊天中打开'
                  ),
                  createElement(
                    'button',
                    { type: 'button', onClick: () => { props.onTurnOff(); setMenuId(null) } },
                    '关闭排队'
                  )
                )
              : null
          )
        )
      )
    )
  )
}
