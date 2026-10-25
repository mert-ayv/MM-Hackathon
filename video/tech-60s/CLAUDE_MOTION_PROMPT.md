# Claude Motion prompt for the technical video

How to use: in claude.ai, choose **Output → Motion** (or the Motion template on the Artifacts tab), attach
`SCRIPT_v1.md` from this folder, paste everything below the line, send. Review, ask for fixes in chat, then
**Export → MP4**. Send us the MP4 (1920×1080). We add the narration ourselves.

---

Make a 60-second, 16:9 (1920×1080) animated technical explainer for a hackathon submission. It explains how our
autonomous AI buyer agent "csee-base" works. The attached SCRIPT_v1.md is the exact shot list; follow its timings,
on-screen text and numbers word for word. Do not invent numbers, names or quotes. There is no footage, no people
and no narrator voice in the file: it is a silent animation of type, simple line drawings and one chart. We will
record and add the narration later, so keep the pacing of the script's timecodes.

Audience: hackathon judges who know what an LLM agent is but have not read the challenge. Tone: calm, precise,
editorial.

Visual style
- Background: cream paper (#f1ebdc) with a faint vignette. Ink: charcoal (#2b2a28). Accent: dusty ochre (#b8924a)
  for underlines. Exactly one word or number per scene in oxide red (#a63a2a), as marked in the script.
- Type: a high-contrast serif like Didot for big numbers and the red words, Helvetica Neue for information,
  Menlo (monospace) for IDs, file names and log lines. Monospace lines are small and grey.
- Motion: things draw, type or slide in; nothing bounces or spins. A cut every 2 to 5 seconds. Lines and boxes
  draw themselves like ink. Stamps land with a quick scale-down. Hold each text long enough to read.
- Recurring device: a cream window envelope. It opens the film (slides in from the left) and closes it (turns over
  to show our name on the back).

Scenes (seconds)
1. 0–6 Setup. The envelope slides in, "to csee-base" in its window, "Tacto Negotiation Arena" in the corner.
   Beside it three small envelopes appear one by one, then a stopwatch with the red "60 s". Text:
   "1–3 supplier bots · e-mail · 60 s per thread" and, greyer, "scored on total cost, not unit price".
2. 6–10 Rule. Blank paper. A line types itself in large serif: "code decides every number." with "code" in red.
   Below, smaller: "the language model only reads and writes".
3. 10–15 Box 1. A schematic begins: a box "Supplier dossier" (sub-label "offline") draws itself at the bottom of
   the frame, monospace footer "profiles/*.json · intel.py". Above it, four paper strips slide into a stack:
   "letter", "call note", "news", "scorecard" with monospace IDs "doc:20260911-70110", "doc:20260902-70110-M2",
   "sc:70110@2026Q3". Big red "46" with "suppliers · offline". Monospace: "ctr:4600070110 ✔ sc:70110@2026Q3 ✔ /
   every cited ID checked by code".
4. 15–20 Box 2. An arrow draws to the next box "Commercial engine" (sub-label "code"), footer "levers.py ·
   arena_kit/cost.py". Above: a white tally roll prints, line by line, in monospace: "C = price / + payment terms /
   + freight + lead time / + quality + index risk / + supplier health / + relationship goal". Beside it:
   "the arena's exact cost model," then large red serif "to the euro".
5. 20–27 Box 3. Arrow, box "Negotiation policy" (sub-label "code"), footer "agent.py · agents/router.py". Above,
   a real log line types in monospace: "plan r2: c^ 2.25% gap 7.82% -> target 8.00%", small grey caption
   "run log, case P01, round 2: the supplier moved 2.25 %, so we match what it will mirror". Then:
   "anchor · pace · 3 term sheets per e-mail · accept or walk" with the "3" large and red.
6. 27–33 Box 4. Arrow, box "Writer" (sub-label "Claude, words only"), footer "writer.py". Above right, a paper
   e-mail: "Dear Mr Brandlhuber, thank you for your letter. Your letter gives 51 days' notice, while our agreement
   requires 90 days. We attach three packages that reflect this …". The sentence about 51 and 90 days gets an ochre
   underline; a red stamp "VERIFIED" lands on the paper. Under the paragraph, monospace "ctr:4600070110
   doc:20260913-70110-Z4": the second ID is struck through in red with the caption "an ID the model invented:
   deleted before sending". Left: large red serif "verbatim", then "numbers and claim sentences", then greyer
   "invented IDs deleted · template if the model is slow".
7. 33–36 Band. Under the four boxes a line draws across the frame, label "guardrails, in code, every variant",
   text: "only the supplier's standing sheet · never above our alternative · never after a final offer · close
   before the cap". No other change; 3 seconds of quiet.
8. 36–47 Finding. The schematic fades. A staircase chart draws step by step, one step every 0.9 s, the supplier's
   asks in EUR per unit: 138.55, 135.50, 133.80, 132.80, 132.30, 132.10. Each step is smaller than the last; show
   the differences in small grey monospace (−3.05, −1.70, −1.00, −0.50, −0.20). The last step and its label
   "132.10 final" are red. Caption under the chart: "supplier asks, EUR per unit, practice case P01, session
   5629648d". Right side: large red serif "260", "of our own sessions, fitted"; then "tit-for-tat / shrinking cap /
   fixed patience"; monospace 'back office: "My call: counter"'; then "so: concede what they will mirror, / never
   push after a final offer"; tiny: "Faratin, Sierra & Jennings 1998 · de Jonge 2022".
9. 47–56 Method. Left: a vertical line draws down with three rungs: "local simulator (free)", "sandbox, real bots
   (free)", "one logged practice run"; label "every change climbs one ladder". Middle: a paper ledger
   "experiments/*.jsonl" with a large red number counting up from 0 to 489, "logged runs", and the monospace
   list "who / agent / variant / commit / score". Right: a small box "router" with four lines fanning out to
   "price increase", "renewal", "RFQ", "raw material", caption "the measured winner per case type". Bottom:
   "an LLM picks the moves" is struck through in red, monospace beside it "measured worse: P07 0.728 vs 0.766 ·
   D02 0.67 vs 0.72".
10. 56–60 End. The envelope turns over. On its back, bold "csee-base" and, in serif italic, "code checks every
    euro." Nothing else on the frame. Hold to 60.0 s.

Rules
- Total length exactly 60 seconds. Keep every number and ID exactly as written above and in the script.
- No sound, no voice, no music, no stock footage, no generated people.
- Make numbers and timings easy to change later (we may update "489" before submission).
- Export as MP4, 1920×1080, 25 or 30 fps.
