import { createElement, type ReactElement } from 'react'
import { REVIEW_SCOPES, type ReviewScope } from './review.comments.ts'

export function ReviewScopeSelector(props: {
  value: ReviewScope
  onChange: (scope: ReviewScope) => void
}): ReactElement {
  return createElement(
    'select',
    {
      'data-testid': 'review-scope',
      'aria-label': 'Review scope',
      value: props.value,
      onChange: (event: React.ChangeEvent<HTMLSelectElement>) =>
        props.onChange(event.target.value as ReviewScope)
    },
    REVIEW_SCOPES.map((scope) => createElement('option', { key: scope, value: scope }, scope))
  )
}
