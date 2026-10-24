# Demo video (60 s): script v3, "Hear the negotiation"

**Source:** practice case P01, session `d06ad94e8fafcc6e` (v15 + LLM writer, commit `c3c65e2`): **score 0.926**, 7 rounds, deal €134.80/unit from 2027-04-01, 30 days net. C_open €1,153,780 → C_deal €1,101,015, which is €52,764 below their opening offer; C_best €1,096,816.
**Concept:** the real email thread is the hero, voiced by ElevenLabs. The presenter appears only at the start and the end. All quotes below are verbatim from the replay (shortened with "…").

| Time | Who | Line | On screen |
|---|---|---|---|
| 0–8 | **PRESENTER** | "This foundry wants nine and a half percent more. For the Tacto Negotiation Arena, we built an AI buyer that negotiates this alone. By email. Listen." | presenter, then the letter |
| 8–12 | OWNER | "We can offer you a price of one hundred thirty-eight fifty-five per unit, valid from the first of November." | letter on paper, **+9.5 %** |
| 12–21 | BUYER | "We have not forgotten that in 2022 you kept supplying us at the old price for a full quarter. … Your letter gives fifty-one days' notice, while our agreement requires ninety." | our email; three packages appear as small term sheets (price × payment days × start date) |
| 21–23 | BACK OFFICE (whisper) | "My call: counter." | supplier's internal chat bubble |
| 23–28 | OWNER | "We checked the notice period data you cited; it holds. … We did not know that. A fair point." | three **VERIFIED** stamps (quality record, volume change, notice period) |
| 28–30 | OWNER | "Which figures is that based on?" | |
| 30–37 | BUYER | "Our own cost assessment of the casing tells us the current price is too low for you. We want to correct that." | a 14-days-payment package lights up (the owner asked for faster payment) |
| 37–40 | BACK OFFICE (whisper) | "My call: hold." … "My call: final offer." | |
| 40–45 | OWNER | "This is our final offer. One hundred thirty-four eighty, from the first of April." | |
| 45–47 | BUYER | "We accept your offer as stated." | stamp **AGREED** |
| 47–52 | (no voice) | | score bar fills: opening → our deal → best possible, **0.93** · **€52,764 below their opening offer** · "+6.5 % instead of +9.5 %, five months later" |
| 52–60 | **PRESENTER** | "Code sets every number. The language model only writes the words. We're csee-base. Our agent reads the supplier before it negotiates." | presenter, end card; footer `Practice session d06ad94e · emails and quotes verbatim` |

## Fact check

- 2022 loyalty is in the profile `persona.relationship_notes`, and the buyer cited it in every message.
- 51 vs 90 days notice, plus the 712 ppm complaint rate and the +10.1 % forecast also cited in round 1. All three came back `verified`.
- "Which figures is that based on?" is round 3. The buyer's answer quoting PPI-D351 and the cost assessment is round 3 as well.
- The 14-day payment option is round 3, package 2 (EUR 132.09). This matches the profile: the owner asked for 10-day payment.
- Back office: counter (rounds 1–3), hold (4), final_offer (5).
- Price: 126.53 → 134.80 is +6.5 %, against the +9.5 % ask, and the start date moves from 2026-11-01 to 2027-04-01.
- "Code sets every number": terms come from the lever engine's term sheets; the writer (template or LLM) only words them, and claim sentences stay verbatim (`docs/ARCHITECTURE.md`).
- Don't show the house agent's score (0.97) in the video. In the pitch, say it openly if asked.

## Voices (ElevenLabs)

- **OWNER:** older German man speaking English ("Heribert deutsch" or "Dieter der Erzähler").
- **BUYER:** calm, precise, neutral English voice (to pick).
- **BACK OFFICE:** the owner's voice as a whisper, lower in the mix.
- **PRESENTER:** recorded live, intro and outro only.

## Higgsfield

One shot only: H2, the foundry pour (5 s), under the owner's first line or the intro. Everything else is paper, type and stamps built in the edit.
