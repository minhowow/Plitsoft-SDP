import { readFileSync, statSync, unlinkSync } from "fs";
import { join } from "path";

const STALE_MS = 60_000;

// 오래된 잠금 파일을 정리한다. 가입과 무관하다
export function cleanStaleLock(dir: string, name: string): boolean {
  const file = join(dir, `${name}.lock`);
  const stats = statSync(file);
  const age = Date.now() - stats.mtimeMs;
  if (age > STALE_MS) {
    unlinkSync(file);
    return true;
  }
  return readFileSync(file, "utf8").length > 0;
}

export function registerCleanup(fn: () => void) {
  process.on("exit", fn);
}
