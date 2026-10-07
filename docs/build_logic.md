# Build Logic

Pipeline order (each stage reads only config/, data/, and prior stage output/):

1. `walkie region` (one-time) — location detect + Geofabrik extract -> `config/settings.yaml`, `data/osm/*.pbf`
2. `walkie wizard` (one-time) — PyQt wizard -> `config/user_plan.json` + quote
3. `walkie suggest` — weather cache (auto-refresh when stale) + Ollama one-shot
   proposal -> `output/proposal.json`; quick edit via `walkie suggest --edit`,
   reminders at T-30/T-15/T-5 (`walkie remind` once, `walkie daemon` to loop)
   -> `output/today_plan.json` (auto-approves at walk time if nobody edits)
4. `walkie plan` — AI decision engine: structured inputs (today's proposal,
   weather, daylight) -> one local LLM call -> validated
   `output/plans/plan.json` (falls back to the inputs when the model is
   unreachable or replies garbage)
5. `walkie route` — offline loop builder: one scan of the local .pbf
   (street graph cached in `cache/routes/`) -> closed start-and-back-to-start
   loop sized to today's duration -> `output/routes/walk.gpx` (timestamps
   paced to fit the walk window; load it in OsmAnd)
6. `walkie voice` — read `output/routes/walk.gpx`, narrate the turns with
   local Piper TTS -> `output/audio/walk_audio.mp3` (spoken cues only — no
   playlist matching; play your own music alongside it)
7. Reminders + phone sync — each reminder notification carries a random
   quote from `config/quotes.txt`; `walkie serve` puts `output/` on the LAN
   (landing page at `/` lists today_plan.json + walk.gpx + walk_audio.mp3)
   so the phone downloads the files and imports the GPX into OsmAnd
8. `walkie run` — integration pipeline (cron entry point): steps 3+4 always,
   reminders (7) next, then — only once `output/today_plan.json` exists —
   route + voice (5-6), rebuilding only stale outputs (`--force` resets all).
   Cron: `* * * * * cd <repo> && .venv/bin/walkie run >> output/cron.log 2>&1`

Entry points: `make wizard|region|suggest|plan|route|voice|remind|daemon|run|serve`
— all of them run `python -m walkie <cmd>` (or the `walkie` console script
after `pip install -e .`).

Code layout (`src/walkie/`):

- `cli.py` — the only module that parses argv and exits
- `config.py` — path constants + validated settings (loud `ConfigError`)
- `models.py` — `UserPlan` / `Weather` / `Proposal` / `TodayPlan` dataclasses
- `storage.py` — atomic JSON read/write
- `log.py`, `clock.py`, `geo.py` — stderr logging, local wall-clock, haversine
- `llm.py` — the single Ollama client (system + user messages)
- `weather.py` — Open-Meteo fetch, staleness cache, prompt fingerprint
- `daylight.py` — sunrise/sunset/day length (astral, offline)
- `ai/` — planning system prompt + decision engine (plan.json)
- `routing/` — OSM extract -> OSMnx street graph -> closed loop -> walk.gpx
- `media/` — GPX turn narration (Piper TTS, voice-only MP3)
- `sync/` — desktop notification bridge (plyer + quote) and the LAN server
- `pipeline.py` — `walkie run`: chains suggest -> plan -> remind -> route -> voice
- `suggest/` — prompts, proposals, reminders
- `ui/` — setup wizard, quick-adjust dialog, shared widgets
- `region.py` — Geofabrik extract detection + download

Rules:
- Config changes never require code edits (config/user_plan.json, config/settings.yaml, config/quotes.txt).
- Inputs (`data/`) are never written to; outputs (`output/`) are always regenerable.
- Every module is importable standalone for unit tests; Qt is imported only inside UI paths.
- Defaults live in code, overrides live in config; invalid config fails loudly (never silently to null island).
