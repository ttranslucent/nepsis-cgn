"""
Streaming UTF-8 validator + NFC normalizer.

Ported into Nepsis as a reusable red-channel guardrail.
"""

import unicodedata
from typing import List, Tuple


class Utf8StreamNormalizer:
    """
    Streaming UTF-8 validator + NFC normalizer with:
      - RFC 3629 checks (no overlongs, surrogates, >U+10FFFF, noncharacters)
      - Byte-accurate error spans
      - Cross-chunk NFC with a safe flush policy that understands Hangul Jamo
    """

    def __init__(self):
        self.buffer = bytearray()
        self.byte_offset = 0
        self.errors: List[Tuple[int, int]] = []
        self.segment: List[str] = []  # current canonical segment (list[str])

    # ---------------- Public API ----------------

    def push(self, chunk: bytes) -> str:
        if not chunk:
            return ""
        self.buffer.extend(chunk)
        out = []
        pos = 0
        n = len(self.buffer)

        while pos < n:
            b0 = self.buffer[pos]

            # ASCII fast path
            if b0 <= 0x7F:
                self._accept_char(chr(b0), out)
                pos += 1
                continue

            # Lone continuation bytes run (treat as one invalid run)
            if 0x80 <= b0 <= 0xBF:
                run_start = pos
                pos += 1
                while pos < n and 0x80 <= self.buffer[pos] <= 0xBF:
                    pos += 1
                self._record_span_error(run_start, pos)
                self._accept_char("\uFFFD", out)
                continue

            # ----- Multi-byte sequences -----

            # 2-byte: 110xxxxx 10xxxxxx
            if 0xC0 <= b0 <= 0xDF:
                if pos + 1 >= n:
                    break  # incomplete
                b1 = self.buffer[pos + 1]
                if not (0x80 <= b1 <= 0xBF):
                    # invalid follower -> consume 1 byte only (minimal advance)
                    self._record_span_error(pos, pos + 1)
                    self._accept_char("\uFFFD", out)
                    pos += 1
                    continue
                cp = ((b0 & 0x1F) << 6) | (b1 & 0x3F)
                # overlong: cp < 0x80
                if cp < 0x80 or self._is_noncharacter(cp):
                    self._record_span_error(pos, pos + 2)
                    self._accept_char("\uFFFD", out)
                else:
                    self._accept_char(chr(cp), out)
                pos += 2
                continue

            # 3-byte: 1110xxxx 10xxxxxx 10xxxxxx
            if 0xE0 <= b0 <= 0xEF:
                if pos + 2 >= n:
                    break  # incomplete
                b1, b2 = self.buffer[pos + 1], self.buffer[pos + 2]
                if not (0x80 <= b1 <= 0xBF and 0x80 <= b2 <= 0xBF):
                    self._record_span_error(pos, pos + 1)
                    self._accept_char("\uFFFD", out)
                    pos += 1
                    continue
                # Lead-byte boundary checks
                if b0 == 0xE0 and b1 < 0xA0:  # overlong
                    self._record_span_error(pos, pos + 3)
                    self._accept_char("\uFFFD", out)
                    pos += 3
                    continue
                if b0 == 0xED and b1 >= 0xA0:  # surrogates
                    self._record_span_error(pos, pos + 3)
                    self._accept_char("\uFFFD", out)
                    pos += 3
                    continue
                cp = ((b0 & 0x0F) << 12) | ((b1 & 0x3F) << 6) | (b2 & 0x3F)
                if cp < 0x800 or (0xD800 <= cp <= 0xDFFF) or self._is_noncharacter(cp):
                    self._record_span_error(pos, pos + 3)
                    self._accept_char("\uFFFD", out)
                else:
                    self._accept_char(chr(cp), out)
                pos += 3
                continue

            # 4-byte: 11110xxx 10xxxxxx 10xxxxxx 10xxxxxx
            if 0xF0 <= b0 <= 0xF4:
                if pos + 3 >= n:
                    break  # incomplete
                b1, b2, b3 = self.buffer[pos + 1], self.buffer[pos + 2], self.buffer[pos + 3]
                if not (0x80 <= b1 <= 0xBF and 0x80 <= b2 <= 0xBF and 0x80 <= b3 <= 0xBF):
                    self._record_span_error(pos, pos + 1)
                    self._accept_char("\uFFFD", out)
                    pos += 1
                    continue
                # Lead-byte boundary checks
                if b0 == 0xF0 and b1 < 0x90:      # overlong for 4-byte
                    self._record_span_error(pos, pos + 4)
                    self._accept_char("\uFFFD", out)
                    pos += 4
                    continue
                if b0 == 0xF4 and b1 > 0x8F:      # beyond U+10FFFF
                    self._record_span_error(pos, pos + 4)
                    self._accept_char("\uFFFD", out)
                    pos += 4
                    continue
                cp = ((b0 & 0x07) << 18) | ((b1 & 0x3F) << 12) | ((b2 & 0x3F) << 6) | (b3 & 0x3F)
                if cp < 0x10000 or cp > 0x10FFFF or self._is_noncharacter(cp):
                    self._record_span_error(pos, pos + 4)
                    self._accept_char("\uFFFD", out)
                else:
                    self._accept_char(chr(cp), out)
                pos += 4
                continue

            # 0xF5..0xFF are invalid lead bytes
            self._record_span_error(pos, pos + 1)
            self._accept_char("\uFFFD", out)
            pos += 1

        # Advance global offset and keep any incomplete tail in buffer
        self.byte_offset += pos
        if pos:
            del self.buffer[:pos]

        return "".join(out)

    def finish(self) -> str:
        out = []
        # Any leftover bytes mean an incomplete sequence -> ONE span + ONE U+FFFD
        if self.buffer:
            start = self.byte_offset
            end = self.byte_offset + len(self.buffer)
            self.errors.append((start, end))
            self.buffer.clear()
            self._accept_char("\uFFFD", out)

        if self.segment:
            out.append(unicodedata.normalize("NFC", "".join(self.segment)))
            self.segment.clear()
        return "".join(out)

    def process(self, full_bytes: bytes) -> Tuple[str, List[Tuple[int, int]]]:
        """Convenience method to process a full byte stream at once."""
        out = self.push(full_bytes)
        out += self.finish()
        return out, self.errors

    # ---------------- Helpers ----------------

    def _accept_char(self, ch: str, out_parts: list):
        if self._is_starter(ch) and self._segment_safe_to_flush():
            if self.segment:
                out_parts.append(unicodedata.normalize("NFC", "".join(self.segment)))
                self.segment.clear()
            self.segment.append(ch)
        else:
            self.segment.append(ch)

    def _segment_safe_to_flush(self) -> bool:
        if not self.segment:
            return False
        last = ord(self.segment[-1])
        if self._is_hangul_jamo_L(last) or self._is_hangul_jamo_V(last):
            return False
        return True

    @staticmethod
    def _is_starter(ch: str) -> bool:
        return unicodedata.combining(ch) == 0

    @staticmethod
    def _is_hangul_jamo_L(cp: int) -> bool:
        return (0x1100 <= cp <= 0x115F) or (0xA960 <= cp <= 0xA97F)

    @staticmethod
    def _is_hangul_jamo_V(cp: int) -> bool:
        return (0x1160 <= cp <= 0x11A7) or (0xD7B0 <= cp <= 0xD7C6)

    @staticmethod
    def _is_noncharacter(cp: int) -> bool:
        if 0xFDD0 <= cp <= 0xFDEF:
            return True
        return (cp & 0xFFFF) in (0xFFFE, 0xFFFF)

    def _record_span_error(self, local_start: int, local_end: int):
        self.errors.append((self.byte_offset + local_start, self.byte_offset + local_end))
