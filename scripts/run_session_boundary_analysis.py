"""Print the session gap-threshold sensitivity table for Player A (ticket 06)."""
import os

from session_boundary_analysis import compute_gaps_minutes, fetch_game_windows, sensitivity_table


def main():
    puuid = os.environ["TRACKED_PUUIDS"].split(",")[0].strip()
    windows = fetch_game_windows(puuid)
    gaps = compute_gaps_minutes(windows)
    print(f"{len(windows)} non-remake ranked games, {len(gaps)} inter-game gaps")
    for row in sensitivity_table(gaps):
        print(
            f"threshold={row['threshold_min']:>4} min -> {row['session_count']} sessions "
            f"(avg {row['avg_games_per_session']:.2f} games/session)"
        )


if __name__ == "__main__":
    main()
