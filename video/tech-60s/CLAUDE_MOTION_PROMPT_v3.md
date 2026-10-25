Make a 60-second, 16:9 (1920×1080, 30 fps) animated technical explainer for a hackathon submission. It explains how our autonomous AI buyer agent "csee-base" works and why we designed it this way. The video is SILENT: no voice, no music. A narration will be added later, so follow the timings below closely. No footage, no people, no stock images. It should be animated type, simple line drawings, paper cards and one chart. Do not invent any numbers, names or quotes; use exactly the text given.

Background for you (do not show it): in the Tacto Negotiation Arena, our AI buyer negotiates by e-mail with 1–3 supplier bots. It is scored on total cost, not just unit price. Our design rule is that code computes every number, and the language model (Claude) only reads and writes the e-mails.

STYLE
- Cream paper background (#f1ebdc) with a faint vignette. Charcoal ink (#2b2a28). Secondary text in dark grey (#57524a), never lighter.
- Exactly ONE oxide-red (#a63a2a) word or number per scene, as marked below with [red]. The only other colour is one ochre (#b8924a) highlight frame in scene 5.
- Fonts: Didot (high-contrast serif) for big numbers and the red words; Helvetica Neue for text; Menlo (monospace) only for small IDs. No text smaller than 24 px.
- Motion: things draw, type or slide in. Nothing bounces or spins. Lines draw like ink, and stamps land with a quick scale-down.
- No empty frames. The next scene's first element appears before the previous scene has fully cleared (about 0.4 s overlap). Hold each scene's final state until the next scene starts.
- Use the whole frame. Content sits around the optical centre, not crowded into the top-left.
- Recurring device: a cream window envelope (an envelope with an address window), used at the start and at the end.

SCENES (seconds)

1. 0.0–4.5 Setup. The window envelope slides in from the left, with "to csee-base" in its window and small "Tacto Negotiation Arena" in the corner. To its right, three small envelopes appear one by one, then a stopwatch and "60 s" [red]. Caption: "1–3 supplier bots · e-mail · 60 s per thread". Second line, grey: "scored on total cost, not unit price".

2. 4.5–10.5 The rule. Blank paper. A line types itself in large Didot: "code decides every number." The word "code" is [red]. Below it, in Helvetica: "the language model only reads and writes". Then a smaller grey line: "bots price by rules: exact packages move them, eloquence doesn't".

3. 10.5–18.5 Box 1, supplier dossier. An architecture schematic starts along the lower third: a box "Supplier dossier" (sub-label "prepared offline") draws itself. Above it, four paper strips slide into a fanned stack, labelled "letter", "call note", "news" and "scorecard". Big "46" [red] with "suppliers profiled". Then: "only sourced facts: 0 of 244 fact-checks contradicted". Then a struck-through grey line: "order-history arguments: moved a price 0 times in 26, dropped".

4. 18.5–25.0 Box 2, cost engine. An arrow draws to a second box, "Cost engine" (sub-label "code"). Above it, a paper tally roll prints line by line: "total cost = price / + payment terms / + freight + lead time / + quality + index risk / + supplier health". Beside it: "matches the arena's cost" and, large, "to the euro" [red]. Then a small paper card: "copper price clause · predicted 0.736 · real session 0.733".

5. 25.0–32.5 Box 3, negotiation policy. An arrow draws to a third box, "Negotiation policy" (sub-label "code"). Headline above: "up to 3 packages per e-mail, not one counter-offer", with the "3" large and [red]. Three paper cards appear one by one:
   - "€128.76 / pay in 14 days / from Apr 2027"
   - "€132.48 / pay in 90 days / from Apr 2027"
   - "€124.53 / pay in 14 days / from Jan 2027"
   Small caption: "a real round-2 offer, priced by the cost engine". Then an ochre frame highlights the first card, and text appears to the right: "supplier answers on 14-day terms: it values cash". Last, a small grey line: "where suppliers ignored the menu, we switched it off".

6. 32.5–37.0 Box 4, writer. An arrow draws to a fourth box, "Writer" (sub-label "Claude, words only"). Above it, a paper e-mail reads: "Dear Mr Brandlhuber, thank you for your letter. Your letter gives 51 days' notice, while our agreement requires 90 days. We attach three packages that reflect this …". The sentence about 51 and 90 days gets an ochre underline, and a red stamp "VERIFIED" lands on the paper. Left of it: "verbatim" [red] in large Didot, with "numbers and facts pasted in unchanged" below. At 35.5 s a line draws under all four boxes, labelled "guardrails, in code: only the supplier's standing offer · never above our alternative · never push after a final offer · close before the time cap". All four boxes now read as one diagram.

7. 37.0–47.5 What we learned about the bots. The diagram clears. A large staircase chart draws step by step, one step every 0.9 s. It shows a supplier's asks in € per unit: 138.55, 135.50, 133.80, 132.80, 132.30 and "132.10 final". Under each step, in small grey, the step size: −3.05, −1.70, −1.00, −0.50, −0.20. Axis labels: "supplier's ask, € per unit" on the left and "step size per round" at the bottom. The last step and its label are the only red element besides the number below. Right side, in sequence:
   - big "260" [red] with "of our own sessions, modelled";
   - "they mirror our moves, / give less each round, / then send a final offer";
   - "we give exactly what they mirror: simulated walk-aways 36 → 3";
   - "one push after a final offer: 0.48 → 0";
   - in bold, "so we never push".

8. 47.5–54.5 How we tested. Left: a vertical line draws down, with three rungs labelled top to bottom "free sandbox", "bot model" and "one real practice run", and the label "every change climbs one ladder". Middle: a paper ledger card "logged results", with a large number counting from 0 to 590 [red] and a list: "who / agent / commit / score". Bottom: "Claude picks the moves" is struck through with a red line, and beside it in grey: "tested: never beat our rules".

9. 54.5–57.0 Result. Large Didot "0.81" beside a smaller grey "0.70". The caption under 0.81 reads "our best practice runs, average"; the caption under 0.70 reads "Tacto's own agent". Only "0.81" is [red].

10. 57.0–60.0 End. The same window envelope as the opening slides in. In its window: "csee-base" in regular-weight Helvetica, and below it "code checks every euro." in italic Didot. Nothing else on the frame: no footer, no underline. Hold until 60.0 s.

RULES
- Exactly 60.0 seconds. Silent MP4, 1920×1080, 30 fps.
- Use every number and text string exactly as written above.
- Keep numbers easy to edit later, especially "590".
