# Drift evidence — 2026-10-08

The input the user set, and what `make run` produced that evening. Archived
before the next run overwrote `output/`. This is the "before" sample for the
`fix/single-decision-plan` branch and the side-by-side in the DEV post.

| File | What it is | Time | Length |
| --- | --- | --- | --- |
| `user_plan.json` | what the user asked for | 21:30 | 30 min |
| `proposal.json` | first model call's answer | 18:30 | 60 min |
| `plan.json` | second model call's answer | 18:00–19:30 | 90 min |

What went wrong, in three lines:

1. Neither call was checked against the user's numbers — the validators only
   enforce the global 06:00–21:00 / 5–180 min window, so a 3-hour shift and a
   tripled duration passed as valid.
2. Two independent calls compounded the drift: the plan call reads the
   proposal's values, so 21:30/30 was already gone by the second prompt.
3. 21:30 is outside the reply window anyway (latest legal start 21:00), so
   even an obedient model echoing it would have been rejected — while the
   input side accepted it without complaint.

Also visible here: `plan.json` records `sunset: 18:15` for a walk that ends
19:30 — the daylight rule was prompt text only.
