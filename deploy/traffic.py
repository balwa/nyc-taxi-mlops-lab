#!/usr/bin/env python3
"""Steady rider traffic for a canary (S8, given): POST /predict through Traefik at a fixed rate, with
trips drawn from busy zone pairs at random hours and days. Standard library only; runs on the app host.

  deploy/traffic.py [SECONDS] [RATE_PER_SECOND] [URL]      (defaults: 1800, 5, http://localhost)

Prints a one-line summary at the end (or when stopped): requests by status and by who answered.
"""

import collections
import json
import random
import signal
import sys
import time
import urllib.error
import urllib.request

PAIRS = [(132, 230), (138, 161), (161, 237), (237, 236), (236, 237), (162, 170), (230, 161), (48, 68), (142, 239), (79, 107),
         (186, 170), (132, 48), (138, 230), (234, 79), (68, 246), (163, 140), (13, 231), (239, 142), (170, 162), (100, 186)]
seconds, rate = float(sys.argv[1]) if len(sys.argv) > 1 else 1800, float(sys.argv[2]) if len(sys.argv) > 2 else 5
url = (sys.argv[3] if len(sys.argv) > 3 else "http://localhost").rstrip("/") + "/predict"
status, answered = collections.Counter(), collections.Counter()


def summary(*_):
    print(json.dumps({"requests": sum(status.values()), "status": dict(status), "answered_by": dict(answered)}), flush=True)
    sys.exit(0)


signal.signal(signal.SIGTERM, summary)
signal.signal(signal.SIGINT, summary)
rng, t0, n = random.Random(), time.time(), 0
while time.time() - t0 < seconds:
    p, d = rng.choice(PAIRS)
    body = {"pickup_zone_id": p, "dropoff_zone_id": d,
            "pickup_datetime": f"2024-03-{rng.randint(4, 10):02d}T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00"}
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            m = json.load(r).get("model") or {}
            status[r.status] += 1
            answered[f"{m.get('alias') or m.get('name')} v{m.get('version')}"] += 1
    except urllib.error.HTTPError as e:
        status[e.code] += 1
    except OSError as e:
        status[type(e).__name__] += 1
    n += 1
    time.sleep(max(0.0, t0 + n / rate - time.time()))
summary()
