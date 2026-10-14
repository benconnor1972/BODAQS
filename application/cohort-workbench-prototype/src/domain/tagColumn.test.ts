import { describe, expect, it } from 'vitest'
import { fixtureSessions } from '../data/fixtures'
import { emptySessionAnnotations } from './sessionAnnotations'
import { allColumns, columnGroups, getColumnText, matchesSearch, normalizeColumnSelection, sortSessions } from './sessionCatalog'
import { applyTableColumnFilters, tableColumnFilterOptions } from './tableFilters'

describe('Tags column', () => {
  const wet = { ...fixtureSessions[0], userAnnotations: { ...emptySessionAnnotations(fixtureSessions[0]), tags: ['wet', 'test, one'] } }
  const dry = { ...fixtureSessions[1], userAnnotations: { ...emptySessionAnnotations(fixtureSessions[1]), tags: ['dry'] } }
  it('is selectable, searchable and sortable', () => {
    expect(allColumns).toContain('tags')
    expect(columnGroups.some((group) => group.columns.includes('tags'))).toBe(true)
    expect(normalizeColumnSelection(['name', 'tags'])).toEqual(['name', 'tags'])
    expect(getColumnText(wet, 'tags', [])).toBe('wet, test, one')
    expect(matchesSearch(wet, 'wet', ['tags'], [])).toBe(true)
    expect(sortSessions([wet, dry], 'tags', 'asc', [])).toEqual([dry, wet])
    expect(getColumnText(fixtureSessions[0], 'tags', [])).toBe('')
  })
  it('filters by individual whole tags, preserving commas in names', () => {
    expect(tableColumnFilterOptions([wet, dry], 'tags', [])).toEqual(['dry', 'test, one', 'wet'])
    expect(applyTableColumnFilters([wet, dry], [{ columnId: 'tags', values: ['WET'] }], [])).toEqual([wet])
    expect(applyTableColumnFilters([wet, dry], [{ columnId: 'tags', values: ['test, one'] }], [])).toEqual([wet])
  })
})
