// Shared number / copy formatters. No imports, so node:test can load this file directly.

/** `1,000`: counts of patients, tokens, calls. */
export const formatCount = (n: number) => n.toLocaleString("en-US");

/** `1 criterion`, `21 criteria`. */
export function countNoun(n: number, one: string, many: string): string {
  return `${formatCount(n)} ${n === 1 ? one : many}`;
}
