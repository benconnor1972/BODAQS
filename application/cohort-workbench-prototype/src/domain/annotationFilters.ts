import type { SessionFilterPredicate } from './sessionFilters'

export type AnnotationFilterSelection = { tags: string[]; tagMatch: 'in' | 'all'; issues: '' | 'gps' | 'qa' | 'any' | 'none' }
export const emptyAnnotationFilter: AnnotationFilterSelection = { tags: [], tagMatch: 'in', issues: '' }

export function annotationFilterPredicate(selection: AnnotationFilterSelection): SessionFilterPredicate | null {
  const children: SessionFilterPredicate[] = []
  if (selection.tags.length) children.push({ field: 'tags', op: selection.tagMatch, value: selection.tags })
  if (selection.issues === 'gps' || selection.issues === 'qa') children.push({ field: selection.issues === 'gps' ? 'user.gps_issue' : 'user.qa_issue', op: 'eq', value: true })
  if (selection.issues === 'none') children.push({ field: 'user.gps_issue', op: 'eq', value: false }, { field: 'user.qa_issue', op: 'eq', value: false })
  if (selection.issues === 'any') children.push({ op: 'or', children: [
    { field: 'user.gps_issue', op: 'eq', value: true }, { field: 'user.qa_issue', op: 'eq', value: true },
  ] })
  return children.length === 1 ? children[0] : children.length ? { op: 'and', children } : null
}
