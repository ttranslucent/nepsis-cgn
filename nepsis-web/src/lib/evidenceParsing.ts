export function parseBoolTag(text: string, tag: string): boolean | undefined {
  const escapedTag = tag.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const regex = new RegExp(
    `(?:^|\\s)${escapedTag}\\b\\s*[:=]\\s*(true|false|yes|no|1|0)`,
    "gi",
  );
  let token: string | undefined;
  for (const match of text.matchAll(regex)) {
    token = match[1]?.toLowerCase();
  }
  if (!token) {
    return undefined;
  }
  return token === "true" || token === "yes" || token === "1";
}

export function parseStringTag(text: string, tag: string): string | undefined {
  const escapedTag = tag.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const regex = new RegExp(
    `(?:^|\\s)${escapedTag}\\b\\s*[:=]\\s*([A-Za-z0-9._:-]+)`,
    "gi",
  );
  let value: string | undefined;
  for (const match of text.matchAll(regex)) {
    value = match[1];
  }
  return value;
}

export function containsAffirmedAny(
  haystack: string,
  terms: readonly string[],
): boolean {
  return terms.some((term) => containsAffirmedTerm(haystack, term));
}

export function containsAffirmedTerm(haystack: string, term: string): boolean {
  let start = 0;
  while (start < haystack.length) {
    const index = haystack.indexOf(term, start);
    if (index === -1) {
      return false;
    }
    if (!isNegatedEvidenceWindow(haystack, index, term.length)) {
      return true;
    }
    start = index + term.length;
  }
  return false;
}

export function isNegatedEvidenceWindow(
  text: string,
  termIndex: number,
  termLength: number,
): boolean {
  const before = text.slice(Math.max(0, termIndex - 72), termIndex);
  const clauseBoundary = Math.max(
    before.lastIndexOf("."),
    before.lastIndexOf("!"),
    before.lastIndexOf("?"),
    before.lastIndexOf(";"),
    before.lastIndexOf("\n"),
  );
  const clauseBefore = before.slice(clauseBoundary + 1);
  const after = text.slice(termIndex + termLength, termIndex + termLength + 48);
  const around = `${clauseBefore}${text.slice(termIndex, termIndex + termLength)}${after}`;
  return (
    /\b(no|not|without|none|denies|denied|absent|negative for|unconfirmed)\b/.test(
      clauseBefore,
    ) ||
    /\bnot\s+(confirmed|present|observed|identified|established)\b/.test(after) ||
    /\b(no|not|without)\b[^.!?\n;]{0,80}\b(confirmed|present|observed|identified|established|yet)\b/.test(
      around,
    )
  );
}
