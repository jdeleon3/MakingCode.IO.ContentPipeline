"""Safety gates (TDD §6). Each gate is a small module raising `GateBlocked`
(exit code 2) rather than returning a pass/fail value — ADR-005 makes G1 and
G2 fail closed and non-bypassable by `--force`, so "the gate ran and found a
problem" and "the caller forgot to check a return value" can't be confused.
"""
