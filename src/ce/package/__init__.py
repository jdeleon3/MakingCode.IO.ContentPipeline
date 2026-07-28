"""`ce package <piece-id>` (TDD 10.8, 12 WP-13) -- assembles `outbox/<id>/`.

`builder.py` owns filesystem assembly (copying assets, gathering renditions,
writing the result); `review_html.py` owns turning that gathered data into
the single self-contained `REVIEW.html` file (ADR-006). Split the same way
`assets/__init__.py` (orchestration) and `assets/_render.py` (pure HTML
rendering) are split in WP-11.
"""

from __future__ import annotations
