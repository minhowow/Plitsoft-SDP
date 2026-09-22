export function withAdBadge(titles: string[]): string[] {
  const out: string[] = [];
  for (const t of titles) {
    out.push(`(광고) ${t}`);
  }
  return out;
}
