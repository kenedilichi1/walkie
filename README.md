# walkie

Offline-first walk planner. Asks your preferences once, checks local weather,
picks today's best walk window with a local LLM (Ollama), reminds you before
it starts — and (later steps) builds a walking loop from an offline OSM
extract, matches a playlist, generates voice cues, and drops everything to
your phone over local WiFi. No cloud required after setup.

## Layout

```
walkie/
├── config/          # settings.yaml (region, paths), user_plan.json, quotes.txt
├── data/            # inputs: .pbf extracts, music/ (never written by the app)
├── src/walkie/      # all code (installable via src/ layout)
│   ├── cli.py       # walkie wizard|region|suggest|remind|daemon
│   ├── config.py    # paths + validated settings (ConfigError)
│   ├── models.py    # UserPlan / Weather / Proposal / TodayPlan dataclasses
│   ├── storage.py   # atomic JSON helpers
│   ├── llm.py       # the single Ollama client (system + user messages)
│   ├── weather.py   # Open-Meteo fetch + staleness-aware cache
│   ├── daylight.py  # sunrise/sunset/day length (astral, offline)
│   ├── ai/          # planning prompt + decision engine (plan.json)
│   ├── suggest/     # prompts / proposals / reminders
│   ├── ui/          # setup wizard + quick-adjust dialog (PyQt6)
│   ├── region.py    # Geofabrik OSM extract fetch
│   └── log.py, clock.py, __main__.py
├── tests/           # unit/ (pytest, incl. offscreen Qt smoke tests)
├── output/          # generated at runtime (gitignored)
├── docs/            # build_logic.md, test_protocol.md
└── scripts/         # setup_env.sh
```

## Quickstart

```bash
make setup        # venv + deps + Ollama model + region fetch
make region       # re-detect location / fetch OSM extract
make wizard       # one-time preference setup (PyQt)
make suggest      # today's walk proposal (weather + local LLM)
make plan         # AI decision engine -> output/plans/plan.json
make daemon       # reminders until today's walk is approved
make test         # pytest
make lint         # ruff
make typecheck    # mypy
```

Every `make` target is just `python -m walkie <command>`; after
`pip install -e .` the `walkie` console script works too:

```bash
walkie suggest --edit   # quick-adjust today's walk
walkie remind           # fire due reminders once (cron-friendly)
```
