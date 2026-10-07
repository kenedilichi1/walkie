# Build Logic

Pipeline order (each stage reads only config/, data/, and prior stage output/):

1. `setup_gui.py` (one-time) — PyQt wizard -> `config/user_plan.json` + quote
2. `weather/fetcher.py` — Open-Meteo -> `cache/weather_today.json` (auto-refresh when stale)
3. `suggest.py` — Ollama one-shot proposal -> `output/proposal.json`;
   quick edit via `--edit` or reminders at T-30/T-15/T-5 -> `output/today_plan.json`
   (auto-approves at walk time if nobody edits)
4. `ai/planner.py` — Ollama scores prefs + conditions -> `output/plans/plan.json`
5. `routing/builder.py` + `routing/export.py` -> `output/routes/walk.gpx`
6. `media/matcher.py` + `media/voice.py` -> `output/audio/playlist.json`, `walk_final.mp3`
7. `sync/notify.py` + `sync/server.py` — OS notification + local file drop

Entry points: `make wizard`, `make region`, `python suggest.py [--edit|--daemon]`.

Rules:
- Config changes never require code edits (config/prefs.json, config/settings.yaml).
- Inputs (`data/`) are never written to; outputs (`output/`) are always regenerable.
- Every module is importable standalone for unit tests.
