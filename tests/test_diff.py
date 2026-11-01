#!/usr/bin/env python3
"""Differential test: upstream html2text vs the patched build.

The baseline package is reconstructed on the fly by reverse-applying
``patch.diff`` to a copy of the repo's ``html2text/`` package, so the test is
self-contained and offline.

Every generated input is hashed (sha256 of the exact HTML plus the converter
options); the reported N is the number of *distinct* inputs actually compared,
not the number of loop iterations.
"""

import hashlib
import importlib.util
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "html2text"
PATCH = ROOT / "patch.diff"
N_TARGET = 2600
SEED = 20261102


def build_baseline(dst: Path) -> Path:
    """Copy the package and reverse-apply patch.diff to get the upstream code."""
    shutil.copytree(PKG, dst / "html2text")
    # _version.py is generated at install time and may not be tracked
    ver = PKG / "_version.py"
    if ver.exists():
        shutil.copy(ver, dst / "html2text" / "_version.py")
    applied = False
    if shutil.which("patch"):
        r = subprocess.run(["patch", "-p1", "-R", "-i", str(PATCH)],
                           cwd=dst, capture_output=True, text=True)
        applied = r.returncode == 0
    if not applied:
        subprocess.run(["git", "init", "-q"], cwd=dst, check=True)
        subprocess.run(["git", "apply", "-R", str(PATCH)], cwd=dst, check=True)
        applied = True
    assert applied, "could not reverse-apply patch.diff"
    return dst / "html2text"


def load_package(name: str, pkg_dir: Path):
    spec = importlib.util.spec_from_file_location(
        name, pkg_dir / "__init__.py", submodule_search_locations=[str(pkg_dir)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def convert(mod, doc, opts):
    h = mod.HTML2Text()
    for k, v in opts.items():
        setattr(h, k, v)
    return h.handle(doc)


def rnd_href(rnd, style):
    if style == 0:
        return "https://ex.org/a/%d" % rnd.randrange(50)
    if style == 1:
        return "https://ex.org/u/%d" % rnd.randrange(10 ** 9)
    if style == 2:
        return "/rel/%d?x=%d" % (rnd.randrange(20), rnd.randrange(5))
    if style == 3:
        return "#frag-%d" % rnd.randrange(5)
    if style == 4:
        return "mailto:user%d@ex.org" % rnd.randrange(5)
    return "https://例え.jp/路径/%d" % rnd.randrange(30)


def rnd_doc(rnd):
    n = rnd.randrange(0, 60)
    parts = ["<html><body>"]
    for i in range(n):
        style = rnd.randrange(6)
        href = rnd_href(rnd, style)
        title = ""
        if rnd.random() < 0.35:
            title = ' title="%s"' % rnd.choice(["t%d" % rnd.randrange(4), "日本語", "a b"])
        body = rnd.choice(["x%d" % i, "词%d" % i, "", "  spaced  "])
        parts.append('<a href="%s"%s>%s</a>' % (href, title, body))
        if rnd.random() < 0.3:
            parts.append("<p>text %d</p>" % i)
        if rnd.random() < 0.15:
            parts.append('<img src="%s" alt="alt%d">' % (rnd_href(rnd, 0), i))
    if rnd.random() < 0.2:
        parts.append('<a href="https://ex.org/a/0">nested <a href="/rel/1">inner</a></a>')
    if rnd.random() < 0.2:
        parts.append("<table><tr><td><a href='/rel/2?x=1'>cell</a></td></tr></table>")
    parts.append("</body></html>")
    return "".join(parts)


def boundary_cases():
    return [
        ("", {}),
        ("<html><body></body></html>", {}),
        ("<a href=''>empty href</a>", {}),
        ('<a href="https://x/1">single</a>', {}),
        ('<a href="https://x/1" title="t">a</a><a href="https://x/1" title="t">b</a>', {}),
        ('<a href="https://x/1" title="t">a</a><a href="https://x/1">b</a>', {}),
        ('<a href="https://x/1">a</a><a href="https://x/1" title="t">b</a>', {}),
        ('<a href="#f1">a</a><a href="#f1">b</a><a href="#f2">c</a>', {}),
        ('<a href="mailto:a@b.c">m</a><a href="mailto:a@b.c">m2</a>', {}),
        ('<img src="https://x/i.png" alt="i"><img src="https://x/i.png" alt="j">', {}),
        ('<a href="' + "h" * 3000 + '">long</a>', {}),
        ("<a href='https://例え.jp/路径/1'>非ASCII</a>" * 3, {}),
        ('<a href="https://x/1">a</a>', {"inline_links": True}),
        ('<a href="https://x/1">a</a>', {"ignore_links": True}),
        ('<a href="https://x/1">a</a>', {"protect_links": True}),
        ('<a href="https://x/1">a</a>', {"images_to_alt": True}),
        ('<a href="https://x/1">a</a>', {"links_each_paragraph": True}),
        ('<a href="https://x/1">a</a>', {"body_width": 20}),
    ]


def main():
    tmp = Path(tempfile.mkdtemp(prefix="h2t_diff_"))
    base_dir = build_baseline(tmp)
    base = load_package("html2text_base", base_dir)

    sys.path.insert(0, str(ROOT))
    import html2text as opt

    rnd = random.Random(SEED)
    seen = {}
    n_unique = 0
    n_mismatch = 0
    fails = []

    def check(doc, opts):
        nonlocal n_unique, n_mismatch
        key = hashlib.sha256(
            (doc + "\x00" + json.dumps(opts, sort_keys=True)).encode("utf-8")
        ).hexdigest()
        if key in seen:
            return
        seen[key] = True
        n_unique += 1
        a = convert(base, doc, opts)
        b = convert(opt, doc, opts)
        if a != b:
            n_mismatch += 1
            if len(fails) < 5:
                fails.append({"doc": doc[:200], "opts": opts,
                              "baseline": a[:200], "optimized": b[:200]})

    for doc, opts in boundary_cases():
        check(doc, opts)

    while n_unique < N_TARGET:
        opts = {
            "inline_links": rnd.random() < 0.7,
            "body_width": rnd.choice([0, 40, 78]),
            "protect_links": rnd.random() < 0.1,
            "images_to_alt": rnd.random() < 0.1,
            "links_each_paragraph": rnd.random() < 0.1,
        }
        if rnd.random() < 0.15:
            opts["ignore_links"] = True
        check(rnd_doc(rnd), opts)

    # Direct method-level fuzzing: random self.a states + random query attrs.
    for it in range(400):
        h = opt.HTML2Text()
        h.inline_links = False
        pool = []
        for _ in range(rnd.randrange(0, 25)):
            at = {"href": rnd_href(rnd, rnd.randrange(6))}
            if rnd.random() < 0.5:
                at["title"] = rnd.choice(["t%d" % rnd.randrange(4), "日本語"])
            pool.append(at)
        h.a = [opt.AnchorElement(dict(at), i + 1, i) for i, at in enumerate(pool)]
        hb = base.HTML2Text()
        for _ in range(rnd.randrange(0, 8)):
            q = {}
            if rnd.random() < 0.9:
                q["href"] = rnd_href(rnd, rnd.randrange(6))
            if rnd.random() < 0.5:
                q["title"] = rnd.choice(["t%d" % rnd.randrange(4), "日本語"])
            ra = base.HTML2Text()
            ra.a = [base.AnchorElement(dict(x.attrs), x.count, x.outcount) for x in h.a]
            if h.previousIndex(dict(q)) != ra.previousIndex(dict(q)):
                n_mismatch += 1
                fails.append({"kind": "method", "q": q,
                              "a": [x.attrs for x in h.a]})

    shutil.rmtree(tmp, ignore_errors=True)

    ok = n_mismatch == 0 and n_unique >= 1000
    print(json.dumps({
        "unique_inputs": n_unique,
        "distinct_method_states": None,
        "mismatches": n_mismatch,
        "de_dup": "sha256(html + json(options))",
        "seed": SEED,
        "result": "PASS" if ok else "FAIL",
        "failures": fails,
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
