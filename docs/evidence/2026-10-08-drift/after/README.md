# After — the same input, post-fix (2026-10-09)

The `../` files are the original drift: the user asked for 21:30 / 30 min and
`make run` produced 18:00–19:30 / 90 min. These `after/` files replay that
exact scenario — same `user_plan.json` (21:30 / 30 min), same drifted model
replies (`18:30` / `60` for the proposal, `18:00` / `90` for the plan) — after
`fix/single-decision-plan` and `fix/validator-enforces-rules` landed.

The model replies are now rejected as outside the window around the user's own
choice, so the walk falls back to what the user asked for:

| File | Before (drift) | After (fixed) |
| --- | --- | --- |
| `proposal.json` | 18:30 / 60 min | 21:30 / 30 min |
| `plan.json` | 18:00–19:30 / 90 min | 21:30–22:00 / 30 min |

Both records carry `source: fallback` / the fallback reason, because the only
reply on offer was the old drifted one. Regenerate with any real model and the
plan can still nudge the time — but only inside the allowed window, never the
3-hour shift and tripled duration from the original run.
