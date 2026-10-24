---
name: leaderboard
description: Check who is winning the Tacto Negotiation Arena right now - the practice leaderboard (mean best score per team, records, house-agent benchmark per case) or, during/after Sunday's Live Final, the final standings. Use when asked "who is first", "leaderboard", "how are we doing vs other teams", "who is winning".
---

# Arena leaderboard

These endpoints are public and need no key. **They are for people only**: our *agent* must never read them during the Live Final (rule 7.1), so never call them from agent code.

## Practice (until the Sunday 13:00 code freeze)

```bash
curl -s https://arena.tacto.ai/v1/live | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f\"{d['teams_total']} teams, {d['teams_active_1h']} active in the last hour\")
for t in sorted(d['teams'], key=lambda t: t['rank'] or 99):
    us = '  <- us' if t['name'] == 'csee-base' else ''
    print(f\"{t['rank'] or '-':>2} {t['name']:<20} mean {t['best_mean'] if t['best_mean'] is not None else '-':<6} \"
          f\"played {t['bots_played']}/10  records {t['records']}  sessions today {t['used_today']}{us}\")
print()
print('case   house  best   holder')
for b in d['bots']:
    beat = ' BEATS HOUSE' if b.get('best') is not None and b['best'] > b['house'] else ''
    print(f\"{b['case_id'][5:]:<6} {b['house']:.2f}   {b['best'] if b['best'] is not None else '-':<6} {b.get('holder') or '-'}{beat}\")
"
```

Report: who is #1, our team's rank (`csee-base`) and gap to #1, cases where anyone beats the house agent, and any case where we lead. Mean = mean of each team's best score per hosted case (unplayed = 0); practice does **not** decide the ranking.

## Live Final (Sunday from 13:30)

```bash
curl -s https://arena.tacto.ai/v1/leaderboard?set=final | python3 -m json.tool | head -60
```

Points = sum of wave scores (max 500); ties go to more deals, then fewer rounds. Per-team detail: `https://arena.tacto.ai/v1/results/<team_name>`.
