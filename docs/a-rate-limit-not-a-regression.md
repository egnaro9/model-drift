# Field note: the drift that was a rate limit

*2026-07-21*

On 2026-07-20 the board showed **Llama 3.3 70B drop from 69% to 3%, and Llama 3.1 8B to 0%** — overnight, on a frozen suite. That is a regression post. *"Meta's models fell off a cliff this week"* writes itself.

It wasn't drift. I pulled the run log instead of the screenshot:

```
api.groq.com -> 429: Rate limit reached for model `llama-3.3-70b-versatile`
service tier `on_demand` ... requests per minute (RPM): Limit 30, Used 30
```

**34 of 35 calls, both Llama models, rate-limited.** They run on Groq's free tier — 30 RPM shared across the whole org — and probing two models back-to-back spent the budget. Every 429'd call scored as a wrong answer, so accuracy cratered toward zero. (Google threw a few 503s and xAI a 429 too — same category.)

The model didn't get dumber. A rate limit scored as a 0%, and a rate limit scoring as a 0% is the single most misleading thing a drift tracker can do — it looks *exactly* like the thing it exists to catch.

The board got the important half right: it already tracks **reliability** (the share of calls that succeeded) as its own metric and excludes low-reliability probes from the auto-generated summary, so the written paragraph never claimed a regression. But the raw accuracy chart still dove toward 0, and there was no retry to recover a transient 429.

**What changed** ([PR #2](https://github.com/egnaro9/model-drift/pull/2)):

- Retry 429/5xx honoring `Retry-After` (Groq's 429 says "try again in 2s"); deterministic 4xx are never retried.
- Throttle per host to the provider's rate cap (Groq = 30 RPM), state shared across models on the same org.
- The dashboard drops points below a reliability floor from the accuracy and per-capability lines — a rate limit can no longer render as a regression. Reliability keeps them, because reliability genuinely dropped.
- Fixed a silent failure: a missing `drift` label under `|| true` meant a real regression opened no alert issue at all.

The hard part of an eval board isn't detecting drift. It's not manufacturing it. The most valuable thing the board did that week was stop a post from going out.
