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


def test_plural_team_notes_are_dropped():
    out = strip_notes("Dear Mr Lis,\nthank you.\n\n" + SIGN + "\n\nNotes for the team: the MD cannot sign margin cuts.")
    assert "MD cannot" not in out


def test_claim_goes_above_a_signature_the_model_wrote():
    from csee.writer import insert_before_signature

    body = "Dear Mr Lis,\nthank you.\n\nKind regards\nHollerau Pumpenwerke GmbH, Purchasing"
    out = insert_before_signature(body, "Should-cost is EUR 40.10 (cost:1).")
    assert out.index("cost:1") < out.index("Kind regards")
    assert out.count("Hollerau Pumpenwerke GmbH, Purchasing") == 1


def test_plural_team_notes_are_dropped():
    out = strip_notes("Dear Mr Lis,\nthank you.\n\n" + SIGN + "\n\nNotes for the team: the MD cannot sign margin cuts.")
    assert "MD cannot" not in out


def test_claim_goes_above_a_signature_the_model_wrote():
    from csee.writer import insert_before_signature

    body = "Dear Mr Lis,\nthank you.\n\nKind regards\nHollerau Pumpenwerke GmbH, Purchasing"
    out = insert_before_signature(body, "Should-cost is EUR 40.10 (cost:1).")
    assert out.index("cost:1") < out.index("Kind regards")
    assert out.count("Hollerau Pumpenwerke GmbH, Purchasing") == 1
