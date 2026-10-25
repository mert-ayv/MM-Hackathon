"""A quote line the kit cannot read must not take the supplier down with it."""

from arena_kit.docs import standard_terms as kit_standard_terms

from csee.agent import standard_terms

QUOTE = """Angebot / Quote offer:70410-0
Offered terms
Unit price (EUR) 32.20
Lead time (days) 54
Our standard terms (apply to everything not stated above)
Quality commitment (ppm) 300
Tooling (EUR) {tooling}
Chargeback per complaint (EUR) 0.00
Terms fixed by your enquiry
Payment terms (days net) 30
"""


def events(tooling):
    return [{"from": "supplier", "attachments": [{"name": "quote.pdf", "text": QUOTE.format(tooling=tooling)}]}]


def test_same_as_the_kit_on_a_readable_quote():
    assert standard_terms(events("0.00")) == kit_standard_terms(events("0.00"))


def test_an_unreadable_line_is_skipped_not_raised():
    assert standard_terms(events("none")) == {"ppm_commitment": 300, "chargeback_eur_per_complaint": 0.0}


def test_no_quote_no_terms():
    assert standard_terms([{"from": "supplier", "body": "hello"}]) == {}
