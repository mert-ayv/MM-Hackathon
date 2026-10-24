# Pitch, demo and video ideas

Ideas for the deliverables, using our ElevenLabs and Lovable credits. Nothing here touches the agent. All of it is built from data we already log: replays, back office, the ledger.

## What we must deliver

| What | When | Notes |
| --- | --- | --- |
| 1-min **demo** video + 1-min **technical** video + architecture notes | Sun 13:00, Hack & More | Architecture notes: [ARCHITECTURE.md](ARCHITECTURE.md) |
| Repo + commit hash + approach description | Sun 13:00 | |
| **5-min pitch + 2-min Q&A** | Sun 15:10, if top 5 | The jury reads our replays. Pick one negotiation and walk through it. Expected questions: *Why did your agent write that? Would it work on a real supplier? What did it learn about suppliers, and from where?* |

**Extra prize to aim for:** the **ElevenLabs prize** (3 months Scale per team member, about $900 each), judged separately from the Tacto track. A memorable, useful ElevenLabs use counts.

## The story (one sentence)

> *Our buyer reads the supplier before it negotiates: it knows the foundry is short of cash, that its letter gave 51 days' notice instead of 90, and that energy prices fell. Then it trades what is cheap for us for what is valuable to the supplier, and code checks every euro.*

## Idea 1: "Hear the negotiation" (ElevenLabs), our strongest bet

Turn a real replay into a short **audio drama**: a voice per party, built from the exact e-mails our agent and the supplier bot exchanged.
- **Our buyer:** a calm, precise voice. **Supplier:** a voice per persona: a Bavarian family-foundry owner, a group's segment manager, a Polish export manager (the replays already have the persona: owner signatures, German phrases like "Viele Grüße aus der Gießerei").
- The **back office as whispered asides**: "The buyer wants more than my band allows. Approve a further step?" The jury hears the supplier's internal reasoning that our agent triggered.
- A narrator (or the agent's own voice) explains each move: *"It cited the notice period. The supplier checked it: verified."*
- Script source: `python -m csee show <session_id>` already prints e-mails + reasons + back office in order. A small script maps them to speakers and calls the ElevenLabs TTS API (multi-voice; Text-to-Dialogue if available).
- Use it as the **soundtrack of the 1-min demo video** and play 20 seconds of it live in the pitch.

## Idea 2: Negotiation replay visualiser (Lovable or a single HTML page)

One screen per negotiation, animated round by round:
- **Price ladder:** the supplier's asks coming down and our offers going up, meeting at the deal. Horizontal lines for the supplier's estimated cost floor and the case's C_best.
- **Score bar:** C_open → C_deal → C_best (exactly like Tacto's 0.64 slide), filling as rounds progress.
- **Lever waterfall:** where the euros came from (price, payment days, delivery terms, effective date, coverage), straight from the result's `cost_breakdown`.
- **Claim badges:** each data argument as a card ("Notice period: 51 vs 90 days, ✔ verified", "Electricity −3.7%, ✔ verified").
- **Supplier mind panel:** the back-office chat (Owner ↔ team, approvals) appearing beside the e-mails.
- **RFQ view:** 2–3 bidders as racing lines, with our agent playing them against each other.
- Data: the session JSON in `starter-kit/runs/sessions/` (export one per showcase case into the app). Build it fast in **Lovable** (we have credits), or as a static HTML page.

## Idea 3: Live Final dashboard for the pitch (for people, never the agent)

A screen showing our agent's five waves as they happened: cases in parallel, deals closing, points per wave, € saved. Built only from **our own logs** (ledger + run log) after the final, so it's clear our agent never read the leaderboard.

## Idea 4: The "before and after" slide

Same case, three agents: Tacto's naive agent → the kit's LLM agent → ours. Show score, rounds and the key move that made the difference (e.g. P10: taking the supplier's second sheet, €85k better). The ledger has all the numbers.

## Idea 5: Voice briefings per wave (fun, optional)

Before each Live Final wave the host shows a theme. After the final, an ElevenLabs "procurement desk radio" recap of each wave: "Wave 3, capacity squeeze. Our agent secured full coverage from Ravensteiner at +1.8%…"

## 1-minute videos (draft)

**Demo video (1 min):**
1. 0–10 s: the inbox (3 supplier e-mails), "Hollerau's buyer has to answer these alone."
2. 10–40 s: the visualiser plays a showcase case, with the ElevenLabs audio of the negotiation underneath.
3. 40–55 s: the score bar fills; lever waterfall shows where the money came from.
4. 55–60 s: "Code decides every number. The language model only words it."

**Technical video (1 min):** the architecture diagram from ARCHITECTURE.md, built up step by step: profiles (46 suppliers, offline), the lever engine, verified claims, parallel threads, the free test pipeline (sim → sandbox → practice) and the experiment ledger.

## Pick the showcase case

After the final (or from our best practice run), choose the negotiation with: a clear supplier persona, at least one verified data argument that moved the price, a trade (e.g. faster payment for a lower price), and a high score. Candidates so far: **P01 Brandlhuber** (family foundry, notice-period argument verified, "we did not know that, a fair point") and **D02** (an RFQ where the owner needs cash: "we need cash to pay our guys").

## Owner and timing

- Saturday evening: pick tools, build the visualiser skeleton, and do a first ElevenLabs test with one replay.
- Sunday 08:00–12:30: record both videos from the best practice replay, prepare the slides.
- Sunday 13:00: upload. 15:10: pitch with the final's best replay (jury can open it on arena.tacto.ai/results).
