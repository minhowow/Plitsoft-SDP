// 줄바꿈을 잰다: 닫는 부호와 조사 사이('(광고) ⏎ 를')에서 줄이 바뀌면 적어 둔다
export class Scans {
  readonly low: string[] = [];

  add(where: string, found: string[]): void {
    for (const entry of found) {
      this.low.push(`${where}: ${entry}`);
    }
  }
}

export function collect(own: string[], where: string, found: string[]): number {
  for (const entry of found) own.push(`${where}: ${entry}`);
  return own.length;
}
