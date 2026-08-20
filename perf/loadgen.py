#!/usr/bin/env python
"""Open-loop load generator for the redirect path (T098).

Purpose-built because no load tool is installed on this machine. Three properties matter and
are easy to get wrong:

* **Redirects are not followed.** The endpoint returns 302 by design; following it would
  measure example.com rather than this service.
* **Open loop.** Requests are scheduled at a fixed rate rather than issued as fast as
  responses arrive, so a slow service produces a queue instead of silently lowering the
  offered load — closed-loop tools hide exactly the degradation we are looking for.
* **Generator lag is measured separately.** The gap between a request's scheduled send time
  and its actual send is reported as `scheduler_lag`, so client overhead is never mistaken
  for service latency.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from dataclasses import dataclass, field


@dataclass
class Sample:
    status: int
    latency_ms: float
    lag_ms: float


@dataclass
class Result:
    profile: str
    target_rps: float
    duration_s: float
    samples: list[Sample] = field(default_factory=list)

    def summary(self) -> dict:
        latencies = sorted(s.latency_ms for s in self.samples)
        lags = sorted(s.lag_ms for s in self.samples)
        redirects = sum(1 for s in self.samples if s.status == 302)
        errors = sum(1 for s in self.samples if s.status != 302)

        def pct(values: list[float], p: float) -> float | None:
            if not values:
                return None
            index = min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))
            return round(values[index], 2)

        return {
            "profile": self.profile,
            "target_rps": self.target_rps,
            "duration_s": round(self.duration_s, 2),
            "total_requests": len(self.samples),
            "successful_redirects": redirects,
            "errors": errors,
            "error_rate": round(errors / len(self.samples), 6) if self.samples else None,
            "throughput_rps": round(len(self.samples) / self.duration_s, 2) if self.duration_s else None,
            "latency_ms": {
                "p50": pct(latencies, 50), "p95": pct(latencies, 95),
                "p99": pct(latencies, 99), "max": round(max(latencies), 2) if latencies else None,
                "mean": round(statistics.fmean(latencies), 2) if latencies else None,
            },
            "scheduler_lag_ms": {
                "p50": pct(lags, 50), "p95": pct(lags, 95),
                "max": round(max(lags), 2) if lags else None,
            },
            "status_counts": _counts(self.samples),
        }


def _counts(samples: list[Sample]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sample in samples:
        counts[str(sample.status)] = counts.get(str(sample.status), 0) + 1
    return dict(sorted(counts.items()))


def pick_code(codes: list[str], hot: list[str], hot_share: float, rng: random.Random) -> str:
    if hot and rng.random() < hot_share:
        return rng.choice(hot)
    return rng.choice(codes)


async def run(base_url: str, codes: list[str], *, profile: str, rate: float, duration: float,
              hot_share: float, hot_size: int, seed: int, concurrency: int) -> Result:
    import httpx

    rng = random.Random(seed)
    hot = codes[:hot_size] if hot_share > 0 else []
    result = Result(profile=profile, target_rps=rate, duration_s=duration)
    queue: asyncio.Queue = asyncio.Queue()

    # follow_redirects=False is the point: we measure our 302, not the destination.
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=base_url, follow_redirects=False, limits=limits,
                                 timeout=30.0) as client:

        async def worker() -> None:
            while True:
                item = await queue.get()
                if item is None:
                    queue.task_done()
                    return
                scheduled, code = item
                sent = time.perf_counter()
                try:
                    response = await client.get(f"/{code}")
                    status = response.status_code
                except Exception:
                    status = 0
                finished = time.perf_counter()
                result.samples.append(Sample(
                    status=status,
                    latency_ms=(finished - sent) * 1000,
                    lag_ms=max(0.0, (sent - scheduled) * 1000),
                ))
                queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(concurrency)]

        start = time.perf_counter()
        interval = 1.0 / rate
        index = 0
        while True:
            scheduled = start + index * interval
            now = time.perf_counter()
            if scheduled - start >= duration:
                break
            if scheduled > now:
                await asyncio.sleep(scheduled - now)
            await queue.put((scheduled, pick_code(codes, hot, hot_share, rng)))
            index += 1

        await queue.join()
        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers)
        result.duration_s = time.perf_counter() - start

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--codes", default="perf/results/codes.txt")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--rate", type=float, default=100.0)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--hot-share", type=float, default=0.0)
    parser.add_argument("--hot-size", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with open(args.codes, encoding="utf-8") as handle:
        codes = [line.strip() for line in handle if line.strip()]

    result = asyncio.run(run(
        args.base_url, codes, profile=args.profile, rate=args.rate, duration=args.duration,
        hot_share=args.hot_share, hot_size=args.hot_size, seed=args.seed,
        concurrency=args.concurrency,
    ))
    summary = result.summary()
    summary["hot_share"] = args.hot_share
    summary["hot_size"] = args.hot_size if args.hot_share else 0
    summary["corpus_size"] = len(codes)

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
