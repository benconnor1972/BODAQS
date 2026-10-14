import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { emptyAnnotationFilter } from '../domain/annotationFilters'
import { AnnotationFilters } from './AnnotationFilters'
afterEach(cleanup)
it('offers tag suggestions, any/all matching, issue filters and saved-filter handoff', () => {
  const onChange = vi.fn(), onSave = vi.fn()
  render(<AnnotationFilters knownTags={['wet', 'dry']} value={{ ...emptyAnnotationFilter, tags: ['wet'] }} onChange={onChange} onSave={onSave} canSave />)
  fireEvent.click(screen.getByLabelText('dry'))
  expect(onChange).toHaveBeenLastCalledWith({ ...emptyAnnotationFilter, tags: ['wet', 'dry'] })
  fireEvent.change(screen.getByLabelText('Tag matching'), { target: { value: 'all' } })
  expect(onChange).toHaveBeenLastCalledWith({ ...emptyAnnotationFilter, tags: ['wet'], tagMatch: 'all' })
  fireEvent.change(screen.getByLabelText('User issues'), { target: { value: 'none' } })
  expect(onChange).toHaveBeenLastCalledWith({ ...emptyAnnotationFilter, tags: ['wet'], issues: 'none' })
  fireEvent.click(screen.getByText('Save as filter...'))
  expect(onSave).toHaveBeenCalledOnce()
})
