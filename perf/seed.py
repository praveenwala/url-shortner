#!/usr/bin/env python
"""Seed the shortener corpus for the load baseline (T098).

Writes links directly with COPY rather than through the API: the API path is what we are
measuring, and creating 100k links through it would take longer than the benchmark and would
pollute the counters we then read.

    python perf/seed.py --dsn postgresql://... --count 100000
"""

from __future__ import annotations

import argparse
import io
import string
import sys
from datetime import UTC, datetime

ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits  # 62 symbols
CODE_LENGTH = 7


def code_for(index: int) -> str:
    """Deterministic base-62 encoding of the row index.

    Deterministic rather than random so the corpus is reproducible and uniqueness is
    guaranteed without a retry loop — the benchmark is not testing collision handling.
    """
    value, digits = index, []
    for _ in range(CODE_LENGTH):
        value, remainder = divmod(value, len(ALPHABET))
        digits.append(ALPHABET[remainder])
    return "".join(reversed(digits))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--count", type=int, default=100_000)
    parser.add_argument("--codes-out", default="perf/results/codes.txt")
    args = parser.parse_args()

    import psycopg

    now = datetime.now(UTC).isoformat()
    buffer = io.StringIO()
    codes = []
    for index in range(args.count):
        code = code_for(index)
        codes.append(code)
        destination = f"https://example.com/target/{index}"
        buffer.write(f"{code}\t{destination}\t{destination}\tperf-client\t{now}\t\\N\t\\N\t0\t\\N\t\\N\n")
    buffer.seek(0)

    with psycopg.connect(args.dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE redirect_event, short_link RESTART IDENTITY CASCADE")
            with cur.copy(
                "COPY short_link (code, destination, destination_canonical, client_id,"
                " created_at, expires_at, revoked_at, redirect_count, first_redirect_at,"
                " last_redirect_at) FROM STDIN"
            ) as copy:
                copy.write(buffer.read())
            cur.execute("ANALYZE short_link")
            cur.execute("SELECT count(*) FROM short_link")
            seeded = cur.fetchone()[0]

    with open(args.codes_out, "w", encoding="utf-8") as handle:
        handle.write("\n".join(codes))
    print(f"seeded {seeded} links; codes written to {args.codes_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
