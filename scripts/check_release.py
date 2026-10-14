#!/usr/bin/env python3
"""Release documentation consistency checks.

Automates the doc-consistency part of docs/RELEASE_PROCESS.md. Only
"current" surfaces are scanned (README, CI workflow, i18n module) —
CHANGELOG.md and docs/ are deliberately NOT scanned for versions, since
release history legitimately mentions old version numbers.

Each check and the concrete mistake it prevents:

1. versions        — the README "From source" install command and the
                     "Latest release" link lagging the package version
                     (historically: README shipped a 3.0.2 wheel command
                     after 3.0.3 was released). Also pyproject vs
                     __init__ version drift.
2. ci-matrix       — the CI matrix not covering the Python versions the
                     package claims to support (historically: 3.13/3.14
                     claimed via requires-python but never tested).
3. i18n            — translation JSON files drifting out of key parity,
                     empty translations that silently fall back to
                     English, the language registry / README language
                     list drifting from the files on disk.
4. fingerprint     — a mistyped GPG fingerprint or spacing drift in one
                     of the places that publish it (README,
                     RELEASE_PROCESS, release.yml) — after a key rotation
                     every published copy must stay identical.
5. --site-dir      — (optional, the site checkout lives outside this
                     repo, so this cannot run in CI) the website's
                     install command / version lagging the README, the
                     PEP 668 note going missing, the fingerprint being
                     formatted differently from the README.

Usage:
    python3 scripts/check_release.py
    python3 scripts/check_release.py --site-dir /path/to/virtdeck-site

Exit code 0 = all checks passed, 1 = at least one failure.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

FINGERPRINT = "117DEABD3EA48810B219BA6B401F700FB97DE8B8"
FINGERPRINT_SOURCES = [
    "README.md",
    "docs/RELEASE_PROCESS.md",
    ".github/workflows/release.yml",
]

failures: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)
    print("FAIL  " + msg)


def ok(msg: str) -> None:
    print("ok    " + msg)


def read(relpath: str) -> str:
    return (REPO / relpath).read_text(encoding="utf-8")


# ---------------------------------------------------------------- versions
def check_versions() -> str:
    """All current install/release references must match the package version."""
    pyproject = read("pyproject.toml")
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
    if not m:
        fail("pyproject.toml: [project] version not found")
        return "unknown"
    version = m.group(1)

    m = re.search(r'^__version__\s*=\s*"([^"]+)"', read("virtdeck/__init__.py"), re.M)
    if not m or m.group(1) != version:
        fail(f"virtdeck/__init__.py __version__ ({m.group(1) if m else 'missing'}) "
             f"!= pyproject version ({version})")
    else:
        ok(f"pyproject.toml and __init__.py agree on {version}")

    readme = read("README.md")
    wheels = set(re.findall(r"virtdeck-(\d+\.\d+\.\d+)-py3-none-any\.whl", readme))
    if wheels != {version}:
        fail(f"README wheel filename(s) {sorted(wheels)} != current version {version}")
    else:
        ok(f"README install command references the current wheel {version}")

    latest = set(re.findall(r"Latest release: \[v(\d+\.\d+\.\d+)\]", readme))
    tags = set(re.findall(r"releases/tag/v(\d+\.\d+\.\d+)", readme))
    if latest != {version} or tags != {version}:
        fail(f"README release references (Latest: {sorted(latest)}, "
             f"tag links: {sorted(tags)}) != current version {version}")
    else:
        ok("README 'Latest release' link points at the current version")
    return version


# --------------------------------------------------------------- ci matrix
def check_ci_matrix() -> None:
    """The CI matrix must cover exactly the Python versions the package
    declares (classifiers + requires-python floor)."""
    pyproject = read("pyproject.toml")
    classifiers = set(re.findall(
        r'"Programming Language :: Python :: (3\.\d+)"', pyproject))
    m = re.search(r'requires-python\s*=\s*">=(\d+\.\d+)"', pyproject)
    floor = m.group(1) if m else None

    ci = read(".github/workflows/ci.yml")
    matrices = [set(re.findall(r"'(\d+\.\d+)'", block))
                for block in re.findall(r"python-version:\s*\[([^\]]*)\]", ci)]
    if len(matrices) < 2:
        fail(f"ci.yml: expected 2 python-version matrices (lint, tests), "
             f"found {len(matrices)}")
        return
    lint, tests = matrices[0], matrices[1]
    if lint != tests:
        fail(f"ci.yml: lint matrix {sorted(lint)} != tests matrix {sorted(tests)}")
    if not classifiers:
        fail("pyproject.toml: no versioned 'Programming Language :: Python :: 3.X' "
             "classifiers — CI matrix coverage cannot be validated against claims")
        return
    if lint != classifiers:
        fail(f"ci.yml matrix {sorted(lint)} != declared support {sorted(classifiers)} "
             f"(classifiers and CI must cover the same versions)")
    else:
        ok(f"CI matrix covers exactly the declared Python support: "
           f"{sorted(lint)}")
    if floor and floor not in lint:
        fail(f"requires-python floor {floor} is missing from the CI matrix")
    if "release-checks" not in ci:
        fail("ci.yml: release-checks job is missing")


# --------------------------------------------------------------------- i18n
def check_i18n(readme: str) -> None:
    """Translation JSON files must stay in parity with each other and with
    the language registry / README."""
    i18n_dir = REPO / "virtdeck" / "ui" / "i18n"
    json_langs = {p.stem for p in i18n_dir.glob("*.json")}

    init = read("virtdeck/ui/i18n/__init__.py")
    m = re.search(r"_JSON_LANGS\s*=\s*\{([^}]*)\}", init)
    registry = set(re.findall(r'"(\w+)"', m.group(1))) if m else set()
    if not m or registry != json_langs:
        fail(f"i18n/_JSON_LANGS {sorted(registry)} != JSON files on disk "
             f"{sorted(json_langs)}")
    else:
        ok(f"i18n: _JSON_LANGS matches the {len(json_langs)} JSON files on disk")

    m = re.search(r"_SUPPORTED_LANGUAGES\s*=\s*\{(.*?)\}", init, re.S)
    supported = set(re.findall(r'"(\w+)":', m.group(1))) if m else set()
    if not m or supported != {"en"} | json_langs:
        fail(f"i18n/_SUPPORTED_LANGUAGES {sorted(supported)} != "
             f"{{en}} + JSON files {sorted({'en'} | json_langs)}")
    else:
        ok("i18n: _SUPPORTED_LANGUAGES covers en + every shipped JSON")

    keysets: dict[str, set] = {}
    for path in i18n_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            fail(f"i18n/{path.name}: not valid JSON: {e}")
            continue
        keysets[path.stem] = set(data)
        empty = [k for k, v in data.items() if not str(v).strip()]
        if empty:
            fail(f"i18n/{path.name}: empty translations (silent English "
                 f"fallback): {', '.join(sorted(empty)[:5])}"
                 + (" ..." if len(empty) > 5 else ""))
    if keysets:
        base_lang = "ru"
        ref = keysets.get(base_lang) or next(iter(keysets.values()))
        for lang, keys in sorted(keysets.items()):
            if keys == ref:
                continue
            missing = sorted(ref - keys)[:5]
            extra = sorted(keys - ref)[:5]
            fail(f"i18n parity broken: {lang} vs {base_lang} — "
                 f"missing: {missing}, extra: {extra}")
        if all(k == ref for k in keysets.values()):
            ok(f"i18n: {len(keysets)} JSON files in key parity "
               f"({len(ref)} keys each)")

    m = re.search(r"## Language switching\n(.*?)(?=\n## )", readme, re.S)
    if not m:
        fail("README: '## Language switching' section not found")
        return
    documented = set(re.findall(r"^- .+?\((\w{2,3})\)\s*$", m.group(1), re.M))
    if documented != supported:
        fail(f"README 'Supported languages' list {sorted(documented)} != "
             f"_SUPPORTED_LANGUAGES {sorted(supported)}")
    else:
        ok("README language list matches the i18n registry")


# -------------------------------------------------------------- fingerprint
def check_fingerprint() -> None:
    """Every published fingerprint copy must be the canonical value; the
    display form must use single spaces (the old double space at the gpg
    two-line join is exactly the drift this catches)."""
    display_re = re.compile(r"[0-9A-F]{4}(?:[ \t]+[0-9A-F]{4}){9}")
    machine_re = re.compile(r"(?<![0-9A-F])[0-9A-F]{40}(?![0-9A-F])")
    for rel in FINGERPRINT_SOURCES:
        text = read(rel)
        hits = 0
        for match in display_re.finditer(text):
            hits += 1
            groups = match.group(0).split()
            if "".join(groups) != FINGERPRINT:
                fail(f"{rel}: fingerprint value {match.group(0)!r} does not match "
                     f"the canonical {FINGERPRINT}")
            elif any(sep != " " or len(sep) != 1 for sep in
                     re.findall(r"[ \t]+", match.group(0))):
                fail(f"{rel}: fingerprint formatting {match.group(0)!r} — "
                     f"expected single spaces between groups")
        for match in machine_re.finditer(text):
            hits += 1
            if match.group(0) != FINGERPRINT:
                fail(f"{rel}: machine-form fingerprint {match.group(0)} does not "
                     f"match the canonical value")
        if hits == 0:
            fail(f"{rel}: fingerprint not found at all (it must stay published)")
        else:
            ok(f"{rel}: fingerprint published and canonical ({hits} occurrence(s))")


# --------------------------------------------------------------------- site
def check_site(site_dir: Path, version: str) -> None:
    """Optional: verify the website checkout against the README install
    instructions. The site lives in a separate repo, so CI cannot run this;
    it is a manual/CI-local step documented in RELEASE_PROCESS.md."""
    index_path = site_dir / "public" / "index.html"
    if not index_path.is_file():
        fail(f"--site-dir: {index_path} not found (expected <site>/public/index.html)")
        return
    html = index_path.read_text(encoding="utf-8").replace("&#160;", " ")

    site_wheels = set(re.findall(r"virtdeck-(\d+\.\d+\.\d+)-py3-none-any\.whl", html))
    site_tags = set(re.findall(r"releases/download/v(\d+\.\d+\.\d+)/", html))
    if site_wheels != {version} or site_tags != {version}:
        fail(f"site references (wheels {sorted(site_wheels)}, "
             f"assets {sorted(site_tags)}) != current version {version} — "
             f"run the site's update-version.sh")
    else:
        ok(f"site download links reference the current version {version}")

    # The pip command must stay token-identical to the README's (line
    # continuation and wrapping differences are normalized away).
    def pip_tokens(text: str) -> list[str] | None:
        # site: <pre id="pre-src">…</pre>; README: the fenced block under
        # "### From source". Comments are dropped, backslash continuations
        # are joined, then the single "pip install …" line is extracted.
        m = re.search(r'<pre id="pre-src">(.*?)</pre>', text, re.S)
        if not m:
            m = re.search(r"### From source.*?```bash\n(.*?)```", text, re.S)
        if not m:
            return None
        chunk = re.sub(r"(?m)^\s*#.*$", "", m.group(1))
        chunk = re.sub(r"\\\s*\n\s*", " ", chunk)
        m = re.search(r"pip install (.+)", chunk)
        return sorted(m.group(1).split()) if m else None

    readme_cmd = pip_tokens(read("README.md"))
    site_cmd = pip_tokens(html)
    if not readme_cmd or not site_cmd:
        fail("could not extract the 'pip install' command from README and/or "
             "site pre-src for comparison")
    elif readme_cmd != site_cmd:
        fail(f"site 'pip install' command drifted from README:\n"
             f"      README: {' '.join(readme_cmd)}\n"
             f"      site:   {' '.join(site_cmd)}")
    else:
        ok("site 'pip install' command is token-identical to the README's")

    if "PEP 668" not in html:
        fail("site 'From source' block has no PEP 668 note (the README's "
             "warning about protected system Python must be mirrored)")
    else:
        ok("site carries the PEP 668 note")

    display = re.findall(r"[0-9A-F]{4}(?:[ \t]+[0-9A-F]{4}){9}", html)
    if not display:
        fail("site: fingerprint not found in index.html")
    for match in display:
        if "".join(match.split()) != FINGERPRINT:
            fail(f"site: fingerprint value mismatch: {match!r}")
        elif not re.fullmatch(r"[0-9A-F]{4}(?: [0-9A-F]{4}){9}", match):
            fail(f"site: fingerprint formatting drift: {match!r} "
                 f"(expected single spaces)")
    if display and all(
        "".join(match.split()) == FINGERPRINT
        and re.fullmatch(r"[0-9A-F]{4}(?: [0-9A-F]{4}){9}", match)
        for match in display
    ):
        ok("site fingerprint matches the canonical single-space form")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--site-dir", type=Path, default=None,
        help="optional virtdeck-site checkout to verify against the README")
    args = parser.parse_args()

    version = check_versions()
    readme = read("README.md")
    check_ci_matrix()
    check_i18n(readme)
    check_fingerprint()
    if args.site_dir:
        check_site(args.site_dir, version)

    print()
    if failures:
        print(f"{len(failures)} failure(s)")
        return 1
    print("all release consistency checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
