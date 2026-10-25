# Claude Motion prompt v2 (visual revision)

How to use: open the existing Motion animation from v1 and paste everything below the line as a revision request.
Or start a new Motion, attach `SCRIPT_v1.md`, and paste it. Export as MP4 at 1920×1080. It stays silent; we add the
voice and re-time scenes to it ourselves.

---

Revise this 60-second technical explainer. Keep the style: cream paper (#f1ebdc), charcoal ink (#2b2a28), Didot
for big numbers, Helvetica Neue for text, Menlo for IDs, and the window envelope at the start and end. Keep the
scene order and roughly the same timings. Fix the following, which a judge review flagged:

Global
1. No empty frames. When a scene changes, the next scene's first element must appear before the previous one has
   fully cleared, with an overlap of about 0.4 s. Never show a blank or nearly blank frame. Hold each scene's last
   full state until the next scene starts.
2. Legibility at laptop size. No text smaller than 24 px. All grey secondary text and monospace no lighter than
   #57524a. Dimmed (inactive) boxes at 0.55 opacity, not fainter. Checkmarks in the same ink as their ID.
3. Exactly one oxide-red (#a63a2a) element per scene, plus the VERIFIED stamp in the writer scene. No ochre except
   the one highlight described in scene 5.
4. Use the whole frame. Content should sit around the optical centre, not crowded into the top-left with an empty
   bottom third.

Scene changes
- Scene 3, dossier: keep it. Make the checkmarks after "ctr:4600070110" and "sc:70110@2026Q3" clearly visible.
- Scene 5, negotiation policy: replace the monospace log line "plan r2: c^ 2.25% …" entirely. Instead:
  - Headline: "up to 3 packages per e-mail, not one counter-offer", with the "3" large and red.
  - Three paper cards in a row, appearing one by one:
    - "€128.76 / pay in 14 days / from Apr 2027"
    - "€132.48 / pay in 90 days / from Apr 2027"
    - "€124.53 / pay in 14 days / from Jan 2027"
  - Small caption: "our round-2 offer, practice case P01, priced by the cost engine".
  - Then an ochre frame highlights the first card, and text appears to the right: "supplier answers on 14-day
    terms: it values cash".
- Scene 6, writer: the caption under the struck-out ID ("an ID the model invented: deleted before sending") is grey,
  not red. Remove any stray typed characters.
- Scene 7, guardrails band: show it for at least 2 s, with text at 28 px or more.
- Scene 8, chart: keep the staircase 138.55 → 135.50 → 133.80 → 132.80 → 132.30 → 132.10 final. Make it about 30 %
  larger.
  - Add axis labels: "supplier's ask, € per unit" (vertical) and "step size per round" under the grey step values
    (−3.05, −1.70, −1.00, −0.50, −0.20). Remove empty ticks.
  - Right side, replacing the jargon:
    - big red "260", then "of our own sessions, fitted";
    - "they mirror our moves, / give less each round, / then send a final offer";
    - "one push after a final offer: supplier walked, 0.48 → 0";
    - bold "so we never push";
    - small "model of the bots fitted on our own back-office notes".
  - Remove "tit-for-tat", "shrinking cap", "fixed patience" and the citation line.
- Scene 9, testing:
  - Ladder rungs, top to bottom: "free sandbox, real bots", "fitted bot model", "one logged practice run".
  - Ledger counter counts to 590, labelled "logged results".
  - Router caption: "best-scoring version per case type".
  - Strike-through text: "Claude picks the moves". Next to it, at 30 px in grey Helvetica: "never beat our rules,
    and up to 20 s of a 60 s clock per move".
- Scene 10, end card: use the same window envelope as the opening (not a flap envelope). Regular-weight
  "csee-base" and italic Didot "code checks every euro." inside the window. No underline, no footer, nothing else.
  Hold to 60.0 s.

Keep every number exactly as written. Silent MP4, 1920×1080, 30 fps, exactly 60 s.
