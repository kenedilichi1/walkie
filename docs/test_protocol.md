# Test Protocol

Per-step tests are run before moving to the next step.

| Step | Command | Pass criteria |
|------|---------|---------------|
| 1 | `ollama run llama3.2 "hello"` | responds with no internet |
| 2 | `python -m calendar.reader` | gaps.json matches today's calendar |
| 3 | `python -m weather.fetcher` | cache matches real weather/sun |
| 4 | run planner 5x; edit prefs; rerun | consistent pick; prefs change output |
| 5 | load output/routes/walk.gpx in OsmAnd | loop closes; time ≈ gap |
| 6 | play playlist | duration covers gap + buffer |
| 7 | play walk_final.mp3 | cues match GPX turns |
| 8 | open laptop IP on phone | files download; GPX shows offline |
| 9 | `python -m walkie` | all outputs, no errors |
| 10 | field walk | see TEST_LOG.md |

Unit tests: `make test`
