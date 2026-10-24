# Negotiation research: what the literature says about our supplier bots

Sat 24 Oct, evening. A deep-research subagent compared the literature with the supplier-engine model (scratchpad `sub-engine`). Rough effect sizes come from the engine model, not from practice runs.

## The opponent we face

The Tacto supplier bot is a rule engine; an LLM only writes its e-mails. Its rules:

- **Steps:** it mirrors our concession up to a cap that shrinks each round.
- **Final offer:** it sends one at reply N, or earlier once our gap exceeds G.
- **Agreement:** it agrees to any of our sheets worth at least its current ask.

The literature calls this a behaviour-dependent **tit-for-tat** tactic (Faratin, Sierra & Jennings 1998, "Negotiation decision functions").

Against a capped mirror, the best response is to **concede exactly what it will reciprocate, as early as possible**. That is the opposite of the slow early concession ("Boulware") that won much of the ANAC competitions. A simple reciprocity rule with no opponent model beat the ANAC 2018/2019 top agents ([de Jonge 2022, MiCRO](https://www.iiia.csic.es/~davedejonge/homepage/files/articles/2022%20-%20de%20Jonge%20-%20MiCRO.pdf)).

In this engine model:

    price ≈ opening ask − min(gap0 / 2, Σ_t min(our step_t, cap_t)) − argument effects

## Ranked ideas

1. **Concede the cap from reply 1.**
   - Probe at about 1.3× the expected cap in reply 1, then step at about 1.05× the estimated next cap.
   - Today `next_terms` limits our step to the supplier's last step × `follow_share`, which makes its next step smaller.
   - Fall back to base pacing when the supplier does not reciprocate: ρ = its step / our step, much below 1.
2. **Compute the anchor from its limits.** Set the opening gap to min(gap trigger − safety, 2 × sum of caps). A wider gap buys nothing and brings the final offer sooner, which is consistent with v18 (12 % anchor) beating v14 (22 %).
3. **At the close, send three sheets each worth exactly its ask to the supplier** but cheapest for us, plus its own final sheet as a fallback.
   - Sources: equal-utility trade-offs ([Faratin et al. 2002](https://eprints.soton.ac.uk/256872/1/aij03-faratin.pdf)), MESOs ([Leonardelli et al. 2019](https://researchers.mq.edu.au/en/publications/multiple-equivalent-simultaneous-offers-mesos-reduce-the-negotiat/)), and Pactum/Walmart trade-off menus ([PYMNTS](https://www.pymnts.com/news/artificial-intelligence/2023/walmart-finds-75-percent-vendors-prefer-negotiating-with-chatbot/partial/)).
4. **Learn the supplier's value function during the session.** Use frequency-style updates from the terms it never moves, which of our sheets it counters from, and preferences named in its e-mails ([Tunalı et al. 2017](https://research.tudelft.nl/en/publications/rethinking-frequency-opponent-modeling-in-automated-negotiation)).
5. **Cite only the argument kinds that move the engine, and cite them early.**
   - Kinds that work: cost-index falls on drivers it names and does not hedge, should-cost, rival quotes, forecasts, notice periods.
   - Never cite order history or delivery/quality records.
6. **Protect the number of rounds.** Extraction is the sum of caps over the rounds actually played, so latency in the 8-minute final waves costs money.
7. **Push after a final offer only when it pays:** P(improve) × gain > P(walk) × loss ([Baarslag et al., Accepting optimally](https://eprints.soton.ac.uk/373623/1/Accepting_20Optimally_20in_20Automated_20Negotiation_20with_20Incomplete_20Information.pdf)). Our logs say that is almost never.
8. **Relationship goals:** stop at the supplier's sustainable margin, then spend the remaining reciprocity on non-price terms.

## Rejected for this setting

- **Boulware, or small early and large late concessions.** Against a decaying cap these give up concessions.
- **Psychology:**
  - warmth, dominance or gratitude ([MIT competition, Vaccaro et al. 2025](https://arxiv.org/html/2503.06416v3));
  - feigned desperation ([NegotiationArena](https://arxiv.org/pdf/2402.05863));
  - precise numbers.

  These act on LLM deciders; ours decides by rules.
- **Prompt injection.** Against the spirit of the rules and bad for the pitch.
- **Reinforcement learning or Gaussian-process opponent models.** About 4 replies per session is too little data.

## Open questions that decide how much of 1–3 turns into score

1. Is the mirror measured in euros, in % of the gap, or in the supplier's value units?
2. Do replies without a concession count toward N?
3. Is the gap trigger measured on price or on value?
4. When several of our sheets are acceptable, does it take the first one or the best one for itself?
