import { expect, test } from "@playwright/test";

import { readRationaleSegment } from "../src/app/engine/operatorAssist";

test("rationale segment extraction is exact-case and pipe-delimited", () => {
  const rationale = "Red channel: avoid harm | Blue channel: move carefully | Uncertainty: report quality";

  expect(readRationaleSegment(rationale, "Red channel")).toBe("avoid harm");
  expect(readRationaleSegment(rationale, "Blue channel")).toBe("move carefully");
  expect(readRationaleSegment(rationale, "Uncertainty")).toBe("report quality");
  expect(readRationaleSegment("red channel: avoid harm | Blue channel: x", "Red channel")).toBe("");
  expect(readRationaleSegment("Red channel: avoid | embedded pipe | Blue channel: x", "Red channel")).toBe("avoid");
  expect(readRationaleSegment("Red channel: avoid harm", "Uncertainty")).toBe("");
});
