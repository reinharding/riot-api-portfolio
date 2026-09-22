import pytest

from composite_metric import compute_composite_scores

TOP_ROW_A = {
    "match_id": "M1", "puuid": "p-a", "team_position": "TOP",
    "kills": 8, "assists": 4, "deaths": 2, "gold_earned": 14000,
    "damage_dealt_to_champions": 25000,
    "team_kills": 15, "team_damage": 50000, "game_duration_seconds": 1500,
}
TOP_ROW_B = {
    "match_id": "M2", "puuid": "p-b", "team_position": "TOP",
    "kills": 2, "assists": 2, "deaths": 6, "gold_earned": 9000,
    "damage_dealt_to_champions": 10000,
    "team_kills": 15, "team_damage": 50000, "game_duration_seconds": 1500,
}


def test_composite_score_matches_hand_calculated_example():
    rows = compute_composite_scores([TOP_ROW_A, TOP_ROW_B])
    by_match = {r["match_id"]: r["composite_score"] for r in rows}
    assert by_match["M1"] == pytest.approx(1.0)
    assert by_match["M2"] == pytest.approx(-1.0)


def test_composite_score_standardizes_within_role_not_across_roles():
    jungle_row_c = {
        "match_id": "M3", "puuid": "p-c", "team_position": "JUNGLE",
        "kills": 10, "assists": 5, "deaths": 3, "gold_earned": 16000,
        "damage_dealt_to_champions": 30000,
        "team_kills": 20, "team_damage": 60000, "game_duration_seconds": 1500,
    }
    jungle_row_d = {
        "match_id": "M4", "puuid": "p-d", "team_position": "JUNGLE",
        "kills": 1, "assists": 1, "deaths": 8, "gold_earned": 6000,
        "damage_dealt_to_champions": 5000,
        "team_kills": 20, "team_damage": 60000, "game_duration_seconds": 1500,
    }

    rows = compute_composite_scores([TOP_ROW_A, TOP_ROW_B, jungle_row_c, jungle_row_d])
    by_match = {r["match_id"]: r["composite_score"] for r in rows}

    assert by_match["M1"] == pytest.approx(1.0)
    assert by_match["M2"] == pytest.approx(-1.0)
