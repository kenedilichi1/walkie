# walkie

Offline-first walk planner. Asks your preferences once, checks local weather,
picks today's best walk window with a local LLM (Ollama), reminds you before
it starts — and builds a walking loop from an offline OSM extract, narrates
the turns with local voice cues (play your own music alongside it), and drops
everything to your phone over local WiFi. No cloud required after setup.

## Layout

```
walkie/
├── config/          # settings.yaml (region, paths), user_plan.json, quotes.txt
├── data/            # inputs: .pbf extracts, piper voices/, music/ (never written by the app)
├── src/walkie/      # all code (installable via src/ layout)
│   ├── cli.py       # walkie wizard|region|suggest|plan|route|voice|remind|daemon|run|serve
│   ├── config.py    # paths + validated settings (ConfigError)
│   ├── models.py    # UserPlan / Weather / Proposal / TodayPlan dataclasses
│   ├── storage.py   # atomic JSON helpers
│   ├── llm.py       # the single Ollama client (system + user messages)
│   ├── weather.py   # Open-Meteo fetch + staleness-aware cache
│   ├── daylight.py  # sunrise/sunset/day length (astral, offline)
│   ├── geo.py       # shared haversine
│   ├── pipeline.py  # walkie run: the integration chain (cron entry)
│   ├── ai/          # planning prompt + decision engine (plan.json)
│   ├── routing/     # OSM extract -> street graph -> closed loop -> walk.gpx
│   ├── media/       # GPX turn narration (Piper TTS, voice-only mp3)
│   ├── suggest/     # prompts / proposals / reminders
│   ├── sync/        # quote notifications (plyer) + LAN server for the phone
│   ├── ui/          # setup wizard + quick-adjust dialog (PyQt6)
│   ├── region.py    # Geofabrik OSM extract fetch
│   └── log.py, clock.py, __main__.py
├── tests/           # unit/ (pytest, incl. offscreen Qt smoke tests)
├── output/          # generated at runtime (gitignored)
├── docs/            # build_logic.md, test_protocol.md
├── TEST_LOG.md      # field-testing log (fill during walks, Step 9)
└── scripts/         # setup_env.sh
```

## Quickstart

```bash
make setup        # venv + deps + Ollama model + region fetch
make region       # re-detect location / fetch OSM extract
make wizard       # one-time preference setup (PyQt)
make suggest      # today's walk proposal (weather + local LLM)
make plan         # AI decision engine -> output/plans/plan.json
make route        # offline walking loop -> output/routes/walk.gpx (OsmAnd)
make voice        # narrate route turns -> output/audio/walk_audio.mp3
make daemon       # reminders until today's walk is approved
make run          # full pipeline: suggest -> plan -> remind -> route -> voice
make serve        # phone downloads today's files over local WiFi
make test         # pytest
make lint         # ruff
make typecheck    # mypy
```

Every `make` target is just `python -m walkie <command>`; after
`pip install -e .` the `walkie` console script works too:

```bash
walkie suggest --edit   # quick-adjust today's walk
walkie route            # rebuild today's loop (--minutes N, --refresh)
walkie voice            # voice cues for output/routes/walk.gpx (own music: your player)
walkie remind           # fire due reminders once (cron-friendly)
walkie run              # the whole pipeline --force regenerates everything
walkie serve            # LAN server: phone gets plan + gpx + mp3 (--port N)
```

Schedule it with cron (cheap: fresh outputs are skipped, stale ones rebuilt):

```bash
* * * * * cd /path/to/walkie && .venv/bin/walkie run >> output/cron.log 2>&1
```
