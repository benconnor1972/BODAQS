export function toCssUnit(v: string | number) {
  return typeof v === 'number' ? `${v}px` : v;
}
