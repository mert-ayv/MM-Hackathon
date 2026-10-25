"""Offline score diagnostics, not an agent or a forecast of supplier acceptance.

Run from starter-kit: uv run python ../analysis/mert-frontier-review/offline_frontier.py
No network calls. Observations are completed team practice results, 24 October.
"""
import json
import math
from pathlib import Path

from arena_kit.cost import total_cost, must_haves_ok

ROOT = Path(__file__).resolve().parents[2]
cases = {c['case_id']: c for c in json.loads(
    (ROOT / 'starter-kit/runs/cases/practice.json').read_text())}

# session e12ba8b1ded8b5f0 (90 days) and 62b13173901fbf62 (30 days).
c = cases['case:P02']
b = c['buyer']
def cost_ratio(penalty):
    gap = math.sqrt(10 * penalty / b['relationship_eur_per_point'])
    assert gap <= 5, 'quadratic inversion requires gap <= 5'
    return 1 + (gap - b['sustainable_margin_pct']) / 100

full_cost = 357 * cost_ratio(38416.56)
rate = (1 - full_cost / (362 * cost_ratio(32205.77))) * 360 / 60
standard = dict(c['fixed_terms'], payment_days=30, ppm_commitment=250,
                chargeback_eur_per_complaint=0, index_clause=None)
supplier = dict(full_cost=full_cost, interest_rate=rate, standard=standard)
clause = next(t for t in c['term_options']['index_clause']
              if t and t['deadband_pct'] == 5)
print(f'P02 inferred full cost {full_cost:.5f}, money rate {rate:.6%}')
# Holdouts were not used to fit the two parameters. Rounding tolerates two cents.
for price, index, actual in [(360.38, clause, 2248294.44)]:
    terms = dict(standard, unit_price=price, payment_days=90, index_clause=index)
    predicted = total_cost(c, terms, supplier=supplier)
    assert abs(predicted - actual) <= .02, (predicted, actual)
    print(f'P02 held-out 360.38 deal cost error: {predicted-actual:+.2f} EUR')

def score(case, terms, opening, best, supplier=None):
    assert must_haves_ok(case, terms)
    raw = (opening-total_cost(case, terms, supplier=supplier))/(opening-best)
    return max(0, min(1, raw))

print('\nP02 cheapest mathematical cost by clause/payment; acceptance UNKNOWN')
for index in [None, clause]:
    for days in c['term_options']['payment_days']:
        t = dict(standard, payment_days=days, index_clause=index)
        cost, price = min((total_cost(c, dict(t, unit_price=p/100), supplier=supplier), p/100)
                          for p in range(34500, 38001))
        print(index and index['deadband_pct'], days, price,
              round(max(0,min(1,(2282867.49-cost)/(2282867.49-2235514.05))),4))
print('P02 fixed 368 @90:', score(c, dict(standard, unit_price=368,
      payment_days=90), 2282867.49, 2235514.05, supplier))

print('\nP11 candidate structures; acceptance UNKNOWN')
c = cases['case:P11']
for price, ppm in [(45.5,300),(45,300),(44.77,800),(44.46,1500)]:
    t = dict(c['fixed_terms'], unit_price=price, ppm_commitment=ppm,
             chargeback_eur_per_complaint=0)
    print(price, ppm, score(c,t,817578,722500.02))

print('\nP18 candidate structures; acceptance UNKNOWN')
c = cases['case:P18']
for price, days, db in [(5.30,90,5),(5.10,45,3),(5.10,90,5)]:
    index = next(t for t in c['term_options']['index_clause'] if t and t['deadband_pct']==db)
    t = dict(c['fixed_terms'],unit_price=price,payment_days=days,
             index_clause=index,contract_months=24,ppm_commitment=70,
             chargeback_eur_per_complaint=0)
    print(price,days,db,score(c,t,295173.23,222651.27))
