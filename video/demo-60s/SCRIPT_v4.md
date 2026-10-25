# Demo video (60 s): script v4, dashboard replay of the final router

**Source:** practice case P01, session `796f528a6eea6626`. This is the exact final router (`--agent router`, commit `09c8e5c`, AI writer on), run 25 Oct 08:10 CET, note "release check: exact final router". **Score 0.971**, 5 rounds, deal **€132.85/unit from 2027-04-01, payment 14 days net**. C_open €1,153,780 → C_deal €1,098,441, which is **€55,339 below their opening offer**.
**Picture:** dashboard replay (`#/replay/20261025-080841-router-practice/case:P01`), Demo speed, 125 % zoom, recorded headless with `record_replay.py`. File: `renders/replay_router/replay_p01_router.mp4` (30 s of playback).
v3 (session `d06ad94e`, 0.93) stays in `SCRIPT_v3.md` as the fallback.

| Time | Who | Line (verbatim from the run, shortened with "…") | Picture |
|---|---|---|---|
| 0–8 | **PRESENTER** | "Our supplier for pump housings just raised the price by nine and a half percent. For the Tacto Negotiation Arena, we built an AI buyer that negotiates this alone. By email. Listen." | presenter |
| 8–12 | OWNER | "We can offer you a price of one hundred thirty-eight fifty-five per unit, valid from the first of November." | replay: opening quote (zoom on the email column) |
| 12–18 | BUYER | "We cannot accept an increase of this size. Your letter gives fifty-one days' notice, while our agreement requires ninety." | replay R1: our email |
| 18–20 | BACK OFFICE (whisper) | "My call: counter." | |
| 20–26 | OWNER | "We checked the notice period data you cited; it holds. … We did not know that. A fair point." | R1 reply with three **VERIFIED** badges |
| 26–31 | BUYER | "We propose one hundred twenty-eight seventy-six per unit… payment at fourteen days net." | R2: the 14-day option (the owner wants cash) |
| 31–37 | OWNER | "We accept your offer of one hundred thirty-two eighty-five per unit, with payment at fourteen days net, from April." | R5: agreed |
| 37–42 | (no voice) | | **only now** the score panel, full frame: **0.97** · **−€55,339 vs opening** |
| 42–55 | **PRESENTER** | "Code sets every number. The language model only writes the words. Ten of ten deals: seventy-seven percent of the best possible saving. Tacto's own agent gets seventy. We're csee-base." | presenter, end card |

**In the edit:** while the replay runs, stay zoomed on the email column. The live score panel reaches 1.00 in rounds 4–5 because it uses the agent's own cost estimate. Show the score panel only at the end, where the official 0.97 appears. Trim the first 4 s of the recording, which are before the zoom kicks in.

## Fact check

- Deal €132.85 from 2027-04-01 at 14 days net. Old price €126.53 → **+5.0 %** against the +9.5 % ask, and it starts five months later.
- The three cited facts (notice period, complaint rate, demand forecast) all came back `verified`. "We did not know that - a fair point." is verbatim from round 1.
- "Ten of ten deals: seventy-seven percent": the exact final router played all 10 practice cases in four separate full runs: 0.762, 0.765, 0.772 and 0.773, with 10/10 deals each time. **Not 0.806**: that is the best result per case picked across many different agents and runs, which no single agent achieved.
- "Tacto's own agent gets seventy": the house agent mean on the practice board is 0.697 over the same 10 cases.
- "The language model only writes the words": this run had the AI writer on (`llm: true`). Terms come from the lever engine; the writer only words them, and claim sentences stay verbatim.
