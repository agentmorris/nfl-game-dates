"""
Ingest NFL game data from nflverse open data (no PFR crawl, no Cloudflare).

Produces the same per-year JSON format as pfr_crawler.py:
{
  "year": 2023,
  "games": [
    {
      "week_idx": 0,
      "is_postseason": false,
      "playoff_round": null,
      "away_team": "Detroit Lions",
      "home_team": "Kansas City Chiefs",
      "datetime": "2023-09-07T20:20:00",
      "away_scores": [q1,q2,q3,q4,ot,final],
      "home_scores": [q1,q2,q3,q4,ot,final],
      "boxscore_url": ""
    },
    ...
  ]
}

Sources:
  - https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv
    (schedule + final scores + game times for all seasons)
  - https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_YYYY.csv
    (play-by-play data for halftime scores; one file per season)
"""

import csv
import io
import json
import os
import requests
from collections import defaultdict
from datetime import datetime

GAMES_CSV_URL = (
    'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'
)
PBP_URL_TEMPLATE = (
    'https://github.com/nflverse/nflverse-data/releases/download/pbp/'
    'play_by_play_{year}.csv'
)

# nflverse team abbreviation -> canonical (current) full team name
ABBR_TO_TEAM = {
    'ARI': 'Arizona Cardinals',
    'ATL': 'Atlanta Falcons',
    'BAL': 'Baltimore Ravens',
    'BUF': 'Buffalo Bills',
    'CAR': 'Carolina Panthers',
    'CHI': 'Chicago Bears',
    'CIN': 'Cincinnati Bengals',
    'CLE': 'Cleveland Browns',
    'DAL': 'Dallas Cowboys',
    'DEN': 'Denver Broncos',
    'DET': 'Detroit Lions',
    'GB':  'Green Bay Packers',
    'HOU': 'Houston Texans',
    'IND': 'Indianapolis Colts',
    'JAX': 'Jacksonville Jaguars',
    'KC':  'Kansas City Chiefs',
    'LA':  'Los Angeles Rams',
    'LAR': 'Los Angeles Rams',
    'STL': 'Los Angeles Rams',         # pre-2016 (canonicalize to current)
    'LAC': 'Los Angeles Chargers',
    'SD':  'Los Angeles Chargers',     # pre-2017
    'LV':  'Las Vegas Raiders',
    'OAK': 'Las Vegas Raiders',        # pre-2020
    'MIA': 'Miami Dolphins',
    'MIN': 'Minnesota Vikings',
    'NE':  'New England Patriots',
    'NO':  'New Orleans Saints',
    'NYG': 'New York Giants',
    'NYJ': 'New York Jets',
    'PHI': 'Philadelphia Eagles',
    'PIT': 'Pittsburgh Steelers',
    'SEA': 'Seattle Seahawks',
    'SF':  'San Francisco 49ers',
    'TB':  'Tampa Bay Buccaneers',
    'TEN': 'Tennessee Titans',
    'WAS': 'Washington Commanders',
}

PLAYOFF_TYPE_TO_ROUND = {
    'WC':  'wild card',
    'DIV': 'divisional',
    'CON': 'championship',
    'SB':  'super bowl',
}


def _download(url, dest_path, force=False):
    if os.path.exists(dest_path) and not force:
        return dest_path
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp = dest_path + '.tmp'
    with requests.get(url, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        with open(tmp, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
    os.replace(tmp, dest_path)
    return dest_path


def _parse_games_csv(path, year):
    """Yield dicts for each game of `year`."""
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row['season']) != year:
                continue
            yield row


def _compute_halftime_scores(pbp_path, year):
    """
    Return dict {old_game_id -> (away_halftime, home_halftime)} from pbp data.
    Halftime = max(total_*_score) over plays with qtr <= 2.
    """
    halftime = {}
    with open(pbp_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            qtr_str = row.get('qtr')
            if not qtr_str:
                continue
            try:
                qtr = int(qtr_str)
            except ValueError:
                continue
            if qtr > 2:
                continue
            gid = row.get('old_game_id') or row.get('game_id')
            if not gid:
                continue
            try:
                hs = int(row.get('total_home_score') or 0)
                aw = int(row.get('total_away_score') or 0)
            except ValueError:
                continue
            prev = halftime.get(gid, (0, 0))
            halftime[gid] = (max(prev[0], aw), max(prev[1], hs))
    return halftime


def _quarters_from_pbp(pbp_path, year):
    """
    Return dict {old_game_id -> {'away': [q1,q2,q3,q4,ot,final], 'home': [...]}}.
    Each list is six entries: Q1, Q2, Q3, Q4, OT-total, final.
    OT-total is the sum of all OT periods. Final equals the box-score final.
    """
    # End-of-quarter cumulative scores per game per quarter
    # end_score[gid][qtr] = (away_total, home_total) at the END of that quarter
    end_score = defaultdict(dict)
    final_score = {}
    with open(pbp_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            qtr_str = row.get('qtr')
            if not qtr_str:
                continue
            try:
                qtr = int(qtr_str)
            except ValueError:
                continue
            gid = row.get('old_game_id') or row.get('game_id')
            if not gid:
                continue
            try:
                hs = int(row.get('total_home_score') or 0)
                aw = int(row.get('total_away_score') or 0)
            except ValueError:
                continue
            prev = end_score[gid].get(qtr, (0, 0))
            # Cumulative is monotonic; keep max seen
            end_score[gid][qtr] = (max(prev[0], aw), max(prev[1], hs))
            # Also track final from away_score/home_score on this row
            try:
                fa = int(row.get('away_score') or 0)
                fh = int(row.get('home_score') or 0)
                final_score[gid] = (fa, fh)
            except ValueError:
                pass

    result = {}
    for gid, quarters in end_score.items():
        away_quarters = [0, 0, 0, 0, 0]  # Q1, Q2, Q3, Q4, OT
        home_quarters = [0, 0, 0, 0, 0]
        prev_away = prev_home = 0
        # Q1
        a1, h1 = quarters.get(1, (0, 0))
        away_quarters[0] = a1 - prev_away
        home_quarters[0] = h1 - prev_home
        prev_away, prev_home = a1, h1
        # Q2
        a2, h2 = quarters.get(2, (prev_away, prev_home))
        away_quarters[1] = a2 - prev_away
        home_quarters[1] = h2 - prev_home
        prev_away, prev_home = a2, h2
        # Q3
        a3, h3 = quarters.get(3, (prev_away, prev_home))
        away_quarters[2] = a3 - prev_away
        home_quarters[2] = h3 - prev_home
        prev_away, prev_home = a3, h3
        # Q4
        a4, h4 = quarters.get(4, (prev_away, prev_home))
        away_quarters[3] = a4 - prev_away
        home_quarters[3] = h4 - prev_home
        prev_away, prev_home = a4, h4
        # OT (sum across 5+)
        ot_away = 0
        ot_home = 0
        for q in range(5, 10):
            if q in quarters:
                qa, qh = quarters[q]
                ot_away += qa - prev_away
                ot_home += qh - prev_home
                prev_away, prev_home = qa, qh
        away_quarters[4] = ot_away
        home_quarters[4] = ot_home

        fa, fh = final_score.get(gid, (prev_away, prev_home))
        away_list = list(away_quarters) + [fa]
        home_list = list(home_quarters) + [fh]
        result[gid] = {'away': away_list, 'home': home_list}
    return result


def _week_idx_from_game(row):
    """
    Map nflverse week + game_type to our 0-indexed week_idx, matching the
    convention used elsewhere (REG week 1 = idx 0, WC = idx n_regular, ...).
    """
    gtype = row['game_type']
    week = int(row['week'])
    if gtype == 'REG':
        return week - 1  # week is 1-indexed in CSV; our idx is 0-indexed
    # nflverse uses week 19/20/21/22 for WC/DIV/CON/SB. After the 17-game era
    # this aligns with n_regular=18 → WC at idx 18. Same as our convention.
    return week - 1


def _parse_datetime(gameday, gametime):
    if not gameday:
        return None
    if gametime:
        try:
            return datetime.fromisoformat('{} {}'.format(gameday, gametime))
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(gameday)
    except ValueError:
        return None


def build_year_cache(year, data_dir, output_path):
    """
    Download (or reuse cached) source data and write a year JSON to output_path.
    """
    games_csv_path = os.path.join(data_dir, 'games.csv')
    pbp_csv_path = os.path.join(data_dir, 'pbp_{}.csv'.format(year))

    _download(GAMES_CSV_URL, games_csv_path)
    _download(PBP_URL_TEMPLATE.format(year=year), pbp_csv_path)

    quarters = _quarters_from_pbp(pbp_csv_path, year)

    cache = {'year': year, 'games': []}
    for row in _parse_games_csv(games_csv_path, year):
        gtype = row['game_type']
        is_postseason = gtype != 'REG'
        playoff_round = PLAYOFF_TYPE_TO_ROUND.get(gtype) if is_postseason else None
        week_idx = _week_idx_from_game(row)
        away = ABBR_TO_TEAM.get(row['away_team'], row['away_team'])
        home = ABBR_TO_TEAM.get(row['home_team'], row['home_team'])
        dt = _parse_datetime(row['gameday'], row['gametime'])

        gid = row['old_game_id']
        q = quarters.get(gid)
        if q is None:
            # No pbp for this game (shouldn't happen for completed games)
            away_scores = None
            home_scores = None
        else:
            away_scores = q['away']
            home_scores = q['home']

        cache['games'].append({
            'week_idx': week_idx,
            'is_postseason': is_postseason,
            'playoff_round': playoff_round,
            'away_team': away,
            'home_team': home,
            'datetime': dt.isoformat() if dt else None,
            'away_scores': away_scores,
            'home_scores': home_scores,
            'boxscore_url': '',
        })

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2)
    return cache


def main():
    import argparse
    p = argparse.ArgumentParser(description='Build year JSON from nflverse data')
    p.add_argument('year', type=int)
    p.add_argument('--data-dir', default=r'g:\temp\nfl-game-dates',
                   help='Where to cache nflverse source files')
    p.add_argument('--output', default=None,
                   help='Output JSON path (default: <data-dir>/year_YYYY.json)')
    args = p.parse_args()

    output = args.output or os.path.join(args.data_dir, 'year_{}.json'.format(args.year))
    cache = build_year_cache(args.year, args.data_dir, output)
    print('Wrote {} games to {}'.format(len(cache['games']), output))


if __name__ == '__main__':
    main()
