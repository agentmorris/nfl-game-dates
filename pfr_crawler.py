"""
Pro-Football-Reference crawler with per-year JSON cache.

Output format (per year):
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
      "away_scores": [0, 7, 7, 7, 0, 21],   // [q1,q2,q3,q4,ot,final]
      "home_scores": [0, 14, 0, 7, 0, 20],
      "boxscore_url": "https://www.pro-football-reference.com/boxscores/..."
    },
    ...
  ]
}

Resumable: re-running picks up where the previous run left off, keyed by
boxscore_url. Saves after every game so interruption costs at most one
request.
"""

import importlib.util
import json
import os
import sys
import time

import requests
from bs4 import BeautifulSoup

# Reuse the existing parse function from nfl-game-dates.py
_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "_nfl_core", os.path.join(_HERE, "nfl-game-dates.py")
)
_nfl_core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_nfl_core)
_parse_game_from_boxscore_html = _nfl_core.parse_game_from_boxscore_html
_get_number_of_weeks_in_season = _nfl_core.get_number_of_weeks_in_season
_week_index_to_name = _nfl_core.week_index_to_name

BASE_URL = 'https://www.pro-football-reference.com'

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/131.0.0.0 Safari/537.36'
    ),
    'Accept': (
        'text/html,application/xhtml+xml,application/xml;q=0.9,'
        'image/avif,image/webp,image/apng,*/*;q=0.8,'
        'application/signed-exchange;v=b3;q=0.7'
    ),
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
    'Sec-Ch-Ua': '"Chromium";v="131", "Not_A Brand";v="24"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
}

# Default conservative rate limit. Bigger = friendlier.
DEFAULT_SLEEP_SECONDS = 10.0


def _load_cache(path):
    if not os.path.exists(path):
        return {'year': None, 'games': []}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_cache(cache, path):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp, path)


def _fetch(url, sleep_seconds):
    """GET with the configured headers. Returns text. Sleeps after."""
    resp = requests.get(url, headers=HEADERS, timeout=60)
    time.sleep(sleep_seconds)
    body = resp.text
    if resp.status_code == 429 or 'rate limited' in body.lower():
        raise RuntimeError('Rate limited fetching {}'.format(url))
    if resp.status_code >= 400:
        raise RuntimeError('HTTP {} fetching {}'.format(resp.status_code, url))
    if 'access denied' in body.lower():
        raise RuntimeError('Access denied fetching {}'.format(url))
    return body


def _week_url(year, week):
    return '{}/years/{}/week_{}.htm'.format(BASE_URL, year, week)


def _parse_week_page_for_boxscores(html):
    """Return list of relative boxscore URLs found on a week page, in order."""
    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table', {'class': 'teams'})
    out = []
    for table in tables:
        links = [a for a in table.find_all('a') if 'boxscores' in (a.get('href') or '')]
        if not links:
            continue
        out.append(links[0]['href'])
    return out


def _serialize_game(game_obj, week_idx, is_postseason, playoff_round, boxscore_url):
    """Convert a GameInfo (from _parse_game_from_boxscore_html) to a JSON dict."""
    return {
        'week_idx': week_idx,
        'is_postseason': is_postseason,
        'playoff_round': playoff_round,
        'away_team': game_obj.team_away,
        'home_team': game_obj.team_home,
        'datetime': game_obj.start_time.isoformat() if game_obj.start_time else None,
        'away_scores': game_obj.away_scores,
        'home_scores': game_obj.home_scores,
        'boxscore_url': boxscore_url,
    }


def crawl_year(year, cache_path, sleep_seconds=DEFAULT_SLEEP_SECONDS, verbose=True):
    """
    Crawl all weeks of a season, persisting to cache_path. Resumable.

    Returns the final cache dict.
    """
    cache = _load_cache(cache_path)
    if cache.get('year') is None:
        cache['year'] = year
    elif cache['year'] != year:
        raise ValueError(
            'Cache at {} is for year {}, not {}'.format(cache_path, cache['year'], year))

    seen_urls = {g['boxscore_url'] for g in cache['games']}

    n_regular = _get_number_of_weeks_in_season(year)
    n_playoff = 4
    total_weeks = n_regular + n_playoff  # PFR week numbers go 1..total_weeks

    for week in range(1, total_weeks + 1):
        week_idx = week - 1
        is_postseason = week_idx >= n_regular
        playoff_round = None
        if is_postseason:
            playoff_round = _week_index_to_name(week_idx, year)

        url = _week_url(year, week)
        if verbose:
            print('[{}] week {} -> {}'.format(year, week, url), flush=True)

        week_html = _fetch(url, sleep_seconds)
        rel_paths = _parse_week_page_for_boxscores(week_html)
        if not rel_paths:
            # PFR sometimes places the Super Bowl under the previous week URL
            if is_postseason and playoff_round == 'super bowl':
                if verbose:
                    print('  no games on this URL, super bowl may be under prior week',
                          flush=True)
                continue
            else:
                if verbose:
                    print('  WARNING: no games parsed on week page', flush=True)
                continue

        for rel in rel_paths:
            box_url = BASE_URL + rel
            if box_url in seen_urls:
                if verbose:
                    print('  cached: {}'.format(box_url), flush=True)
                continue

            if verbose:
                print('  fetching: {}'.format(box_url), flush=True)
            box_html = _fetch(box_url, sleep_seconds)
            game = _parse_game_from_boxscore_html(box_html, url=box_url)
            cache['games'].append(_serialize_game(
                game, week_idx, is_postseason, playoff_round, box_url))
            seen_urls.add(box_url)
            _save_cache(cache, cache_path)

    return cache


def main():
    import argparse
    p = argparse.ArgumentParser(description='Crawl a season from pro-football-reference.com')
    p.add_argument('year', type=int)
    p.add_argument('--cache-path', default=None,
                   help='Path to per-year JSON. Defaults to g:/temp/nfl-game-dates/year_YYYY.json')
    p.add_argument('--sleep-seconds', type=float, default=DEFAULT_SLEEP_SECONDS)
    p.add_argument('--quiet', action='store_true')
    args = p.parse_args()

    if args.cache_path is None:
        cache_dir = r'g:\temp\nfl-game-dates'
        os.makedirs(cache_dir, exist_ok=True)
        args.cache_path = os.path.join(cache_dir, 'year_{}.json'.format(args.year))

    crawl_year(args.year, args.cache_path,
               sleep_seconds=args.sleep_seconds,
               verbose=not args.quiet)


if __name__ == '__main__':
    main()
