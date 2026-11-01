#!/usr/bin/env python3
"""Scale-exponent certificate + timing bench for html2text reference-link mode.

Only the reference-link path (`HTML2Text.inline_links = False`) is touched by
the patch: `previousIndex()` used to rescan the whole anchor list for every
emitted reference link, which is quadratic in the number of anchors.  This
script measures end-to-end `convert()` time for

  * synthetic documents with N unique anchors (N sweep, exponent certificate)
  * real-world HTML documents passed on the command line (`--real`)

Every individual sample is written to benchmark/raw/ so the aggregates can be
recomputed.  Timing uses time.perf_counter(); the RNG seed is fixed.

Usage:
  python benchmark/bench.py --impl baseline  --pkg /tmp/ht_base --sweep
  python benchmark/bench.py --impl optimized --sweep
"""

import argparse
import json
import os
import platform
import random
import statistics
import sys
import time
from pathlib import Path

SEED = 20261102
TIMED_REPEATS = 7
WARMUPS = 3
SWEEP_SIZES = [250, 500, 1000, 2000, 4000]
TIMING_SIZES = [300, 900, 2700]
RAW_DIR = Path(__file__).resolve().parent / "raw"


def synth_doc(n, seed=SEED):
    """N anchors, each with a distinct href, inside one paragraph."""
    rnd = random.Random(seed)
    out = ["<html><body><p>"]
    for i in range(n):
        out.append('<a href="https://example.org/doc/%d">word%d</a> ' % (i, i))
    out.append("</p></body></html>")
    # keep rnd referenced so the fixed seed is explicit even if order changes
    rnd.random()
    return "".join(out)


def make_converter():
    import html2text

    h = html2text.HTML2Text()
    h.inline_links = False
    h.body_width = 0
    return h


def time_once(doc):
    import html2text  # noqa: F401  (ensure import cost is outside the timer)

    h = make_converter()
    t0 = time.perf_counter()
    out = h.handle(doc)
    return time.perf_counter() - t0, out


def measure(doc, warmups=WARMUPS, repeats=TIMED_REPEATS):
    samples = []
    for _ in range(warmups):
        time_once(doc)
    for _ in range(repeats):
        dt, out = time_once(doc)
        samples.append(dt)
    return samples


def time_corpus(docs):
    """One timed run = convert every document once, sum of per-doc times."""
    total = 0.0
    for doc in docs:
        total += time_once(doc)[0]
    return total


def measure_corpus(docs, warmups=2, repeats=5):
    samples = []
    for _ in range(warmups):
        time_corpus(docs)
    for _ in range(repeats):
        samples.append(time_corpus(docs))
    return samples


def aggregate(samples):
    s = sorted(samples)
    n = len(s)
    q1 = s[n // 4]
    q3 = s[(3 * n) // 4]
    med = statistics.median(s)
    mean = statistics.fmean(s)
    sd = statistics.pstdev(s) if n > 1 else 0.0
    rsd = (sd / mean) if mean else 0.0
    return {
        "n": n,
        "median_s": med,
        "p25_s": q1,
        "p75_s": q3,
        "min_s": s[0],
        "max_s": s[-1],
        "mean_s": mean,
        "stdev_s": sd,
        "rsd": rsd,
        "samples_s": samples,
    }


def slope(points):
    """Least-squares log-log slope; points = [(n, seconds), ...]."""
    import math

    xs = [math.log(n) for n, _ in points]
    ys = [math.log(t) for _, t in points]
    mx = statistics.fmean(xs)
    my = statistics.fmean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else float("nan")


def env_info():
    cpu = ""
    try:
        for line in open("/proc/cpuinfo", encoding="utf-8", errors="replace"):
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    mem_kb = None
    try:
        for line in open("/proc/meminfo", encoding="utf-8"):
            if line.startswith("MemTotal:"):
                mem_kb = int(line.split()[1])
                break
    except OSError:
        pass
    return {
        "cpu": cpu,
        "mem_total_kb": mem_kb,
        "cores": os.cpu_count(),
        "python": sys.version,
        "platform": platform.platform(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--impl", required=True, choices=["baseline", "optimized"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--pkg", default=None, help="dir prepended to sys.path")
    ap.add_argument("--sweep", action="store_true", help="run the exponent sweep")
    ap.add_argument("--real", nargs="*", default=[])
    ap.add_argument("--real-dir", default=None,
                    help="time every *.html in this dir as one corpus (upstream fixtures)")
    ap.add_argument("--real-limit", type=int, default=0, help="cap anchors per real doc")
    args = ap.parse_args()

    if args.pkg:
        sys.path.insert(0, args.pkg)
    import html2text

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    result = {
        "impl": args.impl,
        "seed": SEED,
        "warmups": WARMUPS,
        "timed_repeats": TIMED_REPEATS,
        "command": " ".join([sys.executable] + sys.argv),
        "env": env_info(),
        "html2text_version": getattr(html2text, "__version__", "unknown"),
        "html2text_file": html2text.__file__,
        "timing": {},
        "sweep": {},
        "real": {},
    }

    # --- synthetic timing scales -------------------------------------------------
    for n in TIMING_SIZES:
        doc = synth_doc(n)
        samples = measure(doc)
        agg = aggregate(samples)
        result["timing"][str(n)] = agg
        for i, dt in enumerate(samples):
            (RAW_DIR / ("%s-synth%d-%d.json" % (args.impl, n, i))).write_text(
                json.dumps({"impl": args.impl, "scale": n, "kind": "synth",
                            "i": i, "seconds": dt, "chars": len(doc)}) + "\n"
            )
        print("synth n=%-6d median=%.6fs p25=%.6fs p75=%.6fs rsd=%.3f"
              % (n, agg["median_s"], agg["p25_s"], agg["p75_s"], agg["rsd"]), flush=True)

    # --- exponent certificate ----------------------------------------------------
    if args.sweep:
        pts = []
        for n in SWEEP_SIZES:
            doc = synth_doc(n)
            samples = measure(doc, warmups=2, repeats=5)
            agg = aggregate(samples)
            agg["chars"] = len(doc)
            result["sweep"][str(n)] = agg
            pts.append((n, agg["median_s"]))
            for i, dt in enumerate(samples):
                (RAW_DIR / ("%s-sweep%d-%d.json" % (args.impl, n, i))).write_text(
                    json.dumps({"impl": args.impl, "scale": n, "kind": "sweep",
                                "i": i, "seconds": dt, "chars": len(doc)}) + "\n"
                )
            print("sweep n=%-6d median=%.6fs" % (n, agg["median_s"]), flush=True)
        result["sweep_exponent"] = slope(pts)

    # --- real corpus -------------------------------------------------------------
    for path in args.real:
        p = Path(path)
        if not p.is_file():
            print("SKIP missing real doc: %s" % path, file=sys.stderr)
            continue
        doc = p.read_text(encoding="utf-8", errors="replace")
        samples = measure(doc, warmups=2, repeats=5)
        agg = aggregate(samples)
        agg["path"] = str(p)
        agg["chars"] = len(doc)
        agg["anchors"] = doc.count("<a ")
        result["real"][p.name] = agg
        for i, dt in enumerate(samples):
            (RAW_DIR / ("%s-real-%s-%d.json" % (args.impl, p.name, i))).write_text(
                json.dumps({"impl": args.impl, "scale": p.name, "kind": "real",
                            "i": i, "seconds": dt, "chars": len(doc),
                            "anchors": agg["anchors"]}) + "\n"
            )
        print("real %-20s anchors=%-6d median=%.6fs rsd=%.3f"
              % (p.name, agg["anchors"], agg["median_s"], agg["rsd"]), flush=True)

    if args.real_dir:
        d = Path(args.real_dir)
        files = sorted(d.glob("*.html"))
        docs = [f.read_text(encoding="utf-8", errors="replace") for f in files]
        samples = measure_corpus(docs, warmups=2, repeats=5)
        agg = aggregate(samples)
        agg["path"] = str(d)
        agg["files"] = len(files)
        agg["bytes"] = sum(len(x.encode("utf-8")) for x in docs)
        agg["anchors"] = sum(x.count("<a ") for x in docs)
        result["real_corpus_dir"] = agg
        for i, dt in enumerate(samples):
            (RAW_DIR / ("%s-realcorpus-%d.json" % (args.impl, i))).write_text(
                json.dumps({"impl": args.impl, "scale": "upstream_fixtures",
                            "kind": "real_corpus", "i": i, "seconds": dt,
                            "files": agg["files"], "bytes": agg["bytes"],
                            "anchors": agg["anchors"]}) + "\n"
            )
        print("real-corpus %-16s files=%-4d bytes=%-8d anchors=%-6d median=%.6fs"
              % (d.name, agg["files"], agg["bytes"], agg["anchors"], agg["median_s"]),
              flush=True)

    out = Path(args.out) if args.out else (
        Path(__file__).resolve().parent / ("%s.json" % args.impl))
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("wrote %s" % out)


if __name__ == "__main__":
    main()
