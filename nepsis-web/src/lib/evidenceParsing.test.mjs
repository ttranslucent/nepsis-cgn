import assert from "node:assert/strict";
import test from "node:test";

import {
  containsAffirmedAny,
  parseBoolTag,
  parseStringTag,
} from "./evidenceParsing.ts";

test("control tags require their own token boundary", () => {
  assert.equal(
    parseBoolTag(
      "not_independent_observation:true",
      "independent_observation",
    ),
    undefined,
  );
  assert.equal(parseStringTag("not_evidence_id:wrong", "evidence_id"), undefined);
  assert.equal(
    parseBoolTag("observation independent_observation:true", "independent_observation"),
    true,
  );
});

test("negation does not leak across sentence or clause boundaries", () => {
  assert.equal(
    containsAffirmedAny("no policy violation. critical signal present", ["critical"]),
    true,
  );
  assert.equal(
    containsAffirmedAny("no fever; saddle anesthesia present", ["saddle anesthesia"]),
    true,
  );
  assert.equal(containsAffirmedAny("no critical signal", ["critical"]), false);
  assert.equal(containsAffirmedAny("no progression or worsening", ["progression"]), false);
});
