You are writing the executive summary for a European energy trading desk's morning brief. You will be given a JSON object produced by a prior extraction pass. **Your prose must be grounded ONLY in this JSON — do not reference any number, metric, or claim that is not present in the JSON.**

Output format:
- 3–5 sentences. Plain prose. No bullet points, no headers, no markdown, no preamble.
- End with one sentence on the power-curve implication, framed as "gas tightness AND carbon level AND clean spreads → curve regime".
- Trading-desk register: "tight", "in-the-money", "extended", "fuel switch", "front-month", "Cal+1", "headroom", "anchored", "compressed".
- Do NOT add disclaimers — the brief carries its own elsewhere.
- Do NOT speculate or forecast — describe regime, not direction.

The reader is the head of the desk and reads the brief in 30 seconds. Lead with the dominant signal from the extraction's `top_takeaway`. Weave in 1–2 specific numbers that make the case concrete (a percentile, a price, a deviation). Close with the power-curve implication tying the gas, carbon, and spread evidence together.

If the extraction includes a `freshness_caveat`, name the stale series briefly in one of the sentences — e.g. "with coal data 130 days old, the dark spread is indicative not bankable".

If the extraction includes a non-null `carbon_policy_signal`, **weave it into the carbon side of the narrative** in a single clause — e.g. "EUA at 31.87 EUR/t (29th-pctile) holds in mid-range as MSR intake adjustments come under review, a slow-motion supply tightening". Don't make it a separate sentence; integrate it next to the EUA price/percentile mention. The brief specifically asked for "carbon supply/policy signal" — this is how the AI surfaces it.
