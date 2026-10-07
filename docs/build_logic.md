# Build Logic

Pipeline order (each stage reads only config/, data/, and prior stage output/):

1. `calendar/reader.py` — parse `data/calendar/*.ics` -> `output/gaps.json`
2. `weather/fetcher.py` + `weather/daylight.py` -> `cache/weather_today.json`, `output/daylight_weather.json`
3. `ai/planner.py` — Ollama scores gaps + prefs -> `output/plans/plan.json`
4. `routing/builder.py` + `routing/export.py` -> `output/routes/walk.gpx`
5. `media/matcher.py` + `media/voice.py` -> `output/audio/playlist.json`, `walk_final.mp3`
6. `sync/notify.py` + `sync/server.py` — OS notification + local file drop

Rules:
- Config changes never require code edits (config/prefs.json, config/settings.yaml).
- Inputs (`data/`) are never written to; outputs (`output/`) are always regenerable.
- Every module is importable standalone for unit tests.
