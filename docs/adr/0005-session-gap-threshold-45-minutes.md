# Session gap threshold frozen at 45 minutes, via sensitivity testing on timestamps alone

A "session" (per `CONTEXT.md`) needs a maximum gap between one game's end and the next game's start, beyond which two games belong to different sessions. Picking this threshold by eye, or worse, by checking which value best reproduces an expected tilt effect, would make ticket 07's model circular: the session boundary would be tuned to manufacture the result it's supposed to test for. This threshold is therefore selected using only Player A's raw game-timestamp/duration data (via `scripts/session_boundary_analysis.py`) — the composite performance metric (ticket 05) is never read during selection.

Player A's 36 ingested non-remake ranked games produce 35 inter-game gaps. Sorted, they split cleanly into two clusters: 12 gaps of 2.8-27.2 minutes (immediate requeue) and the rest starting at 39.5 minutes and climbing into hours. Trying candidate thresholds from 10 to 240 minutes and counting the resulting sessions shows a plateau — a range where the session count doesn't change as the threshold moves — from 40 to 60 minutes, holding at 23 sessions across that entire 20-minute range. No other candidate range is as wide, so 40-60 minutes is the most threshold-insensitive choice available in this data, and 45 minutes (its midpoint) is locked in.

| Threshold (min) | Sessions | Avg games/session |
|---|---|---|
| 10-15 | 26-27 | 1.33-1.38 |
| 20-35 | 24-25 | 1.44-1.50 |
| **40-60** | **23** | **1.57** |
| 75-90 | 21-22 | 1.64-1.71 |
| 120-150 | 18 | 2.00 |
| 180-240 | 11-14 | 2.57-3.27 |

This threshold will need re-testing once more games are ingested, since 36 games is a thin sample for locating a stable plateau -- but it must not be re-tuned by looking at how it affects the tilt finding once picked.
