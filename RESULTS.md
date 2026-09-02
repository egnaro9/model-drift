# Latest standings — suite `2026-07-v3`

_Auto-generated after each scheduled probe. Live chart: [egnaro9.github.io/model-drift](https://egnaro9.github.io/model-drift/)._

**Min detectable** is the smallest movement a run could show: `100 / graded calls`. Accuracy is scored over graded calls only — a truncated call leaves the denominator rather than counting as wrong — so the floor is not a constant, and a delta beneath it is the denominator moving, not the model.

**Reliability floor** is 0.5: accuracy from runs below it is not scored, because a rate limit or outage makes a call absent rather than wrong. The disqualified run stays visible as a reliability event.

| Model | Accuracy | Δ vs previous | Min detectable | Status |
| --- | --- | --- | --- | --- |
| Mock (stable) | 100.0% | +0.0 pts | ±2.9 | ⚪ unchanged |
| GPT-5 | 100.0% | +0.0 pts | ±2.9 | ⚪ unchanged |
| GPT-5 mini | 100.0% | +0.0 pts | ±2.9 | ⚪ unchanged |
| GPT-4o mini | 80.0% | +0.0 pts | ±2.9 | ⚪ unchanged |
| GPT-5 nano | 100.0% | +0.0 pts | ±2.9 | ⚪ unchanged |
| Claude Fable 5 | 97.1% | +2.9 pts | ±2.9 ⚠ below floor | 🟢 improved |
| Claude Opus 4.8 | 91.4% | +0.0 pts | ±2.9 | ⚪ unchanged |
| Claude Sonnet 5 | 82.9% | -5.7 pts | ±2.9 | 🔴 regressed |
| Claude Haiku 4.5 | 85.7% | +0.0 pts | ±2.9 | ⚪ unchanged |
| Gemini 3.1 Pro | 77.1% | -17.2 pts | — | 🔴 regressed |
| Gemini 3.5 Flash | 97.1% | +0.0 pts | — | ⚪ unchanged |
| Gemini 3.1 Flash-Lite | 85.7% | -8.6 pts | — | 🔴 regressed |
| Grok 4.5 | 97.1% | +0.0 pts | ±2.9 | ⚪ unchanged |
| Grok 4.3 | 97.1% | +5.7 pts | ±2.9 | 🟢 improved |
| Grok 4 Fast | 97.1% | +5.7 pts | ±2.9 | 🟢 improved |
| Llama 3.3 70B | 77.1% | -2.9 pts | ±2.9 | 🔴 regressed |
| Llama 3.1 8B | 57.1% | +0.0 pts | ±2.9 | ⚪ unchanged |
