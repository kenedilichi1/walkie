# walkie

Offline-first walk planner. Reads your calendar, checks local weather/daylight,
picks the best 30–60 min gap with a local LLM (Ollama), builds a circular
walking loop from an offline OSM extract, matches a playlist, generates voice
cues, and drops everything to your phone over local WiFi. No cloud required
after setup.

## Layout

```
walkie/
├── config/          # prefs.json (rules) + settings.yaml (region, paths)
├── data/            # inputs: .ics, music/, .pbf extracts
├── src/             # all code (installable via src/ layout)
│   ├── cli.py       # entry point / daemon command
│   ├── main.py      # pipeline orchestrator
│   ├── calendar/    # .ics ingestion + gap finding
│   ├── weather/     # Open-Meteo fetch + astral daylight
│   ├── ai/          # Ollama prompt, client, planner
│   ├── routing/     # OSMnx loop builder + GPX export
│   ├── media/       # BPM/mood playlist + Piper TTS
│   └── sync/        # OS notification + local HTTP server
├── tests/           # unit/ + integration/ (pytest)
├── output/          # generated at runtime (gitignored)
├── docs/            # build_logic.md, test_protocol.md
└── scripts/         # setup_env.sh
```

## Quickstart

```bash
make setup        # or: scripts/setup_env.sh
make test
python -m main     # run the full pipeline
```
