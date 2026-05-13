"""
One-time renumbering script: docs/year_YYYY_week_N_*.md (0-indexed) -> N+1
(1-indexed) for all existing files. Also updates season_YYYY.md links.

Rationale: the previous convention named files such that the file for "display
week 5" lived at year_YYYY_week_4_*.md. This script aligns the filename's
week number with the displayed week number.

After running once, the renumbering is complete and this script should not be
re-run. Existing 1-indexed files are detected and skipped.
"""

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(HERE, 'docs')

WEEK_RE = re.compile(r'^year_(\d{4})_week_(\d+)_(no_quality|with_quality)\.md$')


def _git_mv(src, dst):
    """git mv if both paths are in the repo; otherwise os.rename."""
    try:
        subprocess.run(['git', 'mv', src, dst], check=True, cwd=HERE,
                       capture_output=True, text=True)
    except subprocess.CalledProcessError:
        # git refused (probably untracked) — just rename in place
        os.rename(src, dst)


def renumber_files(docs_dir=DOCS_DIR):
    """Find all year_YYYY_week_N_*.md and rename N -> N+1."""
    files = []
    for fn in os.listdir(docs_dir):
        m = WEEK_RE.match(fn)
        if not m:
            continue
        year = int(m.group(1))
        idx = int(m.group(2))
        kind = m.group(3)
        files.append((year, idx, kind, fn))

    # Sort by idx DESCENDING so we don't clobber the next-higher target.
    files.sort(key=lambda t: (t[0], -t[1]))

    renamed = 0
    for year, idx, kind, fn in files:
        src = os.path.join(docs_dir, fn)
        new_fn = 'year_{}_week_{}_{}.md'.format(year, idx + 1, kind)
        dst = os.path.join(docs_dir, new_fn)
        if os.path.exists(dst):
            # Already renumbered or naming collision — skip.
            print('  skip (target exists): {} -> {}'.format(fn, new_fn))
            continue
        _git_mv(src, dst)
        renamed += 1
    return renamed


def rewrite_season_links(docs_dir=DOCS_DIR):
    """
    Rewrite each season_YYYY.md file to bump week numbers in linked filenames
    by 1. Matches links of the form (year_YYYY_week_N_*.md).
    """
    link_re = re.compile(
        r'\(year_(\d{4})_week_(\d+)_(no_quality|with_quality)\.md\)'
    )
    rewritten = 0
    for fn in os.listdir(docs_dir):
        if not (fn.startswith('season_') and fn.endswith('.md')):
            continue
        p = os.path.join(docs_dir, fn)
        with open(p, 'r', encoding='utf-8') as f:
            text = f.read()

        def repl(m):
            return '(year_{}_week_{}_{}.md)'.format(
                m.group(1), int(m.group(2)) + 1, m.group(3))

        new_text = link_re.sub(repl, text)
        if new_text != text:
            with open(p, 'w', encoding='utf-8') as f:
                f.write(new_text)
            rewritten += 1
    return rewritten


def main():
    n_files = renumber_files()
    n_seasons = rewrite_season_links()
    print('Renamed {} .md files and rewrote {} season pages.'.format(
        n_files, n_seasons))


if __name__ == '__main__':
    main()
