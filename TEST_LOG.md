# TEST_LOG — field testing (Step 9)

Fill this in during and after each field walk. `docs/test_protocol.md` row 10
signs off from section E. Commands assume the project venv
(`.venv/bin/walkie …` or the `make` alias).

Before/after evidence: `docs/evidence/2026-10-08-drift/` holds the archived
input → proposal → plan from the run where the user's 21:30 / 30 min became
18:00–19:30 / 90 min. The `after/` subfolder replays that same input and the
same drifted model replies after the validators landed — the replies are now
rejected and the walk stays at 21:30 / 30 min.

## A. Pre-walk checklist (home, online)

- [ ] `make run` — proposal + plan + route + voice built, exit 0
- [ ] Weather cache warmed while online (`walkie suggest` after leaving home
      network for a while — the cache at `cache/weather_today.json` is what
      the trailhead falls back to)
- [ ] OsmAnd: area map downloaded for offline use
- [ ] `walkie serve` → phone downloads `routes/walk.gpx` (+ `audio/walk_audio.mp3`)
- [ ] Voice cues play locally (`afplay output/audio/walk_audio.mp3` or your player)
- [ ] Notification permission granted for the terminal/walkie app
- [ ] Optional cron installed:
      `* * * * * cd <repo> && .venv/bin/walkie run >> output/cron.log 2>&1`

## B. Trailhead — airplane-mode check (no internet)

Airplane mode ON (or Wi-Fi + cellular off), then:

| Command / action | Expected | Actual / notes |
| --- | --- | --- |
| `walkie suggest` | exit 0; reuses today's proposal (stale cache wins, no crash) | |
| `walkie run` | exit 0; route/voice up-to-date (or rebuilt); weather may read "unavailable (offline)" | |
| Notification (if due) | banner appears with a quote from `config/quotes.txt` | |
| OsmAnd opens `walk.gpx` | route renders with no signal | |
| Play `walk_audio.mp3` | cues audible, no network used | |

Automated proof of this section: `test_airplane_mode_full_chain_completes`
(weather fetch + Ollama both fail → full chain still builds).

Airplane mode OFF again when done.

## C. Walk log

| Date | Loop / route | Duration | Screen time (min) | Cues matched turns? | Issues | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| | | | target < 2 | | | |

Screen time: iOS Screen Time / Android Digital Wellbeing over the walk window
(or stopwatch per unlock). Target: unlock once at the trailhead, then audio
cues only — the walk itself should need no screen.

## D. Refinements (edit any time)

Record what changed and why; the files are read at runtime, no restart needed.

| Date | File | Change | Why |
| --- | --- | --- | --- |
| | `config/user_plan.json` | e.g. preferred_time 16:30 → 17:00 | afternoons too hot |
| | `config/quotes.txt` | added/removed a line | stale motivator |

## E. Sign-off

- [ ] Section B green offline (checked at the trailhead)
- [ ] ≥ 1 walk logged in C with screen time recorded
- [ ] Preferences reviewed in D (or "no change" noted)
- [ ] `docs/test_protocol.md` row 10: pass — date: __________
