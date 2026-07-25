# Field note: four regression alerts, zero regressions

*24 July 2026 — model-drift*

> The numbers below are from the runs of 20–24 July 2026 and are reproducible from
> `dashboard/metrics.json` at the commits of those dates. Later runs will move them;
> the arithmetic won't.

This board probes 16 LLMs on a frozen 35-task suite, once a day, and keeps every score. When a model drops against its previous run, it opens a GitHub issue by itself and writes a draft post.

Between 21 and 24 July it did that four times:

```
23 Jul  Gemini 3.5 Flash   -11.4 pts
24 Jul  Gemini 3.1 Pro      -2.9 pts
21 Jul  Grok 4.3            -5.7 pts
22 Jul  Llama 3.3 70B       -2.9 pts
```

Four regressions in four days, across three labs. None of them was a model getting worse.

## Two weren't the model

Every point carries a second number beside accuracy: **reliability**, the share of probe calls that came back at all.

```
gemini-3.5-flash  22 Jul  acc 1.000  reliability 1.000
                  23 Jul  acc 0.886  reliability 0.914   <- "-11.4 pts"

gemini-3.1-pro    22 Jul  acc 0.914  reliability 0.943
                  23 Jul  acc 0.886  reliability 0.914   <- "-2.9 pts"
                  24 Jul  acc 0.971  reliability 1.000   <- next clean run
```

Accuracy and reliability fell together — the signature of calls that never returned, not answers that got worse. A failed call has no answer to grade, and an ungraded task scores like a wrong one.

This board already published that lesson on 20 July, when Groq's 30 RPM cap took Llama 3.3 70B to 3% and it looked exactly like drift (see `notes.json`, "The drift that was a rate limit"). Gemini 3.1 Pro settles its own case: the next clean run came back at **97.1%**, higher than before the "regression."

## Two were one question

The other two held reliability at 1.000 throughout, so the numbers are real:

```
grok-4.3        0.800 -> 0.743   = -5.7 pts
llama-3.3-70b   0.800 -> 0.771   = -2.9 pts
```

The suite is 35 tasks. One task is `100/35 = 2.86` points.

So **−2.9 is one question changing its answer**, −5.7 is two, and −11.4 is four. Every alert this week was an integer number of questions — the tell that the instrument, not the models, set the scale. A 35-task suite cannot resolve anything finer than about three points.

## Why the alerting stays loud

The obvious fix — only fire above 10 points — is wrong. A tracker that only fires on catastrophes misses real drift, and the −11.4 that turned out to be failed calls is exactly the shape of a true regression. Sensitivity is the feature.

It is only safe because nothing downstream publishes automatically. The stub the probe writes says so in its own text:

> Auto-logged when the scheduled probe flagged a run-over-run regression. Before this becomes a post, check the run log and the Reliability metric — a rate limit or provider outage can look exactly like a regression.

The automation notices. A human checks. This week: four notices, zero posts.

## The number worth tracking

If you build evals you already track your models' scores. The metric more people should publish is **the share of their own alerts that survive checking.**

Mine this week was zero. That's the most useful number I have — it says the suite is too small to resolve single-task noise, and that reliability has to sit beside accuracy on every chart or the chart lies. Both are fixable; neither would have been visible if I'd shipped the post the tracker wrote.

The hard part of a drift tracker isn't detecting drift. It's not manufacturing it.

---

- **Board:** <https://egnaro9.github.io/model-drift/>
- **Suite:** `modeldrift/suite.py` — 35 frozen tasks, deterministic graders, no LLM-as-judge
- **Alert logic:** `modeldrift/report.py`
