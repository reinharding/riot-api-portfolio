"""Role-adjusted composite performance metric (ticket 05)."""
from collections import defaultdict
from statistics import fmean, pstdev

from psycopg.rows import dict_row

from db import session
from game_floor import REMAKE_THRESHOLD_SECONDS


def _kill_participation(row: dict) -> float:
    return (row["kills"] + row["assists"]) / row["team_kills"]


def _damage_share(row: dict) -> float:
    return row["damage_dealt_to_champions"] / row["team_damage"]


def _deaths(row: dict) -> float:
    return row["deaths"]


def _gold_per_min(row: dict) -> float:
    return row["gold_earned"] / (row["game_duration_seconds"] / 60)


STAT_FUNCS = {
    "kill_participation": _kill_participation,
    "damage_share": _damage_share,
    "deaths": _deaths,
    "gold_per_min": _gold_per_min,
}
INVERTED_STATS = {"deaths"}


def _zscore(value: float, mean: float, stdev: float) -> float:
    # A role with zero variance on a stat (e.g. only one row ingested so
    # far) can't say whether this game was above or below normal -- 0 is
    # the "no signal yet" answer, not a crash.
    return 0.0 if stdev == 0 else (value - mean) / stdev


def compute_composite_scores(rows: list[dict]) -> list[dict]:
    """Per-game composite performance score, standardized within role.

    Each row's kill participation, damage share, deaths, and gold/min are
    z-scored against every other ingested row sharing the same
    team_position (across all games, not just this one), then averaged.
    Deaths are inverted before averaging so a higher composite always
    means better performance.
    """
    rows_by_role = defaultdict(list)
    for row in rows:
        stats = {stat: fn(row) for stat, fn in STAT_FUNCS.items()}
        rows_by_role[row["team_position"]].append((row, stats))

    results = []
    for role, role_rows in rows_by_role.items():
        means = {}
        stdevs = {}
        for stat in STAT_FUNCS:
            values = [stats[stat] for _, stats in role_rows]
            means[stat] = fmean(values)
            stdevs[stat] = pstdev(values)

        for row, stats in role_rows:
            z_scores = []
            for stat in STAT_FUNCS:
                z = _zscore(stats[stat], means[stat], stdevs[stat])
                z_scores.append(-z if stat in INVERTED_STATS else z)
            results.append({
                "match_id": row["match_id"],
                "puuid": row["puuid"],
                "team_position": role,
                "composite_score": fmean(z_scores),
            })
    return results


def fetch_participant_rows(conn=None) -> list[dict]:
    """Every ingested participant row, joined with its match duration and its
    team's totals for that game -- the population compute_composite_scores
    standardizes against, and the raw material for each row's own stats.
    """
    with session(conn) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    p.match_id, p.puuid, p.team_position,
                    p.kills, p.assists, p.deaths, p.gold_earned, p.damage_dealt_to_champions,
                    m.game_duration_seconds,
                    tk.team_kills, td.team_damage
                FROM participants p
                JOIN matches m ON m.match_id = p.match_id
                JOIN (
                    SELECT match_id, team_id, SUM(kills) AS team_kills
                    FROM participants GROUP BY match_id, team_id
                ) tk ON tk.match_id = p.match_id AND tk.team_id = p.team_id
                JOIN (
                    SELECT match_id, team_id, SUM(damage_dealt_to_champions) AS team_damage
                    FROM participants GROUP BY match_id, team_id
                ) td ON td.match_id = p.match_id AND td.team_id = p.team_id
                WHERE p.team_position IS NOT NULL AND m.game_duration_seconds >= %(remake_threshold)s
                """,
                {"remake_threshold": REMAKE_THRESHOLD_SECONDS},
            )
            return cur.fetchall()
