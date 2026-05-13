"""
Generate the .md pages for a season from a cached year JSON file
(see pfr_crawler.py for the JSON schema).

Produces, into docs/:
  year_YYYY_week_N_no_quality.md       (N is 0-indexed, matches existing convention)
  year_YYYY_week_N_with_quality.md
  season_YYYY.md

Also rewrites docs/index.md to include the year list.

The no_quality page just shows records going into the week.
The with_quality page additionally shows good/bad game tags AND, for
regular-season weeks, a per-team ", eliminated" marker for teams that have no
remaining path to the playoffs.
"""

import importlib.util
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

from elimination import compute_eliminations
from team_metadata import canonical_name

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "_nfl_core", os.path.join(_HERE, "nfl-game-dates.py")
)
_nfl_core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_nfl_core)
_get_number_of_weeks_in_season = _nfl_core.get_number_of_weeks_in_season
_week_index_to_name = _nfl_core.week_index_to_name
_team_name_from_team_string = _nfl_core.team_name_from_team_string

DOCS_DIR = os.path.join(_HERE, 'docs')


def _load_year(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _parse_dt(s):
    if s is None:
        return None
    return datetime.fromisoformat(s)


def _games_by_week(year_cache):
    """Group games by week_idx, sorted by datetime within each week."""
    by_week = defaultdict(list)
    for g in year_cache['games']:
        by_week[g['week_idx']].append(g)
    for w in by_week:
        by_week[w].sort(key=lambda g: _parse_dt(g['datetime']) or datetime.max)
    return by_week


def _compute_weekly_records(games, n_regular):
    """
    Return list of length n_regular+1 of dicts {team -> {'wins','losses','ties'}}.
    Index i = records going INTO week i (0-indexed; index 0 = all zeros).
    Only regular-season games count.
    """
    teams = set()
    for g in games:
        teams.add(g['away_team'])
        teams.add(g['home_team'])
    # Use canonical names
    teams = {canonical_name(t) for t in teams}

    rec = {t: {'wins': 0, 'losses': 0, 'ties': 0} for t in teams}

    by_week = defaultdict(list)
    for g in games:
        if g['week_idx'] < n_regular:
            by_week[g['week_idx']].append(g)

    result = [dict((t, dict(r)) for t, r in rec.items())]
    for i_week in range(n_regular):
        for g in by_week.get(i_week, []):
            away = canonical_name(g['away_team'])
            home = canonical_name(g['home_team'])
            ascore = g.get('away_scores', [None] * 6)[-1] if g.get('away_scores') else None
            hscore = g.get('home_scores', [None] * 6)[-1] if g.get('home_scores') else None
            if ascore is None or hscore is None:
                continue
            if ascore > hscore:
                rec[away]['wins'] += 1
                rec[home]['losses'] += 1
            elif hscore > ascore:
                rec[home]['wins'] += 1
                rec[away]['losses'] += 1
            else:
                rec[away]['ties'] += 1
                rec[home]['ties'] += 1
        result.append(dict((t, dict(r)) for t, r in rec.items()))
    return result


def _compute_game_quality(g):
    """Return 'good', 'bad', or None for a played regular-season game."""
    away = g.get('away_scores')
    home = g.get('home_scores')
    if not away or not home or away[-1] is None or home[-1] is None:
        return None
    home_final = home[-1]
    away_final = away[-1]
    diff = abs(home_final - away_final)
    home_halftime = home[0] + home[1]
    away_halftime = away[0] + away[1]
    if home_final > away_final:
        result = 'home_win'
    elif away_final > home_final:
        result = 'away_win'
    else:
        result = 'tie'
    if home_halftime > away_halftime:
        halftime_result = 'home_win'
    elif away_halftime > home_halftime:
        halftime_result = 'away_win'
    else:
        halftime_result = 'tie'

    if diff > 16 and result == halftime_result:
        return 'bad'

    second_half_comeback = (halftime_result != 'tie' and halftime_result != result)
    total = home_final + away_final
    if diff <= 8 or second_half_comeback or (diff <= 16 and total > 60):
        return 'good'
    return None


def _zero_padding():
    return '#' if os.name == 'nt' else '-'


def _format_record(rec):
    s = '{}-{}'.format(rec['wins'], rec['losses'])
    if rec['ties'] > 0:
        s += '-{}'.format(rec['ties'])
    return s


def _format_game_line(g, records=None, eliminated=None, include_quality=False, prev_dt=None):
    """
    records: optional dict {team -> {wins,losses,ties}}; if provided, append "(W-L[-T])"
             after each team name.
    eliminated: optional dict {team -> bool}; if a team is True, append ", eliminated"
                inside the parens (only when records is also provided).
    include_quality: if True, append " (:football: good game)" or " (:red_circle: bad game)".
    prev_dt: previous game datetime; used to insert <br/> for gaps > 1 hour.
    """
    pad = _zero_padding()
    away = g['away_team']
    home = g['home_team']
    dt = _parse_dt(g['datetime'])

    def team_label(team_str):
        if records is None:
            return team_str
        canon = canonical_name(team_str)
        rec = records.get(canon, {'wins': 0, 'losses': 0, 'ties': 0})
        elim = bool(eliminated) and eliminated.get(canon, False)
        body = _format_record(rec)
        if elim:
            body += ', eliminated'
        return '{} ({})'.format(team_str, body)

    time_str = dt.strftime('%A, %b %{}d, %{}I:%M %p'.format(pad, pad)) if dt else ''
    base = '{} at {}, {}'.format(team_label(away), team_label(home), time_str)

    if include_quality:
        q = _compute_game_quality(g)
        if q == 'good':
            base += ' (:football: good game)'
        elif q == 'bad':
            base += ' (:red_circle: bad game)'

    line = base
    if prev_dt is not None and dt is not None and (dt - prev_dt) > timedelta(hours=1):
        line = '<br/>' + line
    return line, dt


def _render_week_md(year, week_idx, games, records=None, eliminated=None,
                    include_quality=False):
    """Render markdown content for a single week page."""
    week_name = _week_index_to_name(week_idx, year)
    header = (
        '---\n'
        'title: NFL simulated-real-time schedules, 2009-present\n'
        'description: " "\n'
        '---\n\n'
        '# Game info for {} {}\n\n'.format(year, week_name)
    )
    body_parts = []
    prev_dt = None
    for g in games:
        line, prev_dt = _format_game_line(
            g, records=records, eliminated=eliminated,
            include_quality=include_quality, prev_dt=prev_dt,
        )
        body_parts.append(line)
    body = '\n\n'.join(body_parts) + '\n'
    return header + body


def _render_season_md(year, total_weeks):
    s = (
        '---\n'
        'title: NFL simulated-real-time schedules, 2009-present\n'
        'description: " "\n'
        '---\n\n'
        '# Game info for the {} season\n\n'
        '## Records only\n\n'.format(year)
    )
    for i_week in range(total_weeks):
        s += '* [{}](year_{}_week_{}_no_quality.md)\n'.format(
            _week_index_to_name(i_week, year).title(), year, i_week + 1)
    s += '\n## With quality indicators\n\n'
    for i_week in range(total_weeks):
        s += '* [{}](year_{}_week_{}_with_quality.md)\n'.format(
            _week_index_to_name(i_week, year).title(), year, i_week + 1)
    return s


def _render_index_md(years_present):
    """Rewrite docs/index.md from header.txt + year links."""
    with open(os.path.join(_HERE, 'header.txt'), 'r', encoding='utf-8') as f:
        header = f.read()
    s = header
    if not s.endswith('\n'):
        s += '\n'
    s += '\n'
    for year in years_present:
        s += '* [{}](season_{}.md)\n'.format(year, year)
    return s


def generate_for_year(year, cache_path, docs_dir=DOCS_DIR, write_index=True):
    """
    Generate all week pages + season page for a single year from a year JSON.
    Optionally also rewrites docs/index.md to include all years currently
    present as season_YYYY.md files in docs_dir.
    """
    cache = _load_year(cache_path)
    if cache['year'] != year:
        raise ValueError('Cache year mismatch: {} vs {}'.format(cache['year'], year))

    n_regular = _get_number_of_weeks_in_season(year)
    by_week = _games_by_week(cache)
    total_weeks = max(by_week.keys()) + 1 if by_week else 0

    # Per-week regular-season records going into each week.
    weekly_records = _compute_weekly_records(cache['games'], n_regular)

    # For elimination at the start of week i, only consider games played in
    # weeks 0..i-1. We mark eliminations only for regular-season weeks.
    sorted_games = list(cache['games'])

    eliminations_per_week = {}
    for i_week in range(n_regular):
        # Build a snapshot for elimination: regular-season games only, with
        # scalar away_score / home_score derived from the per-quarter lists.
        # Games at or beyond i_week are shown as unplayed (None scores) so the
        # solver can search them as remaining games.
        snapshot = []
        for g in sorted_games:
            if g.get('is_postseason'):
                continue
            g2 = dict(g)
            if g['week_idx'] < i_week:
                aw = g.get('away_scores')
                ho = g.get('home_scores')
                g2['away_score'] = aw[-1] if aw else None
                g2['home_score'] = ho[-1] if ho else None
            else:
                g2['away_score'] = None
                g2['home_score'] = None
            snapshot.append(g2)
        eliminations_per_week[i_week] = compute_eliminations(snapshot, year)

    os.makedirs(docs_dir, exist_ok=True)
    for i_week in range(total_weeks):
        games = by_week.get(i_week, [])
        records_in = weekly_records[i_week] if i_week < n_regular else None
        eliminated_in = eliminations_per_week.get(i_week) if i_week < n_regular else None

        nq = _render_week_md(year, i_week, games, records=records_in,
                             eliminated=None, include_quality=False)
        wq = _render_week_md(year, i_week, games, records=records_in,
                             eliminated=eliminated_in, include_quality=True)

        with open(os.path.join(docs_dir, 'year_{}_week_{}_no_quality.md'.format(
                year, i_week + 1)), 'w', encoding='utf-8') as f:
            f.write(nq)
        with open(os.path.join(docs_dir, 'year_{}_week_{}_with_quality.md'.format(
                year, i_week + 1)), 'w', encoding='utf-8') as f:
            f.write(wq)

    with open(os.path.join(docs_dir, 'season_{}.md'.format(year)), 'w',
              encoding='utf-8') as f:
        f.write(_render_season_md(year, total_weeks))

    if write_index:
        # Scan docs_dir for all season_YYYY.md files
        years = []
        for fn in os.listdir(docs_dir):
            if fn.startswith('season_') and fn.endswith('.md'):
                try:
                    y = int(fn[len('season_'):-len('.md')])
                    years.append(y)
                except ValueError:
                    pass
        years.sort()
        with open(os.path.join(docs_dir, 'index.md'), 'w', encoding='utf-8') as f:
            f.write(_render_index_md(years))


def main():
    import argparse
    p = argparse.ArgumentParser(description='Generate season .md pages from cached JSON')
    p.add_argument('year', type=int)
    p.add_argument('--cache-path', default=None)
    p.add_argument('--docs-dir', default=DOCS_DIR)
    p.add_argument('--no-index', action='store_true',
                   help='Skip rewriting docs/index.md')
    args = p.parse_args()

    if args.cache_path is None:
        args.cache_path = os.path.join(r'g:\temp\nfl-game-dates',
                                       'year_{}.json'.format(args.year))
    generate_for_year(args.year, args.cache_path, docs_dir=args.docs_dir,
                      write_index=not args.no_index)


if __name__ == '__main__':
    main()
