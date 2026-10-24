# Demo video (60 s): storyboard v1

**Status:** draft for review. Nothing generated or rendered yet.
**Story:** Gießerei Brandlhuber asks +9.5 %. Our agent reads the supplier, avoids an empty threat, cites two facts, the owner checks them and concedes. Practice case P01, session `8deaffac5183ffcb`.
**Style:** `editorial-film-edit` skill: soft archival editorial, cream paper and charcoal, ochre and oxide-red accents, light temporal grain, bright neutral B&W, three type roles.

## Format

| | |
|---|---|
| Master | 1920×1080, 25 fps, H.264/AAC MP4, 60.0 s |
| Type | Helvetica Neue (information), Didot incl. italic (accent words and numerals), Menlo (source IDs). All three are installed on this Mac. |
| Palette | cream paper, charcoal, dusty ochre (our side), oxide red (markings, stamps) |
| Grain | fine, monochrome, new pattern every frame; off on type layers |
| Stepped motion | selected type entrances update every 2 frames (12.5/s); everything else at 25 fps |
| Voices (ElevenLabs) | **OWNER**: older German man speaking English with a German accent. Candidates: "Heribert deutsch" (`yR6YPi6ytQSGBZ0uKFQl`), "Dieter der Erzähler" (`cLemPw4efsDYbUMhZbhl`). **NARRATOR**: calm English voice, to pick. |
| Music | none in v1. Optional low drone later; then also deliver a version without it. |

The agent never speaks in the video. People talk, the agent writes. Its words appear only as type.

## Shot list

### S1 · 0.0–5.0 · The letter
- **Picture:** overhead, slow push-in on a typed business letter landing on a charcoal desk among stacked envelopes. Soft B&W. *(Higgsfield image + slow push in the edit)*
- **Type:** Didot numeral **+9.5 %** lands centre right (stepped entrance). Menlo below: `doc:20260911-70110-P01`.
- **OWNER:** "Guten Tag. We can offer you a price of one hundred thirty-eight fifty-five per unit… valid from the first of November."
- **Source:** opening offer text: €138.55, valid from 1 Nov 2026.

### S2 · 5.0–10.0 · The foundry
- **Picture:** small family iron foundry, molten iron poured into a sand mould, sparks, one worker in silhouette. Bright B&W, the molten glow kept as the only warm ochre highlight. *(Higgsfield video)*
- **Type:** Helvetica **185 people. One family.** Menlo: `profile sup:70110 · sole source, HN 50-200 volute casing`.
- **NARRATOR:** "A family foundry. The only source for this part. And it wants nine and a half percent more."
- **Source:** profile 70110: owner_type family, staff 185, sole source, asks +9.5 %.

### S3 · 10.0–22.0 · The agent reads the supplier *(wow beat 1)*
- **Picture:** collage on cream paper: a large photographic eye (B&W) above the letter, thin oxide-red registration lines. The real reference IDs appear along the lines one by one: `ctr:4600070110` · `sc:70110@2026Q3` · `doc:20260902-70110-M2` · `cost:310010`. *(Higgsfield image of the eye; paper, lines and IDs are our layers)*
- **Type**, three facts, about 3.5 s each, one large word at a time:
  1. Didot **51 days** / Helvetica "notice given" / small "90 required by contract" / Menlo `ctr:4600070110`
  2. Didot **85.2 %** / Helvetica "on-time delivery, slipping to amber" / Menlo `sc:70110@2026Q3`
  3. Didot italic *"Could you pay our invoices within 10 days?"* / Helvetica "He needs cash." / Menlo `doc:20260902-70110-M2`
- **NARRATOR:** "Before it answers, our agent reads everything. The contract. The scorecard. The owner's own emails."
- **Source:** profile 70110 (notice 90, OTD 85.2 %, amber, cash pressure quote), our reply text.

### S4 · 22.0–27.0 · What not to say *(wow beat 2)*
- **Picture:** clean cream paper, carbon-copy texture.
- **Type:** Helvetica line types itself: "Threaten to move the part to Kalwisz", then an oxide-red strike-through draws across it. Below in Menlo: `Kalwisz quoted €143.22, above the ask. An empty threat.` `quote:7200001`
- **NARRATOR:** "It also knows which threat would be empty."
- **Source:** profile 70110, `arguments_to_avoid`.

### S5 · 27.0–35.0 · The reply
- **Picture:** our email as typeset paper, key phrases underlined in ochre as they are read.
- **Type** (real email lines):
  - "Your letter gives **51 days' notice**, while our agreement requires **90 days**."
  - "Your on-time delivery was **85.2 %**."
  - "We propose **EUR 135.29** per unit, valid from **2027-04-01**, payment at 30 days net."
  - Menlo bottom right: `numbers: code · wording: language model`
- **NARRATOR:** "Code decides every number. The language model only finds the words."
- **Source:** buyer message, round 1.

### S6 · 35.0–45.0 · The other side of the desk *(wow beat 3)*
- **Picture:** the owner at a cluttered office desk next to the foundry floor, reading a letter, pausing, slowly taking off his glasses. Bright B&W. *(Higgsfield video, the key shot)*
- **Type:** two oxide-red rubber stamps land on paper inserts: **VERIFIED · notice period** and **VERIFIED · delivery record**. Then Didot italic *a fair point.* fades in and **stays across the cut into S7** (continuing phrase).
- **OWNER** (quieter, half to himself): "We checked the notice period… it holds." *(pause)* "We did not know that. A fair point."
- **Source:** supplier round 1: claim_results verified ×2, quote verbatim.

### S7 · 45.0–52.0 · The deal
- **Picture:** close-up of a vintage mechanical adding machine; the paper tally roll curls out. *(Higgsfield video; the numbers are our layer printed onto the roll, never generated)*
- **Type on the roll:** `138.55 → 137.80` · `01.11.2026 → 01.04.2027` · then Didot **€43,704** with Helvetica "saved on one part".
- **NARRATOR:** "Five more months at the old price. Forty-three thousand euros, on one part."
- **Source:** accepted offer: €137.80 from 2027-04-01. c_open − c_deal = €43,704.

### S8 · 52.0–57.0 · Scale
- **Picture:** eight paper slips slide in as a grid, one per practice negotiation, each with its saving in Menlo. A Didot total settles in the middle.
- **Type:** **€647,314** / Helvetica "saved across 8 practice negotiations".
- **NARRATOR:** "Eight negotiations. Six hundred forty-seven thousand euros."
- **Source:** latest practice deals, c_open − c_deal summed. **Recompute before export**, since newer runs change it.

### S9 · 57.0–60.0 · End card
- **Picture:** cream paper, grain only.
- **Type:** Helvetica **csee-base** · Didot italic *reads the supplier before it negotiates.*
- Small Menlo footer: `Scenes are illustrations. Emails, numbers and quotes from practice session 8deaffac.`
- **Audio:** silence or room tone.

## Higgsfield prompts (English, for approval)

No readable lettering is generated; all text is our own layer. Style across shots: soft archival photograph, bright neutral black-and-white, fine film grain, gentle highlight bloom, muted, no glossy CGI.

| # | Kind | Prompt |
|---|---|---|
| H1 · S1 | image | Overhead view of a dark charcoal wooden desk in a German pump factory purchasing office, 1990s, a single typed business letter lying on top of a small stack of envelopes, a fountain pen beside it, soft grey morning window light from the left, bright neutral black-and-white archival photograph, fine grain, shallow depth of field, letter text illegible and soft, generous empty space on the right third for captions, 16:9. |
| H2 · S2 | video 5 s | Inside a small family-run iron foundry in Bavaria, molten iron poured from a ladle into a sand mould, sparks rising, one worker in heavy apron in silhouette, smoke catching the light, bright neutral black-and-white archival film look with the molten iron as the only warm glowing highlight, fine grain, soft bloom, static camera with a very slow push-in, calm, empty dark area upper left for a caption, 16:9. |
| H3 · S3 | image | Extreme close-up of one human eye, calm and attentive, photographed in bright neutral black-and-white, soft studio light, fine grain, printed on slightly textured cream paper as part of an editorial collage, eye occupying the upper half, lower half plain paper, 16:9. |
| H4 · S6 | video 5–8 s | A man in his sixties, owner of a small German family foundry, sitting at a cluttered office desk with order folders and a casting sample, a window to the foundry floor behind him, he reads a typed letter, pauses, then slowly takes off his reading glasses and looks down thoughtfully, bright neutral black-and-white archival film look, fine grain, soft window light, medium close-up, locked-off camera, no text, 16:9. |
| H5 · S7 | video 5 s | Close-up of a vintage mechanical adding machine on a desk, its paper tally roll slowly feeding out and curling over the edge, keys and metal lever in soft focus, bright neutral black-and-white with warm cream paper tone, fine grain, gentle bloom on the metal, slow lateral camera drift, the paper roll blank and clean, 16:9. |

**Budget (110 credits on the trial):** H4 is required, then H2 and H5. H1 and H3 are images (cheap). Get a price quote per shot before generating; aim for about 80 credits, keeping one retry for H4. Use Seedance 2.5 if the account offers it; don't switch models without saying so.

## Voice lines (ElevenLabs)

| # | Voice | Line | ~s |
|---|---|---|---|
| V1 | OWNER | Guten Tag. We can offer you a price of one hundred thirty-eight fifty-five per unit… valid from the first of November. | 5 |
| V2 | NARRATOR | A family foundry. The only source for this part. And it wants nine and a half percent more. | 5 |
| V3 | NARRATOR | Before it answers, our agent reads everything. The contract. The scorecard. The owner's own emails. | 6 |
| V4 | NARRATOR | It also knows which threat would be empty. | 2.5 |
| V5 | NARRATOR | Code decides every number. The language model only finds the words. | 4 |
| V6 | OWNER | We checked the notice period… it holds. … We did not know that. A fair point. | 6 |
| V7 | NARRATOR | Five more months at the old price. Forty-three thousand euros, on one part. | 4.5 |
| V8 | NARRATOR | Eight negotiations. Six hundred forty-seven thousand euros. | 3.5 |

## Open decisions

1. Narrator voice: pick from a short ElevenLabs list (free to browse).
2. Owner voice: "Heribert deutsch" or "Dieter der Erzähler" (previews are free).
3. S8: keep the practice total, or swap in the Live Final total for the pitch version.
4. Music: none, or a low drone.
