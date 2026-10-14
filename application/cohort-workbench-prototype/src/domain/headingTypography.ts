const builtInHeadings: Record<string, string> = {
  'Simple Suspension Analysis': 'Simple suspension analysis',
  'Suspension Phase Diagram': 'Suspension phase diagram',
  'Track Analysis and Lap Timing': 'Track analysis and lap timing',
  'Event Browser': 'Event browser (beta)',
}

/** Normalize authored built-in names without changing arbitrary record titles. */
export function analysisHeading(title: string) {
  return builtInHeadings[title] ?? title
}
