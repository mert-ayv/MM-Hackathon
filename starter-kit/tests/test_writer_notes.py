"""The LLM writer must never send notes meant for our own team to the supplier (P11 v18 R1/R4)."""

from csee.writer import SIGN, strip_notes

LEAK = """Dear Mr Lis,

we propose EUR 44.00 per unit at 300 ppm.

Best regards
Hollerau Pumpenwerke GmbH, Purchasing

---
Internal note for the purchasing team (not part of the e-mail): the MD cannot sign margin cuts."""


def test_note_after_the_signature_is_dropped():
    out = strip_notes(LEAK)
    assert "Internal note" not in out and "MD cannot" not in out
    assert out.endswith(SIGN.splitlines()[-1])


def test_leading_subject_line_is_dropped():
    out = strip_notes("Subject: Bearing brackets\n\nDear Mr Lis,\nthank you.")
    assert out.startswith("Dear Mr Lis")


def test_plain_email_is_unchanged():
    body = "Dear Mr Lis,\nthank you for your offer.\n\n" + SIGN
    assert strip_notes(body) == body
