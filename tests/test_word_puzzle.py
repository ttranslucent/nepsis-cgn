from nepsis_ra import make_default_nepsis_ra


def test_jingall_puzzle_solved():
  ra = make_default_nepsis_ra()
  query = "Given the letters: J A I L N G, find a word using all letters exactly once."

  result = ra.run(query)

  assert result["domain"] == "word_puzzle"
  assert result["template_id"] == "exact_anagram"
  assert result["answer"] is not None
  assert result["answer"].lower() in {"jingall", "jingal"}
  assert result["trace"].success is True
