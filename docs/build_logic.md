# Build Logic

Pipeline order (each stage reads only config/, data/, and prior stage output/):

1. `walkie region` (one-time) — location detect + Geofabrik extract -> `config/settings.yaml`, `data/osm/*.pbf`
2. `walkie wizard` (one-time) — PyQt wizard -> `config/user_plan.json` + quote
3. `walkie suggest` — weather cache (auto-refresh when stale) + Ollama one-shot
   proposal -> `output/proposal.json`; quick edit via `walkie suggest --edit`,
   reminders at T-30/T-15/T-5 (`walkie remind` once, `walkie daemon` to loop)
   -> `output/today_plan.json` (auto-approves at walk time if nobody edits)
4. AI decision engine — Ollama scores prefs + conditions -> `output/plans/plan.json`
5. Route builder + GPX export -> `output/routes/walk.gpx`
6. Playlist matcher + voice cues -> `output/audio/playlist.json`, `walk_final.mp3`
7. Sync — OS notification + local file drop to phone

Entry points: `make wizard|region|suggest|remind|daemon` — all of them run
`python -m walkie <cmd>` (or the `walkie` console script after `pip install -e .`).

Code layout (`src/walkie/`):

- `cli.py` — the only module that parses argv and exits
- `config.py` — path constants + validated settings (loud `ConfigError`)
- `models.py` — `UserPlan` / `Weather` / `Proposal` / `TodayPlan` dataclasses
- `storage.py` — atomic JSON read/write
- `log.py`, `clock.py` — stderr logging, local wall-clock
- `llm.py` — the single Ollama client
- `weather.py` — Open-Meteo fetch, staleness cache, prompt fingerprint
- `suggest/` — prompts, proposals, reminders
- `ui/` — setup wizard, quick-adjust dialog, shared widgets
- `region.py` — Geofabrik extract detection + download

Rules:
- Config changes never require code edits (config/user_plan.json, config/settings.yaml, config/quotes.txt).
- Inputs (`data/`) are never written to; outputs (`output/`) are always regenerable.
- Every module is importable standalone for unit tests; Qt is imported only inside UI paths.
- Defaults live in code, overrides live in config; invalid config fails loudly (never silently to null island).
