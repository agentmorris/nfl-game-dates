"""
Backfill the "eliminated" indicator into existing docs/year_YYYY_week_N_with_quality.md
files (seasons 2009-2022).

Approach: parse the existing _no_quality.md files (which contain pre-week
records for every regular-season game) to reconstruct each team's record by
week and each game's outcome. Feed that into elimination.compute_eliminations()
to determine, going into each regular-season week, which teams are
mathematically out. Then surgically edit the matching _with_quality.md file:
for each game line, append ", eliminated" inside the parenthetical for any
team that's already eliminated.
"""

import importlib.util
import os
import re
import sys

from collections import defaultdict

from elimination import compute_eliminations
from team_metadata import canonical_name

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "_nfl_core", os.path.join(_HERE, "nfl-game-dates.py")
)
_nfl_core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_nfl_core)
_get_number_of_weeks_in_season = _nfl_core.get_number_of_weeks_in_season

DOCS_DIR = os.path.join(_HERE, 'docs')

# Match a game line, with or without the leading <br/>, with optional tie in
# either record, in either no-quality or with-quality format. The trailing
# group captures everything after the home parenthetical.
_GAME_LINE_RE = re.compile(
    r'^(?P<br>(?:<br/>)?)'
    r'(?P<away>.+?) \((?P<aw>\d+)-(?P<al>\d+)(?:-(?P<at>\d+))?(?:, eliminated)?\)'
    r' at '
    r'(?P<home>.+?) \((?P<hw>\d+)-(?P<hl>\d+)(?:-(?P<ht>\d+))?(?:, eliminated)?\)'
    r'(?P<rest>,.+)$'
)


def _parse_no_quality_md(path):
    """
    Return list of game records: each is a dict with away_team, home_team,
    away_record (W,L,T), home_record (W,L,T), datetime_str, raw_line.
    """
    games = []
    with open(path, 'r', encoding='utf-8') as f:
        for raw in f:
            line = raw.rstrip('\n')
            m = _GAME_LINE_RE.match(line)
            if not m:
                continue
            games.append({
                'away_team': m.group('away'),
                'away_record': (int(m.group('aw')), int(m.group('al')),
                                int(m.group('at') or 0)),
                'home_team': m.group('home'),
                'home_record': (int(m.group('hw')), int(m.group('hl')),
                                int(m.group('ht') or 0)),
                'rest': m.group('rest'),
                'raw_line': line,
            })
    return games


def _reconstruct_season(year, docs_dir=DOCS_DIR):
    """
    Parse all regular-season _no_quality.md files for `year`. Returns:
      (games_by_week, schedule_games, records_at)

    games_by_week: dict {week_idx -> list of parsed game dicts from the md}
    schedule_games: list of game dicts suitable for compute_eliminations(),
                    with 'away_score'/'home_score' = 1/0 for known results
                    (1/1 for a tie), or None/None for unknown.
    records_at: dict {week_idx -> {team -> (W,L,T)}}, filled across byes so
                every team has a record going into every regular-season week.
    """
    n_regular = _get_number_of_weeks_in_season(year)
    games_by_week = {}
    for i_week in range(n_regular):
        p = os.path.join(docs_dir,
                         'year_{}_week_{}_no_quality.md'.format(year, i_week + 1))
        if not os.path.exists(p):
            raise FileNotFoundError(p)
        games_by_week[i_week] = _parse_no_quality_md(p)

    # Per-team list of (week_idx, record) from each week they appear.
    team_appearances = defaultdict(list)
    for i_week, glist in games_by_week.items():
        for g in glist:
            team_appearances[canonical_name(g['away_team'])].append((i_week, g['away_record']))
            team_appearances[canonical_name(g['home_team'])].append((i_week, g['home_record']))

    # Build full records_at by propagating across bye weeks.
    # records_at[i_week][team] = record going INTO week i_week.
    # If team is on bye in week k, record going into k+1 = record going into k.
    records_at = {i: {} for i in range(n_regular)}
    for team, appearances in team_appearances.items():
        appearances.sort(key=lambda x: x[0])
        # Before the team's first appearance, record is (0,0,0)
        first_week = appearances[0][0]
        for i in range(first_week):
            records_at[i][team] = (0, 0, 0)
        # Walk forward: between two consecutive appearances, the record is the
        # later one's pre-game record. Wait -- if a team plays in week i then
        # has a bye in week i+1 and plays again in week i+2: their record
        # going into i+1 equals their record going into i+2 (no game in
        # between).
        for idx in range(len(appearances)):
            week_i, rec = appearances[idx]
            # Record at week_i is `rec` (pre-game for week_i).
            records_at[week_i][team] = rec
            # Next appearance week (or end)
            next_week = appearances[idx + 1][0] if idx + 1 < len(appearances) else n_regular
            # Between week_i+1 and next_week-1: bye weeks. Records going into
            # those weeks equal record going into next_week (which is rec
            # plus the result of the week_i game). We can derive that.
            if idx + 1 < len(appearances):
                next_rec = appearances[idx + 1][1]
                for k in range(week_i + 1, next_week):
                    records_at[k][team] = next_rec
            else:
                # After last appearance: derive final record by inferring the
                # outcome of the team's last game. We don't strictly need
                # these for elimination at start-of-week (only weeks
                # < n_regular matter), but fill in for completeness using
                # the last known pre-game record.
                for k in range(week_i + 1, n_regular):
                    records_at[k][team] = rec  # best we can do without next

    # Derive game results: for each game involving team T in week i, look at
    # T's record going into the *next week T plays* (or rather, T's record in
    # records_at[i+1] which has been propagated). Compare to T's pre-game
    # record.
    schedule_games = []
    for i_week in range(n_regular):
        for g in games_by_week[i_week]:
            away = canonical_name(g['away_team'])
            home = canonical_name(g['home_team'])
            entry = {
                'week_idx': i_week,
                'is_postseason': False,
                'away_team': away,
                'home_team': home,
                'away_score': None,
                'home_score': None,
            }
            # Try to derive the result using away team's record change
            if i_week + 1 < n_regular and away in records_at[i_week + 1]:
                aw_before = g['away_record']
                aw_after = records_at[i_week + 1][away]
                if aw_after[0] > aw_before[0]:
                    entry['away_score'] = 1
                    entry['home_score'] = 0
                elif aw_after[1] > aw_before[1]:
                    entry['away_score'] = 0
                    entry['home_score'] = 1
                elif aw_after[2] > aw_before[2]:
                    entry['away_score'] = 1
                    entry['home_score'] = 1  # tie: equal scalar scores
            schedule_games.append(entry)

    return games_by_week, schedule_games, records_at


def _build_snapshot_for_week(schedule_games, i_week):
    """Snapshot for elimination calc: weeks < i_week have known results, others unplayed."""
    snap = []
    for g in schedule_games:
        g2 = dict(g)
        if g['week_idx'] >= i_week:
            g2['away_score'] = None
            g2['home_score'] = None
        snap.append(g2)
    return snap


def _rewrite_with_quality(year, i_week, eliminated, docs_dir=DOCS_DIR):
    """
    Read the existing _with_quality.md for (year, i_week) and rewrite each game
    line to inject ", eliminated" into the appropriate team's parens.
    """
    path = os.path.join(docs_dir,
                        'year_{}_week_{}_with_quality.md'.format(year, i_week + 1))
    if not os.path.exists(path):
        return False

    with open(path, 'r', encoding='utf-8') as f:
        lines = f.read().split('\n')

    out_lines = []
    for line in lines:
        m = _GAME_LINE_RE.match(line)
        if not m:
            out_lines.append(line)
            continue

        away_str = m.group('away')
        home_str = m.group('home')
        aw, al, at = m.group('aw'), m.group('al'), m.group('at')
        hw, hl, ht = m.group('hw'), m.group('hl'), m.group('ht')
        br = m.group('br')
        rest = m.group('rest')

        def fmt_rec(w, l, t):
            s = '{}-{}'.format(w, l)
            if t is not None:
                s += '-{}'.format(t)
            return s

        away_canon = canonical_name(away_str)
        home_canon = canonical_name(home_str)
        away_elim = eliminated.get(away_canon, False)
        home_elim = eliminated.get(home_canon, False)

        away_body = fmt_rec(aw, al, at)
        if away_elim:
            away_body += ', eliminated'
        home_body = fmt_rec(hw, hl, ht)
        if home_elim:
            home_body += ', eliminated'

        new_line = '{}{} ({}) at {} ({}){}'.format(
            br, away_str, away_body, home_str, home_body, rest)
        out_lines.append(new_line)

    new_content = '\n'.join(out_lines)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    return True


def backfill_year(year, docs_dir=DOCS_DIR, verbose=True):
    import time
    n_regular = _get_number_of_weeks_in_season(year)
    games_by_week, schedule_games, records_at = _reconstruct_season(year, docs_dir)

    for i_week in range(n_regular):
        snapshot = _build_snapshot_for_week(schedule_games, i_week)
        t0 = time.time()
        eliminated = compute_eliminations(snapshot, year)
        elapsed = time.time() - t0
        ok = _rewrite_with_quality(year, i_week, eliminated, docs_dir)
        if verbose:
            n_elim = sum(1 for v in eliminated.values() if v)
            print('  {} week {} (display week {}): {} eliminated, {:.1f}s, file {}'.format(
                year, i_week, i_week + 1, n_elim, elapsed,
                'rewritten' if ok else 'MISSING'), flush=True)


def main():
    import argparse
    p = argparse.ArgumentParser(description='Backfill elimination indicators into legacy _with_quality.md files')
    p.add_argument('--years', nargs='+', type=int, default=list(range(2009, 2023)),
                   help='Years to backfill (default: 2009-2022)')
    p.add_argument('--docs-dir', default=DOCS_DIR)
    args = p.parse_args()

    for year in args.years:
        print('Backfilling year {}'.format(year))
        backfill_year(year, docs_dir=args.docs_dir)


if __name__ == '__main__':
    main()
