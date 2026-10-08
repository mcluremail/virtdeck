"""Fleet Health (milestone M4): summary report across all independent clusters.

Layer between the domain and the UI: cluster data collection via the
provider (`collector`) with source isolation. The transport is swapped
out by the test harness (tests/harness) — no sockets in tests.
Concurrent fan-out over clusters and subscriptions are the UI worker's
concern (M4.5).
"""
