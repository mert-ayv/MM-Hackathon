# Technical video (60 s): script v1, "Code decides every number"

**Status:** draft for review. Nothing recorded or rendered yet.
**Companion:** the demo video (`video/demo-60s/SCRIPT_v3.md`) tells the story of one negotiation. This one answers *how it works and how we know it works*. No overlap: the demo never shows the diagram, this never replays an e-mail thread.
**Audience:** Hack & More judges who have not read Tacto's brief, and the Tacto jury as a second viewer. Assume they know what an LLM agent is and nothing about the arena.

## Depth: what is in, what is out

Sixty seconds is about 150 spoken words, so four ideas with one number each. The depth chosen is **architecture + one empirical finding + method**, never code.

| In (spoken) | Out (on screen only, in Menlo) | Out entirely |
|---|---|---|
| The rule: code decides every number, the LLM reads and writes | module file names under each box | code on screen beyond one real log line |
| The four boxes: dossier, engine, policy, writer | the guardrails band | Ege's strategist (not in the final router) |
| The fitted bot model: tit-for-tat, from our own 260 sessions | result vs house agent (end card only) | score tables, per-case numbers (that is the pitch) |
| The research ladder and the ledger, incl. one rejected idea | commit hashes, session IDs in footers | the Live Final mechanics, the 5 waves |

Why this level: the three things that make us different are the code/LLM split, that we *measured* the bots instead of guessing, and that every change climbed the same ladder. A judge can repeat each of the three in one sentence afterwards. Anything deeper (the pricing math, `price_for`, MESO sheets) needs more than a minute and belongs in Q&A.

## Format and style

Same design language as the demo so both videos read as one set: cream paper, charcoal, dusty ochre, **one oxide-red word per scene**, Didot for the numerals, Helvetica Neue for information, Menlo for IDs and file names. The hero here is a **schematic drawn on paper**: four boxes that appear one at a time, with a guardrails band underneath. The presenter is the same person as in the demo, in the envelope window for the opening and the close, voice only in between.

## Shot list

Narration: 158 words, 2.6 words per second: brisk but fine for a presenter. Cut T1 to "Supplier bots, one minute per thread, scored on total cost. Our rule:" (12 words) if a read-through runs past 60 s. Each scene has one red word.

| Time | Picture | Type (red word in **bold**) | PRESENTER says |
|---|---|---|---|
| 0.0–6.0 | **T1 Setup.** Envelope, presenter in the window. Beside it three small envelopes and a stopwatch icon | "1–3 supplier bots · e-mail · **60 s** per thread" · "scored on total cost, not unit price" | "One to three supplier bots, a sixty-second clock per thread, scored on total cost. Our rule:" |
| 6.0–10.0 | **T2 Rule.** Blank paper, one line is typed | Didot **code** decides every number. · Helvetica "the language model only reads and writes" | "Code decides every number. The language model only reads and writes." |
| 10.0–15.0 | **T3 Box 1.** Schematic: box *Supplier dossier* draws itself; paper strips (letter, call note, news, scorecard) slide in behind it | "**46** suppliers · offline" · Menlo `profiles/70110.json … ctr:4600070110 ✔` | "Offline, a dossier on all forty-six suppliers. Every cited ID is checked by code." |
| 15.0–20.0 | **T4 Box 2.** Box *Commercial engine*; an adding-machine roll prints `C = price + payment + freight + lead time + quality + risk` | "the arena's exact cost model, **to the euro**" · Menlo `levers.py · arena_kit/cost.py` | "An engine prices every term with the arena's exact cost model." |
| 20.0–27.0 | **T5 Box 3.** Box *Negotiation policy*; insert for 2 s: the real log line, typewritten | Menlo `plan r2: c^ 2.25% gap 7.82% -> target 8.00%` · Helvetica "anchor · pace · **3** term sheets per e-mail · accept or walk" · Menlo `agent.py` | "A policy anchors, paces the concessions and sends up to three term sheets per e-mail." |
| 27.0–33.0 | **T6 Box 4.** Box *Writer (Claude)*; a real e-mail paragraph, the claim sentence underlined in ochre, a stamp **VERIFIED** lands on it; one invented ID is struck through in red | "**verbatim**: numbers and claim sentences" · "invented IDs deleted · template if slow" · Menlo `writer.py` | "Claude words the reply in the supplier's register. Numbers and claim sentences stay verbatim." |
| 33.0–36.0 | **T7 Band.** A guardrails band draws under the four boxes | "only the supplier's standing sheet · never above our alternative · never after a final offer · close before the cap" | (no speech, 3 s) |
| 36.0–47.0 | **T8 Finding.** The schematic fades; a chart on paper: P01's supplier asks as six shrinking steps, 138.55 → 135.50 → 133.80 → 132.80 → 132.30 → 132.10 "final" | "**260** of our own sessions" · "tit-for-tat · shrinking cap · fixed patience" · Menlo `back office: "My call: counter"` · small: Faratin, Sierra & Jennings 1998 | "From two hundred sixty of our own sessions we fitted the bots: tit-for-tat, a shrinking cap, fixed patience. So we concede exactly what they will mirror, and never push after a final offer." |
| 47.0–56.0 | **T9 Method.** Three rungs on paper: *simulator → sandbox → one logged practice run*; then the ledger as a tally roll, rows ticking up to 489; a small router box fans out to four case types | "**489** ledger rows · who, agent, commit, score" · "router: the measured winner per case type" · struck through in red: "LLM picks the moves" · Menlo `P07 0.728 vs 0.766` | "Every change climbed one ladder: simulator, sandbox, one logged practice run. The ledger holds hundreds of logged runs, and a router sends each case type to its measured winner. An LLM choosing the moves scored worse, so it doesn't." |
| 56.0–60.0 | **T10 End.** Envelope turns over, presenter in the window | Helvetica **csee-base** · Didot italic *code checks every euro.* · Menlo footer `practice mean 0.81 vs house agent 0.70 · docs/ARCHITECTURE.md` | "csee-base. Code checks every euro." |

## Fact check (every spoken or typed number, with its source)

- 1–3 supplier bots, 60 s per thread, scored on total cost: `CHALLENGE.md` §scoring; `README.md` "Live Final".
- 46 suppliers in the dossier, built offline from letters, call notes, news, scorecards; every cited ID verified: `docs/ARCHITECTURE.md` module table (`profiles/*.json`), `docs/pitch/pitch-outline.md` slide 3. There are 47 profile files; one covers a practice-only supplier. Say "all 46 final suppliers".
- Exact cost model, deal cost reproduced to the euro on all 40 deals: `README.md:203`.
- Up to 3 term sheets per e-mail (main sheet + up to 2 trades): `docs/ARCHITECTURE.md` base pipeline, `sheets()`.
- Log line `plan r2: c^ 2.25% gap 7.82% -> target 8.00%`: P01 round 2, quoted in `docs/pitch/qa.md:8`.
- Numbers and claim sentences verbatim, invented IDs scrubbed, template fallback when the model is slow: `docs/ARCHITECTURE.md` changelog v1.2 and base pipeline (writer).
- Guardrails band: `docs/ARCHITECTURE.md` "Safety rails"; `docs/pitch/pitch-outline.md` slide 3.
- 260 sessions, tit-for-tat, shrinking cap, fixed patience (median 4 replies over 1,132 supplier replies), next price within about 0.6 %: `README.md:211`, `docs/pitch/qa.md:23`. Reference: Faratin, Sierra & Jennings 1998; "concede what they mirror" is the best response per de Jonge 2022 (`README.md:221`).
- P01 shrinking steps 138.55 → 135.50 → 133.80 → 132.80 → 132.30 → 132.10 final: `docs/pitch/pitch-outline.md` slide 4. Re-check against the session before rendering.
- "Never push after a final offer": v15's push on P02 made the supplier walk, 0.48 → 0 (`starter-kit/csee/agents/router.py` comment; pitch-outline slide 7).
- Ladder simulator → sandbox → practice: `STRATEGY.md`, `docs/ARCHITECTURE.md` experiment log.
- 489 ledger rows: `cat experiments/*.jsonl | wc -l` at 10:25 Sunday. Spoken as "hundreds of logged runs" so the voice track does not date; the exact count is type only. Re-count right before rendering and update T9.
- Router = measured winner per case type: `starter-kit/csee/agents/router.py` ROUTES and its comments.
- "An LLM choosing the moves scored worse": P07 0.728 vs 0.766, sandbox D02 0.67 vs 0.72, LLM strategist P05 0.52 / 0.72 vs 0.81 for the rule policy: `docs/pitch/pitch-outline.md` slide 7.
- End card **0.81 vs 0.70**: our practice board, best score per case, `uv run python -m csee board` and `arena.tacto.ai/v1/live` (`best_mean` 0.806, checked 10:30 Sunday). House agent: the arena's per-case `house` values average 0.6966 over the same 10 cases (checked 10:30 Sunday via the leaderboard skill), so 0.70 at two decimals, 0.697 at three. Same number as the demo outro (81 %). Stricter alternative, not used on the card: 0.77 in one full run of the final router (08:10 CET Sunday, commit `09c8e5c`, 10 of 10 cases closed, mean 0.773, `experiments/2026-10-25-go49mor.jsonl`); have it ready for Q&A. The old README line "0.78" is outdated. Do not claim "8 of 10" anywhere in the video; the pitch outline explains why.

## Decisions (strategy session, Sun 10:30)

1. **Ledger count:** spoken as "hundreds of logged runs"; 489 stays as type, re-counted at render time.
2. **T7 (guardrails, 3 s silent):** kept only if the read-through fits 60 s. If it runs long, cut T7 first; the band stays as a static layer under T8.
3. **End card:** 0.81 vs 0.70, the same figure as the demo outro. Verified above.

## Still open

- **T8 chart source:** take the six asks from the P01 session used in the pitch (replays.md #1) so the pitch and the video show the same numbers.
