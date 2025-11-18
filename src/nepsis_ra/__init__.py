from nepsis_ra.core import NepsisRA
from nepsis_ra.domains.utf8_puzzle import Utf8PuzzleDomainHandler
from nepsis_ra.domains.word_puzzle import WordPuzzleDomainHandler


def make_default_nepsis_ra() -> NepsisRA:
  handlers = [
    WordPuzzleDomainHandler(),
    Utf8PuzzleDomainHandler(),
  ]
  return NepsisRA(handlers)


__all__ = ["NepsisRA", "make_default_nepsis_ra"]
