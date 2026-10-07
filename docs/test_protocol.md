# Test Protocol

Per-step tests are run before moving to the next step.

| Step | Command | Pass criteria |
|------|---------|---------------|
| 1 | `ollama run llama3.2 "hello"` | responds with no internet |
| 2 | `make wizard` | `config/user_plan.json` written; quote shown |
| 3 | `walkie suggest` (twice, then edit the weather cache) | proposal reuses while valid; updates when weather changes; `walkie suggest --edit` writes `output/today_plan.json`; reminders fire at T-30/15/5, auto-approve at walk time |
| 4 | `walkie plan` x5; edit prefs; rerun | consistent pick; clean JSON in `output/plans/plan.json` (daylight + weather embedded); `--force-new` regenerates; fallback plan when Ollama is stopped |
| 5 | `walkie route` (fixture grid in tests; real extract when present) then load `output/routes/walk.gpx` in OsmAnd | loop closes (first == last point); timestamp span == planned duration (fits the window: today_plan -> plan -> user_plan fallback); loop length ≈ target (±10%); map sanity: follows streets, no jumps; `--refresh` re-scans, repeat runs hit the cache |
| 6 | `walkie voice --gpx tests/fixtures/square_loop.gpx` (and `walkie voice` once step 5's walk.gpx exists) | mp3 playback covers loop time (5:01 ≥ 300 s, ffmpeg probe); instructions match GPX turns (3× "Turn right" at the square's corners); file contains voice cues only — user plays their own songs separately |
| 7 | `walkie remind` while a proposal is due (or `walkie daemon`), then `walkie serve` | notification fires carrying a random quote from `config/quotes.txt` + the proposal detail; server prints `http://<laptop-ip>:8000/` and the 3 file URLs; missing files flagged `[missing]` |
| 8 | open the printed laptop URL on the phone (same Wi-Fi) | landing page lists today_plan.json + walk.gpx + walk_audio.mp3 with sizes; all download; GPX imports into OsmAnd and renders offline |
| 9 | `walkie run`, run it twice, then `walkie run --force` | end-to-end: proposal + plan written; once approved also walk.gpx (closes, spans the window) + walk_audio.mp3; second run reports route/voice up-to-date (no rebuild); `--force` rebuilds; before approval: quote notification fires when due, route/voice deferred; missing pbf when approved -> exit 1 with "make region" |
| 10 | field walk (airplane-mode check at the trailhead) | see `TEST_LOG.md`: section B green offline, ≥1 walk logged with screen time (< 2 min target), refinements to `user_plan.json`/`quotes.txt` recorded |

Unit tests: `make test` · Lint: `make lint` · Types: `make typecheck`
