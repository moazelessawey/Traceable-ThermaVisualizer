# Contributing to Traceable.ThermaVisualizer

Thanks for helping! This is a community-oriented, GxP-adjacent tool: favor
traceability, explicitness, and tests over cleverness.

## Ground rules
- Requirements live in `PRD_Traceable_ThermaVisualizer.md`; cite requirement
  IDs (e.g. `INT-02`) in PR descriptions. If code and PRD disagree, open an
  issue first.
- AI coding agents must follow `AGENTS.md`.

## Development setup
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"