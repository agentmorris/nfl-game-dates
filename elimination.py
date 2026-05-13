"""
NFL playoff elimination logic.

A team is "eliminated" if there is no possible assignment of remaining
regular-season game outcomes that puts the team in their conference's playoff
field, applying NFL tiebreakers: head-to-head, division record, common games,
conference record. We do not look beyond conference record (no strength of
victory / schedule / points-based tiebreakers).

The implementation uses a best-case-for-X scenario simulation:
  - team X wins all remaining games
  - every other conference team loses all remaining games where possible
  - in games between two non-X conference teams, the team with the lower
    current win total wins (so the higher team can't pad)
  - unresolved tiebreakers are awarded to X (we ask "is X alive in ANY
    scenario", so favorable tiebreaker resolution counts as a valid scenario)

This is a sound *over-approximation* of "alive": a team this routine marks
alive is plausibly alive; a team it marks eliminated is provably eliminated
under the chosen tiebreaker set. The heuristic for breaking intra-conference
non-X games can in rare edge cases cause us to mark a team eliminated when an
alternate scenario assignment would have saved them. In practice these cases
are very rare.
"""

from team_metadata import (
    division_of, conference_of, all_teams, canonical_name,
    playoff_seeds_per_conference,
)


def _result_of(game):
    """
    Return (winner, loser, is_tie) from a completed game, or None if not played.
    winner/loser are canonical team names. For ties, returns (team_a, team_b, True).
    """
    if game.get('away_score') is None or game.get('home_score') is None:
        return None
    away = canonical_name(game['away_team'])
    home = canonical_name(game['home_team'])
    if game['away_score'] > game['home_score']:
        return (away, home, False)
    elif game['home_score'] > game['away_score']:
        return (home, away, False)
    else:
        return (away, home, True)


def _is_played(game):
    return game.get('away_score') is not None and game.get('home_score') is not None


def _is_regular_season(game):
    return game.get('week_idx') is not None and game.get('is_postseason', False) is False


def _current_record(team, games):
    """(wins, losses, ties) from played regular-season games involving `team`."""
    w = l = t = 0
    for g in games:
        if not _is_regular_season(g) or not _is_played(g):
            continue
        away = canonical_name(g['away_team'])
        home = canonical_name(g['home_team'])
        if team not in (away, home):
            continue
        r = _result_of(g)
        winner, loser, is_tie = r
        if is_tie:
            t += 1
        elif winner == team:
            w += 1
        else:
            l += 1
    return w, l, t


def _build_best_case_scenario(team_X, games, intra_conf_heuristic='higher_wins'):
    """
    Return a list of "resolved" games (every regular-season game has a result)
    representing the best case for team_X.

    intra_conf_heuristic chooses how to break ties when two non-X teams in
    X's conference play each other:
      - 'higher_wins': the team with more current wins wins. Tends to
        concentrate wins on fewer teams (leaving more teams below X).
      - 'lower_wins':  the team with fewer current wins wins. Tends to spread
        wins more evenly (more teams clustered at moderate records).
      - 'alphabetical': deterministic but arbitrary.
    """
    team_X = canonical_name(team_X)
    conf_X = conference_of(team_X)

    current_wins = {t: _current_record(t, games)[0] for t in all_teams()}

    resolved = []
    for g in games:
        if not _is_regular_season(g):
            resolved.append(dict(g))
            continue
        if _is_played(g):
            resolved.append(dict(g))
            continue

        away = canonical_name(g['away_team'])
        home = canonical_name(g['home_team'])

        if team_X in (away, home):
            winner = team_X
        else:
            in_conf_away = (conference_of(away) == conf_X)
            in_conf_home = (conference_of(home) == conf_X)

            if in_conf_away and in_conf_home:
                if intra_conf_heuristic == 'higher_wins':
                    if current_wins[away] > current_wins[home]:
                        winner = away
                    elif current_wins[home] > current_wins[away]:
                        winner = home
                    else:
                        winner = sorted([away, home])[0]
                elif intra_conf_heuristic == 'lower_wins':
                    if current_wins[away] < current_wins[home]:
                        winner = away
                    elif current_wins[home] < current_wins[away]:
                        winner = home
                    else:
                        winner = sorted([away, home])[0]
                else:  # alphabetical
                    winner = sorted([away, home])[0]
            elif in_conf_away and not in_conf_home:
                # Make the conference team lose (so its final record is lower)
                winner = home
            elif in_conf_home and not in_conf_away:
                winner = away
            else:
                # Neither in X's conference. Doesn't affect our tiebreakers.
                winner = sorted([away, home])[0]

        new_g = dict(g)
        if winner == away:
            new_g['away_score'] = 1
            new_g['home_score'] = 0
        else:
            new_g['away_score'] = 0
            new_g['home_score'] = 1
        new_g['_synthesized'] = True
        current_wins[winner] += 1
        resolved.append(new_g)

    return resolved


def _record_against(team, opponents, games):
    """Wins/losses/ties from team's regular-season games against a set of opponents."""
    w = l = t = 0
    opponents = set(opponents)
    for g in games:
        if not _is_regular_season(g) or not _is_played(g):
            continue
        away = canonical_name(g['away_team'])
        home = canonical_name(g['home_team'])
        if team not in (away, home):
            continue
        other = home if team == away else away
        if other not in opponents:
            continue
        r = _result_of(g)
        winner, loser, is_tie = r
        if is_tie:
            t += 1
        elif winner == team:
            w += 1
        else:
            l += 1
    return w, l, t


def _opponents_of(team, games):
    """Set of regular-season opponents (all played games)."""
    opps = set()
    for g in games:
        if not _is_regular_season(g) or not _is_played(g):
            continue
        away = canonical_name(g['away_team'])
        home = canonical_name(g['home_team'])
        if team == away:
            opps.add(home)
        elif team == home:
            opps.add(away)
    return opps


def _pct(record):
    w, l, t = record
    n = w + l + t
    if n == 0:
        return 0.5  # No games yet: neutral
    return (w + 0.5 * t) / n


def _break_tie_division(teams, games, favor=None):
    """
    Apply NFL division-tiebreaker rules (truncated to HH, div, common, conf) and
    return teams sorted best-first. `favor` is the team to award unresolved
    ties to (used when checking "is X alive in best-case").
    """
    return _apply_tiebreakers(
        teams, games, favor,
        order=['head_to_head', 'division', 'common', 'conference'],
    )


def _break_tie_wildcard(teams, games, favor=None):
    """
    Apply NFL wild-card tiebreaker rules (truncated). Note: when 2+ teams are
    from the same division, division tiebreakers must reduce them to a single
    representative first; this is handled in the caller.
    """
    return _apply_tiebreakers(
        teams, games, favor,
        order=['head_to_head', 'conference', 'common'],
    )


def _apply_tiebreakers(teams, games, favor, order):
    """
    Sort `teams` from best to worst using the given tiebreaker `order`.
    `favor` (if set) wins any unresolved tie.
    """
    # Recursive: pick a tiebreaker, partition by it, recurse on each group.
    if len(teams) <= 1:
        return list(teams)

    for tb in order:
        scores = {t: _tiebreaker_score(t, teams, games, tb) for t in teams}
        # If everyone has the same score, this tiebreaker doesn't help. Skip.
        unique = set(scores.values())
        if len(unique) == 1:
            continue
        # Partition: sort by score desc, then group equal scores
        sorted_teams = sorted(teams, key=lambda t: scores[t], reverse=True)
        result = []
        i = 0
        while i < len(sorted_teams):
            j = i
            while j < len(sorted_teams) and scores[sorted_teams[j]] == scores[sorted_teams[i]]:
                j += 1
            group = sorted_teams[i:j]
            if len(group) > 1:
                # Recurse on the tied group with remaining tiebreakers
                remaining_order = order[order.index(tb) + 1:]
                result.extend(_apply_tiebreakers(group, games, favor, remaining_order))
            else:
                result.extend(group)
            i = j
        return result

    # Tiebreakers exhausted: award unresolved to `favor` if among teams
    if favor in teams:
        rest = [t for t in teams if t != favor]
        return [favor] + sorted(rest)
    return sorted(teams)


def _tiebreaker_score(team, group, games, tiebreaker):
    """Return a comparable score for `team` within `group` for the given tiebreaker."""
    from team_metadata import _DIVISIONS  # type: ignore

    if tiebreaker == 'head_to_head':
        others = [t for t in group if t != team]
        # For 3+ team ties, NFL only applies HH if there's a round-robin
        # sweep. We approximate: require every pair in the group to have
        # played at least one game. Otherwise return a neutral score so this
        # tiebreaker is effectively skipped (all teams get the same value).
        if len(group) > 2:
            for a in group:
                for b in group:
                    if a == b:
                        continue
                    w, l, t_ = _record_against(a, [b], games)
                    if w + l + t_ == 0:
                        return 0.5  # incomplete round-robin; skip HH
        return _pct(_record_against(team, others, games))

    if tiebreaker == 'division':
        div_name = division_of(team)
        div_mates = [t for t in _DIVISIONS[div_name] if t != team]
        return _pct(_record_against(team, div_mates, games))

    if tiebreaker == 'conference':
        conf = conference_of(team)
        conf_teams = [t for div_name, teams in _DIVISIONS.items()
                      if div_name.startswith(conf) for t in teams if t != team]
        return _pct(_record_against(team, conf_teams, games))

    if tiebreaker == 'common':
        # Common opponents = intersection of opponents across `group`
        opp_sets = [_opponents_of(t, games) for t in group]
        common = set.intersection(*opp_sets) if opp_sets else set()
        # Exclude teams in the tied group themselves (technically common
        # opponents includes any opponent shared by all tied teams, which can
        # include other tied teams).
        common = common - set(group)
        if len(common) < 4:
            return 0.5  # Insufficient: neutral, doesn't help discriminate
        return _pct(_record_against(team, common, games))

    raise ValueError('Unknown tiebreaker: {}'.format(tiebreaker))


def _conference_playoff_teams(conf, games, year, favor=None):
    """
    Determine which teams from this conference would make the playoffs given
    the (resolved) `games` list. Returns the set of seeded teams.

    Steps:
      1. Find each division winner (best team in division by division tiebreakers).
      2. Sort division winners by record + tiebreakers for seeds 1-4.
      3. From the non-division-winners, pick top (n_seeds - 4) wild cards.
         When multiple wild-card candidates are from the same division,
         resolve them with division tiebreakers first.
    """
    from team_metadata import _DIVISIONS  # type: ignore
    n_seeds = playoff_seeds_per_conference(year)

    divisions = {d: teams for d, teams in _DIVISIONS.items() if d.startswith(conf)}

    # Find division winners
    division_winners = []
    for div_name, div_teams in divisions.items():
        # Group teams by win pct first, then break ties with division tiebreakers
        seeded = _seed_within_division(div_teams, games, favor)
        division_winners.append(seeded[0])

    # Seed division winners by pct + tiebreakers
    division_winners_sorted = _seed_across_conference(division_winners, games, favor)

    # Now pick wild cards from non-division-winners
    non_winners = []
    for div_name, div_teams in divisions.items():
        seeded = _seed_within_division(div_teams, games, favor)
        non_winners.extend(seeded[1:])

    wild_cards_needed = n_seeds - 4
    wild_cards = _pick_wildcards(non_winners, wild_cards_needed, games, favor)

    return set(division_winners_sorted) | set(wild_cards)


def _seed_within_division(div_teams, games, favor):
    """Sort division teams best-first, applying division tiebreakers."""
    records = {t: _current_record(t, games) for t in div_teams}
    pcts = {t: _pct(records[t]) for t in div_teams}

    # Group by pct desc
    sorted_teams = sorted(div_teams, key=lambda t: pcts[t], reverse=True)
    result = []
    i = 0
    while i < len(sorted_teams):
        j = i
        while j < len(sorted_teams) and pcts[sorted_teams[j]] == pcts[sorted_teams[i]]:
            j += 1
        group = sorted_teams[i:j]
        if len(group) > 1:
            result.extend(_break_tie_division(group, games, favor))
        else:
            result.extend(group)
        i = j
    return result


def _seed_across_conference(teams, games, favor):
    """Seed division winners against each other (uses division-style tiebreakers)."""
    pcts = {t: _pct(_current_record(t, games)) for t in teams}
    sorted_teams = sorted(teams, key=lambda t: pcts[t], reverse=True)
    result = []
    i = 0
    while i < len(sorted_teams):
        j = i
        while j < len(sorted_teams) and pcts[sorted_teams[j]] == pcts[sorted_teams[i]]:
            j += 1
        group = sorted_teams[i:j]
        if len(group) > 1:
            # Use wild-card-style tiebreakers for cross-division division-winners.
            # (NFL uses a specific order; we'll use HH -> conf -> common.)
            result.extend(_break_tie_wildcard(group, games, favor))
        else:
            result.extend(group)
        i = j
    return result


def _pick_wildcards(non_winners, n_needed, games, favor):
    """Pick the top n_needed wild-card teams from non_winners."""
    if n_needed <= 0:
        return []

    # Group by win pct desc; for each group resolve, taking from the top until we
    # have n_needed teams.
    pcts = {t: _pct(_current_record(t, games)) for t in non_winners}
    sorted_teams = sorted(non_winners, key=lambda t: pcts[t], reverse=True)

    chosen = []
    i = 0
    while i < len(sorted_teams) and len(chosen) < n_needed:
        j = i
        while j < len(sorted_teams) and pcts[sorted_teams[j]] == pcts[sorted_teams[i]]:
            j += 1
        group = sorted_teams[i:j]
        if len(group) == 1:
            chosen.extend(group)
        else:
            ranked = _rank_wildcard_group(group, games, favor)
            for t in ranked:
                if len(chosen) >= n_needed:
                    break
                chosen.append(t)
        i = j

    return chosen[:n_needed]


def _rank_wildcard_group(group, games, favor):
    """
    Resolve a tied wild-card group. NFL rule: when 2+ teams from same division
    are tied, first apply division tiebreakers to reduce them to one rep;
    then apply wild-card tiebreakers across the (now-distinct-division) reps;
    then iterate.
    """
    # Identify divisions present
    from collections import defaultdict
    by_div = defaultdict(list)
    for t in group:
        by_div[division_of(t)].append(t)

    # If any division has multiple tied teams, reduce them first using division tiebreakers
    representatives = []
    div_internal_orders = {}  # div -> [best, second, ...]
    for div_name, members in by_div.items():
        if len(members) == 1:
            representatives.append(members[0])
            div_internal_orders[div_name] = members
        else:
            ordered = _break_tie_division(members, games, favor)
            representatives.append(ordered[0])
            div_internal_orders[div_name] = ordered

    # Now sort representatives using wild-card tiebreakers
    rep_order = _break_tie_wildcard(representatives, games, favor)

    # Build final ordering: cycle through reps, but per NFL rule, once a rep is
    # picked, the next team from that division can re-enter the ranking pool.
    # For simplicity in our truncated model: pick the top rep, then if that
    # division has more tied teams, the next-best from that division is added
    # back to the pool. We approximate with a simpler version: produce reps in
    # order, then append remaining division members behind their rep.
    final = []
    for rep in rep_order:
        div_name = division_of(rep)
        for t in div_internal_orders[div_name]:
            if t not in final:
                final.append(t)
    return final


def compute_eliminations(games, year):
    """
    Return a dict {team_name: bool_eliminated} for all 32 teams at the current
    state of play (i.e., for the next unplayed regular-season game). Tie-aware.

    `games` is the full list of regular-season + postseason games for the
    season. Only regular-season played games inform records; unplayed
    regular-season games are the search space.
    """
    eliminated = {}
    for team in all_teams():
        alive = _alive_or_eliminated(team, games, year)
        eliminated[team] = not alive
    return eliminated


def _classify_teams(team_X, games):
    """
    Return dict {team -> 'lock_above' | 'lock_below' | 'borderline'} for each
    canonical team, given X's perspective. X wins out (best case) and we
    compare other teams' min/max possible wins to X_final.

    'lock_above': team's MIN possible wins > X_final → will finish above X
                  regardless of remaining outcomes.
    'lock_below': team's MAX possible wins < X_final → will finish below X.
    'borderline': otherwise.
    """
    team_X = canonical_name(team_X)
    # X's remaining regular-season games
    x_remaining = 0
    x_w, x_l, x_t = _current_record(team_X, games)
    for g in games:
        if not _is_regular_season(g) or _is_played(g):
            continue
        away = canonical_name(g['away_team'])
        home = canonical_name(g['home_team'])
        if team_X in (away, home):
            x_remaining += 1
    x_final = x_w + 0.5 * x_t + x_remaining  # win-points (ties = 0.5)

    result = {}
    for team in all_teams():
        if team == team_X:
            result[team] = 'self'
            continue
        w, l, t = _current_record(team, games)
        team_remaining = 0
        for g in games:
            if not _is_regular_season(g) or _is_played(g):
                continue
            away = canonical_name(g['away_team'])
            home = canonical_name(g['home_team'])
            if team in (away, home):
                team_remaining += 1
        team_min = w + 0.5 * t
        team_max = w + 0.5 * t + team_remaining
        if team_min > x_final:
            result[team] = 'lock_above'
        elif team_max < x_final:
            result[team] = 'lock_below'
        else:
            result[team] = 'borderline'
    return result


def _resolve_game(game, winner_team):
    """Mark a game as played with winner_team winning 1-0."""
    g = dict(game)
    away = canonical_name(game['away_team'])
    if winner_team == away:
        g['away_score'] = 1
        g['home_score'] = 0
    else:
        g['away_score'] = 0
        g['home_score'] = 1
    g['_synthesized'] = True
    return g


def _check_team_alive(team_X, games, year):
    """
    Determine if team_X has any remaining scenario that puts them in the
    playoffs. Strategy:
      1. Classify other conference teams into lock_above / lock_below /
         borderline given X's best case (X wins out).
      2. Build a base scenario by deterministically resolving every non-X
         unplayed game per these rules:
           - Both lock_above: alphabetical.
           - Both lock_below: alphabetical.
           - lock_above vs lock_below: lock_above wins.
           - borderline vs lock_above: lock_above wins (borderline loses; max drops).
           - borderline vs lock_below: lock_below wins (borderline loses; max drops).
           - borderline vs borderline: enumerable — try both outcomes.
      3. Enumerate the 2^N outcomes of borderline-vs-borderline games. For
         each, check if X is in their conference's playoff field.
      4. Alive iff any scenario succeeds.
    """
    team_X = canonical_name(team_X)
    conf_X = conference_of(team_X)
    classification = _classify_teams(team_X, games)

    # Identify the enumerable games: unplayed, neither team is X, both teams
    # are borderline. (Borderline implies in some conference; not necessarily
    # X's. Inter-conference borderline-borderline games don't affect X's
    # conference standings, so they're not enumerable — just deterministic.)
    enumerable = []
    base_assignments = []  # list of (game, winner_team)

    for g in games:
        if not _is_regular_season(g) or _is_played(g):
            continue
        away = canonical_name(g['away_team'])
        home = canonical_name(g['home_team'])
        if team_X in (away, home):
            base_assignments.append((g, team_X))
            continue
        cls_a = classification.get(away, 'lock_above')
        cls_h = classification.get(home, 'lock_above')

        # Inter-conference: doesn't affect X's conference standings count.
        # Just pick deterministically.
        in_conf_a = (conference_of(away) == conf_X)
        in_conf_h = (conference_of(home) == conf_X)

        if not (in_conf_a or in_conf_h):
            # Neither in X's conference: arbitrary
            base_assignments.append((g, sorted([away, home])[0]))
            continue

        if in_conf_a and not in_conf_h:
            # Conference team should lose (lower their record)
            base_assignments.append((g, home))
            continue
        if in_conf_h and not in_conf_a:
            base_assignments.append((g, away))
            continue

        # Both teams in X's conference. Use classification.
        if cls_a == 'borderline' and cls_h == 'borderline':
            enumerable.append((g, away, home))
            continue
        # If one is borderline and the other lock_below: borderline loses.
        if cls_a == 'borderline' and cls_h == 'lock_below':
            base_assignments.append((g, home))
            continue
        if cls_h == 'borderline' and cls_a == 'lock_below':
            base_assignments.append((g, away))
            continue
        # If one is borderline and the other lock_above: lock_above wins
        # (so the borderline doesn't gain a win).
        if cls_a == 'borderline' and cls_h == 'lock_above':
            base_assignments.append((g, home))
            continue
        if cls_h == 'borderline' and cls_a == 'lock_above':
            base_assignments.append((g, away))
            continue
        # Lock vs lock: arbitrary
        base_assignments.append((g, sorted([away, home])[0]))

    # Quick win-count elimination check.
    n_seeds = playoff_seeds_per_conference(year)
    conf_lock_above = sum(1 for t, c in classification.items()
                          if c == 'lock_above' and conference_of(t) == conf_X)
    if conf_lock_above >= n_seeds:
        return False
    # Quick "obviously alive" check: if conf lock_below count is large enough
    # that even the borderline teams (excluding X) total + lock_above < n_seeds,
    # X is alive without enumeration. We need at most (n_seeds - 1) other
    # conference teams to potentially finish at-or-above X.
    conf_borderline = sum(1 for t, c in classification.items()
                          if c == 'borderline' and conference_of(t) == conf_X)
    # Total conference teams that could finish at/above X = lock_above + borderline (excluding X self).
    # X self is 'self' so not counted. Need that total < n_seeds for guaranteed alive.
    if conf_lock_above + conf_borderline < n_seeds:
        return True

    # Cap on enumeration: if too many borderline-borderline games, fall back
    # to a heuristic (skip enumeration, just try the "all borderline lose
    # except the loser of each pair" approach via alphabetical).
    MAX_ENUMERATE = 14  # 2^14 ~ 16k scenarios; balances accuracy vs speed

    # Pre-build the base scenario once (with placeholder winners for enumerable
    # games) — we mutate the enumerable games' scores per scenario.
    base_winner_for_id = {id(g): w for g, w in base_assignments}
    # Precompute the immutable scenario skeleton — list of resolved game dicts
    # for played + base-assigned games. Enumerable games are slots we mutate.
    scenario_skeleton = []
    enumerable_index = []  # index in scenario_skeleton of each enumerable slot
    for orig_g in games:
        if not _is_regular_season(orig_g):
            scenario_skeleton.append(dict(orig_g))
            continue
        if _is_played(orig_g):
            scenario_skeleton.append(dict(orig_g))
            continue
        if id(orig_g) in base_winner_for_id:
            winner = base_winner_for_id[id(orig_g)]
            scenario_skeleton.append(_resolve_game(orig_g, winner))
        else:
            # Enumerable: placeholder, mutated per scenario
            scenario_skeleton.append(_resolve_game(orig_g,
                                                  canonical_name(orig_g['away_team'])))
            enumerable_index.append(len(scenario_skeleton) - 1)

    # Map enumerable slot -> (away_canon, home_canon) for fast mutation
    enumerable_meta = []
    for g, a, h in enumerable:
        enumerable_meta.append((a, h))

    def evaluate(mask):
        """Mutate enumerable slots in-place to reflect the mask, then check X."""
        for i, idx in enumerate(enumerable_index):
            a, h = enumerable_meta[i]
            winner = a if (mask >> i) & 1 else h
            slot = scenario_skeleton[idx]
            if winner == a:
                slot['away_score'] = 1
                slot['home_score'] = 0
            else:
                slot['away_score'] = 0
                slot['home_score'] = 1
        playoff_teams = _conference_playoff_teams(conf_X, scenario_skeleton, year, favor=team_X)
        return team_X in playoff_teams

    if len(enumerable) > MAX_ENUMERATE:
        # Too many to enumerate. Try heuristic masks.
        current_wins = {t: _current_record(t, games)[0] for t in all_teams()}
        # Heuristic 1: lower-current-wins wins (bit=1 means away wins)
        mask_h1 = 0
        for i, (a, h) in enumerate(enumerable_meta):
            if current_wins[a] <= current_wins[h]:
                mask_h1 |= (1 << i)
        if evaluate(mask_h1):
            return True
        # Heuristic 2: higher-current-wins wins
        mask_h2 = 0
        for i, (a, h) in enumerate(enumerable_meta):
            if current_wins[a] >= current_wins[h]:
                mask_h2 |= (1 << i)
        if evaluate(mask_h2):
            return True
        return False

    # Enumerate all 2^N outcomes
    n = len(enumerable)
    for mask in range(1 << n):
        if evaluate(mask):
            return True
    return False


def _alive_or_eliminated(team_X, games, year):
    """Return True if alive, False if eliminated."""
    return _check_team_alive(team_X, games, year)
