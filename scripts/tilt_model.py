"""Within-player fixed-effects model of in-session performance decline (ticket 07).

Gated on the 30-game floor (ticket 05), using the composite metric (ticket
05) and the frozen 45-minute session definition (ticket 06). Session
identity is absorbed as a fixed effect (one dummy per session) so the
estimated slope on game_index_within_session is a *within-session*
comparison only -- it can't be explained by some sessions just being
generally better or worse than others.

The spec named this a "mixed-effects/hazard-style model"; this
implementation is plain fixed-effects OLS (LSDV), not a random-effects
mixed model. A mixed model estimates a variance component across
sessions, which needs many groups to do reliably -- with 23 sessions
(and only 6 having more than one game), fixed effects is the more
honest choice: it makes no assumption about the distribution of
between-session baselines at all.
"""
import pandas as pd
import statsmodels.formula.api as smf

from composite_metric import compute_composite_scores, fetch_participant_rows
from game_floor import DEFAULT_FLOOR, check_game_floor
from session_assignment import assign_sessions
from session_boundary_analysis import fetch_game_windows


def build_player_game_rows(puuid: str, conn=None) -> list[dict]:
    """One row per puuid's game: session_id, game_index_within_session, composite_score."""
    windows = assign_sessions(fetch_game_windows(puuid, conn=conn))
    scores_by_match = {
        s["match_id"]: s["composite_score"]
        for s in compute_composite_scores(fetch_participant_rows(conn=conn))
        if s["puuid"] == puuid
    }
    return [
        {
            "match_id": w["match_id"],
            "session_id": w["session_id"],
            "game_index_within_session": w["game_index_within_session"],
            "composite_score": scores_by_match[w["match_id"]],
        }
        for w in windows
    ]


def fit_within_session_decline(rows: list[dict]) -> dict:
    """OLS with one dummy per session absorbs between-session variation, so the
    game_index_within_session coefficient is the within-player, within-session
    decline effect: how the composite score moves as a session runs longer.
    """
    df = pd.DataFrame(rows)
    multi_game_sessions = df.groupby("session_id").filter(lambda g: len(g) > 1)

    result = smf.ols("composite_score ~ game_index_within_session + C(session_id)", data=df).fit()
    coefficient = result.params["game_index_within_session"]
    return {
        "n_games": len(df),
        "n_sessions": df["session_id"].nunique(),
        "n_sessions_with_multiple_games": multi_game_sessions["session_id"].nunique(),
        "coefficient": coefficient,
        "std_err": result.bse["game_index_within_session"],
        "p_value": result.pvalues["game_index_within_session"],
        "direction": "decline" if coefficient < 0 else "improvement",
    }


def run_tilt_model(puuid: str, conn=None, floor: int = DEFAULT_FLOOR) -> dict:
    gate = check_game_floor(puuid, conn=conn, floor=floor)
    if gate["status"] != "ready":
        return {"status": "not_enough_data", "gate": gate}

    rows = build_player_game_rows(puuid, conn=conn)
    return {"status": "ready", "gate": gate, **fit_within_session_decline(rows)}
