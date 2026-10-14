import { describe, expect, it } from 'vitest'
import { fixtureSessions } from '../data/fixtures'
import { emptySessionAnnotations } from './sessionAnnotations'
import { annotationFilterPredicate, emptyAnnotationFilter } from './annotationFilters'
import { applySavedSessionFilters, type SessionFilterPredicate } from './sessionFilters'

function matches(predicate: SessionFilterPredicate, changes = {}) {
  const session = { ...fixtureSessions[0], userAnnotations: { ...emptySessionAnnotations(fixtureSessions[0]), tags: ['wet', 'setup test'], ...changes } }
  return applySavedSessionFilters([session], [{ id: 'test', displayName: '', description: '', category: 'custom', origin: 'api_saved', revision: 1, predicate }]).length > 0
}

describe('Annotation filters', () => {
  it('matches entire tags with any/all and ignores case', () => {
    expect(matches({ field: 'tags', op: 'in', value: ['WET', 'dry'] })).toBe(true)
    expect(matches({ field: 'tags', op: 'in', value: ['we'] })).toBe(false)
    expect(matches({ field: 'tags', op: 'all', value: ['wet', 'setup test'] })).toBe(true)
    expect(matches({ field: 'tags', op: 'all', value: ['wet', 'dry'] })).toBe(false)
    expect(matches({ field: 'tags', op: 'all', value: [] })).toBe(false)
  })
  it('combines tags and flags and excludes unknown statuses from unflagged filters', () => {
    const any = annotationFilterPredicate({ tags: ['wet'], tagMatch: 'in', issues: 'any' })!
    expect(matches(any, { qaIssue: { flagged: true, explanation: '' } })).toBe(true)
    expect(matches(any)).toBe(false)
    const none = annotationFilterPredicate({ ...emptyAnnotationFilter, issues: 'none' })!
    expect(matches(none)).toBe(true)
    expect(matches(none, { gpsIssue: null })).toBe(false)
    expect(annotationFilterPredicate(emptyAnnotationFilter)).toBeNull()
  })
})
