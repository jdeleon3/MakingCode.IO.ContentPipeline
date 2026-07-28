"""Post-back & metrics (TDD 12 WP-15): `ce posted`, `ce metrics pull`.

`umami.py` and `youtube.py` are the two external-data seams (each a
`Protocol` + a real httpx-backed client, same DI shape as every other
provider in this codebase). `pull.py` owns the orchestration: refreshing
`data/posted.yml` and regenerating `data/performance.md`.
"""

from __future__ import annotations
