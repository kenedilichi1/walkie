# Test Protocol

Per-step tests are run before moving to the next step.

| Step | Command | Pass criteria |
|------|---------|---------------|
| 1 | `ollama run llama3.2 "hello"` | responds with no internet |
| 2 | `make wizard` | `config/user_plan.json` written; quote shown |
| 3 | `walkie suggest` (twice, then edit the weather cache) | proposal reuses while valid; updates when weather changes; `walkie suggest --edit` writes `output/today_plan.json`; reminders fire at T-30/15/5, auto-approve at walk time |
| 4 | `walkie plan` x5; edit prefs; rerun | consistent pick; clean JSON in `output/plans/plan.json` (daylight + weather embedded); `--force-new` regenerates; fallback plan when Ollama is stopped |
| 5 | load output/routes/walk.gpx in OsmAnd | loop closes; time ≈ planned duration |
| 6 | play playlist | duration covers walk + buffer |
| 7 | play walk_final.mp3 | cues match GPX turns |
| 8 | open laptop IP on phone | files download; GPX shows offline |
| 9 | `walkie suggest && walkie remind` | all outputs, no errors |
| 10 | field walk | see TEST_LOG.md |

Unit tests: `make test` · Lint: `make lint` · Types: `make typecheck`
