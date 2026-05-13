"""
Team conference/division metadata. Divisions have been stable since 2002.
Handles team renames so historical team strings still resolve.
"""

_DIVISIONS = {
    'AFC East':  ['Buffalo Bills', 'Miami Dolphins', 'New England Patriots', 'New York Jets'],
    'AFC North': ['Baltimore Ravens', 'Cincinnati Bengals', 'Cleveland Browns', 'Pittsburgh Steelers'],
    'AFC South': ['Houston Texans', 'Indianapolis Colts', 'Jacksonville Jaguars', 'Tennessee Titans'],
    'AFC West':  ['Denver Broncos', 'Kansas City Chiefs', 'Los Angeles Chargers', 'Las Vegas Raiders'],
    'NFC East':  ['Dallas Cowboys', 'New York Giants', 'Philadelphia Eagles', 'Washington Commanders'],
    'NFC North': ['Chicago Bears', 'Detroit Lions', 'Green Bay Packers', 'Minnesota Vikings'],
    'NFC South': ['Atlanta Falcons', 'Carolina Panthers', 'New Orleans Saints', 'Tampa Bay Buccaneers'],
    'NFC West':  ['Arizona Cardinals', 'Los Angeles Rams', 'San Francisco 49ers', 'Seattle Seahawks'],
}

# Aliases: any historical name -> the canonical (current) franchise name.
_ALIASES = {
    'San Diego Chargers':       'Los Angeles Chargers',
    'Oakland Raiders':          'Las Vegas Raiders',
    'St. Louis Rams':           'Los Angeles Rams',
    'Washington Redskins':      'Washington Commanders',
    'Washington Football Team': 'Washington Commanders',
}

_TEAM_TO_DIV = {}
for div, teams in _DIVISIONS.items():
    for team in teams:
        _TEAM_TO_DIV[team] = div
for alias, canonical in _ALIASES.items():
    _TEAM_TO_DIV[alias] = _TEAM_TO_DIV[canonical]


def canonical_name(team):
    return _ALIASES.get(team, team)


def division_of(team):
    """Return the division name (e.g. 'AFC East'). Accepts historical names."""
    return _TEAM_TO_DIV[team]


def conference_of(team):
    return division_of(team).split(' ')[0]


def all_teams():
    """All 32 canonical team names."""
    return [t for teams in _DIVISIONS.values() for t in teams]


def playoff_seeds_per_conference(year):
    """7 since 2020, 6 before."""
    assert isinstance(year, int)
    return 7 if year >= 2020 else 6
