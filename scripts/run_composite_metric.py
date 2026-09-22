"""Report Player A's composite performance score per game, gated on the 30-game floor (ticket 05)."""
from composite_metric import compute_composite_scores, fetch_participant_rows
from db import session
from game_floor import check_game_floor
from pipeline import load_tracked_puuids


def main():
    puuid = load_tracked_puuids()[0]
    with session() as conn:
        gate = check_game_floor(puuid, conn=conn)
        print(f"Game floor: {gate['status']} ({gate['game_count']} ranked games)")
        if gate["status"] != "ready":
            print("Below the 30-game floor -- keep ingesting, no model run yet.")
            return

        rows = fetch_participant_rows(conn=conn)
        scores = compute_composite_scores(rows)
        player_scores = [s for s in scores if s["puuid"] == puuid]
        player_scores.sort(key=lambda s: s["match_id"])
        for s in player_scores:
            print(f"{s['match_id']} ({s['team_position']}): {s['composite_score']:.3f}")


if __name__ == "__main__":
    main()
