/** Legacy rows store two independent ordered lists; positions do not imply pairing. */
export function caseContentRows(actions: string, checkpoints: string) {
  const lines = (text: string) => text.split('\n').map(line => line.trim()).filter(Boolean);
  const a = lines(actions), e = lines(checkpoints);
  return Array.from({ length: Math.max(a.length, e.length) }, (_, i) => ({ action: a[i] ?? '', expected: e[i] ?? '' }));
}
