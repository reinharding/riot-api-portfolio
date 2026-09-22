# Phase 4 finding: within-session performance decline ("tilt")

**Model:** `scripts/tilt_model.py`, run via `scripts/run_tilt_model.py`. OLS regression of the composite performance z-score (ticket 05) on `game_index_within_session`, with one fixed-effect dummy per session (ticket 06's frozen 45-minute gap definition). The session dummies absorb any between-session baseline difference, so the coefficient on `game_index_within_session` is a within-player, within-session comparison only: does *this session*'s Nth game score differently from *this session*'s 1st game, on average across all of Player A's sessions.

The original spec named this a "mixed-effects/hazard-style model"; this is deliberately plain fixed-effects OLS instead. A random-effects mixed model estimates a variance component across groups, which needs many groups to do reliably -- with 23 sessions (6 of them multi-game), fixed effects is the more honest choice here: it makes no distributional assumption about between-session baselines at all, at the cost of not being able to generalize the baseline variance to a hypothetical future session.

## Result (36 ranked games, 23 sessions, run 2026-09-22)

| | |
|---|---|
| Games | 36 |
| Sessions | 23 |
| Sessions with 2+ games (the only ones informing the slope) | 6 |
| Coefficient (composite z-score per additional game in-session) | +0.168 |
| Standard error | 0.139 |
| p-value | 0.252 |
| Direction | improvement, not decline |

**No statistically significant decline was detected.** The point estimate is even in the opposite direction from the "tilt" hypothesis (performance nominally improves, not worsens, later in a session), and the effect is far from significant (p = 0.25, roughly a 1.2-sigma result).

## Why this result should not be over-read

- **The model's real sample size is much smaller than 36 games suggests.** Of 23 sessions, only 6 contain more than one game — those 6 are the only source of within-session comparison; single-game sessions contribute nothing to the slope estimate beyond fixing their own intercept. Effectively, this is a slope estimated from roughly a dozen within-session game-pairs, not 36 games.
- **Survivorship bias could mask a real effect in either direction.** If Player A tends to stop playing (end the session) right after a bad game, the worst in-session performances are disproportionately *last* games — which this model would count as evidence of decline. But if Player A instead just plays fewer, shorter sessions overall and doesn't specifically quit on bad games, that channel doesn't apply. We have no direct measurement of *why* a session ended (an intentional stop vs. a bad-game reaction), so this is a real, undecided threat to any causal read of the coefficient's sign, not just its size.
- **The 30-game floor is a floor on ingested games, not on statistical power for this specific model.** Ticket 05's gate is deliberately about having *some* baseline data before running any model at all, and it was met (36 >= 30). But this model's power depends specifically on multi-game sessions, which is a stricter and much smaller requirement that the floor doesn't check for.

## Conclusion

At the current sample size, there is no evidence of in-session tilt for Player A. The honest, defensible statement is "not enough same-session repeated play has been observed yet to detect an effect, if one exists" -- not "no tilt effect exists." More ingested games, specifically more *multi-game sessions*, would be needed to give this model real power. This finding should be revisited as ingestion continues; it should not be re-run purely to search for a more favorable result, since that would reintroduce the circularity ticket 06 was designed to avoid.
