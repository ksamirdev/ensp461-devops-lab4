"""Availability probe: sends steady requests for a fixed time and reports what each second looked like.

Runs inside the cluster (stdlib only), so it reaches Services exactly like another pod would:
  kubectl run probe --rm -i --restart=Never --image=mirror.gcr.io/library/python:3.13-slim -- \
      python -c "$(cat lab/probe.py)" URL SECONDS [get|post] [WORKERS]
GET reads the "color"/"release" field of the JSON reply; POST sends a /stats request and counts writes.
"""
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict

url, seconds = sys.argv[1], float(sys.argv[2])
mode = sys.argv[3] if len(sys.argv) > 3 else "get"
workers = int(sys.argv[4]) if len(sys.argv) > 4 else 8

start = time.time()
per_second = defaultdict(Counter)  # second -> Counter of outcomes
failures = []  # timestamps of failed requests
lock = threading.Lock()


def one_request():
    body = json.dumps({"text": "probe request"}).encode() if mode == "post" else None
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
            if mode == "post":
                return "write-ok"
            return data.get("color") or data.get("release") or "ok"
    except urllib.error.HTTPError as exc:
        return f"http-{exc.code}"
    except Exception as exc:  # connection refused, timeout, reset: all count as failures
        return f"error-{type(exc).__name__}"


def worker():
    while (now := time.time()) - start < seconds:
        outcome = one_request()
        second = int(now - start)
        with lock:
            per_second[second][outcome] += 1
            if outcome.startswith(("http-5", "error-")):
                failures.append(now - start)
        time.sleep(0.02)


threads = [threading.Thread(target=worker) for _ in range(workers)]
for t in threads:
    t.start()
for t in threads:
    t.join()

totals = Counter()
print("second  outcomes")
for second in sorted(per_second):
    totals.update(per_second[second])
    print(f"{second:>6}  " + "  ".join(f"{k}={v}" for k, v in sorted(per_second[second].items())))
total = sum(totals.values())
failed = len(failures)
print(f"\ntotal={total} failed={failed} success_rate={100 * (total - failed) / total:.2f}%")
print("outcomes: " + ", ".join(f"{k}={v}" for k, v in sorted(totals.items())))
if failures:
    print(f"first_failure_at={min(failures):.2f}s last_failure_at={max(failures):.2f}s "
          f"failure_window={max(failures) - min(failures):.2f}s")
