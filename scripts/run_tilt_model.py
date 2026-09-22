"""Run the within-player tilt model for Player A and print the result (ticket 07)."""
from db import session
from pipeline import load_tracked_puuids
from tilt_model import run_tilt_model


def main():
    puuid = load_tracked_puuids()[0]
    with session() as conn:
        result = run_tilt_model(puuid, conn=conn)

    if result["status"] != "ready":
        gate = result["gate"]
        print(f"Below the 30-game floor ({gate['game_count']} games) -- keep ingesting, no model run.")
        return

    print(f"{result['n_games']} games across {result['n_sessions']} sessions "
          f"({result['n_sessions_with_multiple_games']} with 2+ games)")
    print(f"Within-session slope: {result['coefficient']:+.3f} per additional game "
          f"(SE {result['std_err']:.3f}, p={result['p_value']:.3f}) -- {result['direction']}")


if __name__ == "__main__":
    main()
