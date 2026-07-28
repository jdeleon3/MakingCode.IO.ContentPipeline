"""Local web dashboard (TDD 10.10, ADR-009). Optional -- `pip install ce[gui]`.

Hard rule the whole package follows: never import a pipeline module
(`harvest/`, `produce/`, `gates/`, ...) and never reimplement its logic.
Every screen only (a) reads a file `ce.store` already knows how to read,
(b) writes to the exact file the CLI would write, or (c) shells out to the
real `ce` entry point via `runner.py`. One implementation of "what the
pipeline does" -- this package is never it.
"""
