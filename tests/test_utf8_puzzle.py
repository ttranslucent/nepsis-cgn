from nepsis_ra import make_default_nepsis_ra


def test_utf8_invisible_codepoint_detected():
  ra = make_default_nepsis_ra()

  candidate = "foo\u200bbar"  # contains zero-width space
  result = ra.run(candidate, override_domain="utf8_puzzle")

  assert result["domain"] == "utf8_puzzle"
  assert result["template_id"] == "invisible_equivalence"
  trace = result["trace"]

  assert trace.success is True

  step = trace.steps[0]
  invis_cr = next(cr for cr in step.constraint_results if cr.constraint_id == "InvisibleCodepointConstraint")

  assert invis_cr.score == 1.0
  assert "U+200B" in invis_cr.message


def test_utf8_clean_string_passes():
  ra = make_default_nepsis_ra()

  candidate = "simple ASCII string"
  result = ra.run(candidate, override_domain="utf8_puzzle")

  assert result["domain"] == "utf8_puzzle"
  trace = result["trace"]

  step = trace.steps[0]
  total_score = step.total_score

  assert total_score == 0.0
  assert trace.final_choice is True
