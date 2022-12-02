#
# nfl-game-dates.py
#
# Core functions for retrieving game dates and times from pro-football-reference.com
#
# The main function is load_game_times(year,week), which returns the list of game teams
# and start times for every game that week.  Though I haven't tested every combination, it
# attempts to handle different season lengths and the addition of the wild card week. 
#
# Pulls data from pro-football-reference.com.
#

#%% Imports and constants

import re
import requests
import klembord

from dateutil import parser as dateparser
from datetime import timedelta
from bs4 import BeautifulSoup

base_url = 'https://www.pro-football-reference.com'
gamepass_base_url = 'https://nfl.com/plus/games/'

playoff_round_names = ['wildcard','divisional','championship','superbowl']
klembord.init()


#%% Classes

class GameInfo:
    def __init__(self,teamAway,teamHome,start_time):
        self.teamAway = teamAway
        self.teamHome = teamHome
        self.start_time = start_time
    
    def __str__(self):
        return '{} at {}, {}'.format(self.teamAway,self.teamHome,self.start_time)
    
    def __repr__(self):
        return '{} at {}, {}'.format(self.teamAway,self.teamHome,self.start_time)
        
        
#%% Functions
    
def get_number_of_weeks_in_season(year):
    """
    Return the number of weeks in any regular season >= 1961
    """    
    # See https://en.wikipedia.org/wiki/NFL_regular_season
    assert isinstance(year,int)
    assert year >= 1961
    if year <= 1977:
        if year == 1966:
            return 15
        else:
            return 14
    elif year <= 1989:
        if year == 1982:
            return 17
        # Technically unnecessary, but this season actually had fewer games than
        # other seasons, and we may need to factor that in later, so this is a reminder
        # that it's different than, e.g., 1988
        elif year == 1987:
            return 16
        else:
            return 16
    elif year <= 2020:
        if year == 1993 or year == 2001:
            return 18
        else:
            return 17
    else:
        assert year >= 2021
        return 18


def normalize_string(s):
    """
    Lowercase and remove whitespace from *s*
    """
    assert isinstance(s,str)
    return s.lower().strip().replace(' ','')


def playoff_round_to_offset(round_name,year):
    """
    Given a playoff round name from playoff_round_names, return the number of games
    after the end of the regular season that this round took place.  E.g. for 2010,
    "wildcard" is 1 week after the end of the regular season
    """
    
    round_name = normalize_string(round_name)
    assert round_name in playoff_round_names
    if year < 1978:
        assert round_name != 'wildcard', "The Wild Card round didn't start until 1978"
        round_mapping = {'divisional':1,'championship':2,'superbowl':3}        
    else:
        round_mapping = {'wildcard':1,'divisional':2,'championship':3,'superbowl':4}
    return round_mapping[round_name]
                         
    
def is_super_bowl(week,year):
    assert isinstance(week,int) and isinstance(year,int)
    return week == get_number_of_weeks_in_season(year) + playoff_round_to_offset('superbowl',year)
        

def load_game_times_from_url(url,week,year):
    """
    See load_game_times() for return values
    """
    
    assert isinstance(week,int)
    assert isinstance(year,int)
    
    s = requests.Session() 
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36'}
    html_text = s.get(url, headers=headers).text
    if 'access denied' in html_text.lower():
        raise ValueError('Access denied')
    week_soup = BeautifulSoup(html_text,'html.parser')
    game_tables = week_soup.find_all('table', {'class':'teams'})
    
    if len(game_tables) == 0:
        # Corner case: for some years, the super bowl is inexplicably considered
        # a third game in the championship round.
        if is_super_bowl(week,year):
            print('Warning: no games found for {} week {}, reverting to week {}'.format(
                year,week,week-1))
            url = url.replace(str(week),str(week-1))
            games = load_game_times_from_url(url,week,year)
            return [games[-1]]
        else:
            raise ValueError('Could not parse any games from {}'.format(url))
    
    # This is what a game table looks like:
    """
    	<table class="teams">
		<tbody>
		<tr class="date"><td colspan=3>Sep 8, 2011</td></tr>		       
		<tr class="loser">
			<td><a href="/teams/nor/2011.htm">New Orleans Saints</a></td>
			<td class="right">34</td>
			<td class="right gamelink">
				<a href="/boxscores/201109080gnb.htm">F<span class="no_mobile">inal</span></a>
				
			</td>
		</tr>
		<tr class="winner">
			<td><a href="/teams/gnb/2011.htm">Green Bay Packers</a></td>
			<td class="right">42</td>
			<td class="right">&nbsp;
			</td>
		</tr>
		</tbody>
	</table>
    """
        
    games = []
    
    # game_table = game_tables[0]
    for i_game,game_table in enumerate(game_tables):
        
        game_links = game_table.find_all('a')
        boxscore_links = [s for s in game_links if 'boxscores' in str(s)]
        assert len(boxscore_links) == 1
        boxscore_link = boxscore_links[0]
        relative_path = boxscore_link['href']
        boxscore_url = base_url + relative_path
        
        html_text = requests.get(boxscore_url).text
        game_soup = BeautifulSoup(html_text,'html.parser')
        
        # E.g.:
        #
        # Regular season:
        #
        # New Orleans Saints at Green Bay Packers - September 8th, 2011 | Pro-Football-Reference.com
        #
        # Playoff:
        #
        # Wild Card - Atlanta Falcons at Arizona Cardinals - January 3rd, 2009 | Pro-Football-Reference.com
        #
        # Starting in 2021:
        # 
        # Dallas Cowboys  at  Tampa Bay Buccaneers - September 9th, 2021 - Raymond James Stadium | Pro-Football-Reference.com
        # Cleveland Browns  at  Kansas City Chiefs - September 12th, 2021 - GEHA Field at Arrowhead Stadium | Pro-Football-Reference.com
        
        title_raw = game_soup.title.getText()
        
        # Super Bowls use 'vs.', all other games use 'at' (maybe London games use 'vs.'?)
        assert ' at ' in title_raw or ' vs. ' in title_raw
        team_tokens = re.split(r' at | vs. ',title_raw,maxsplit=1)
        assert len(team_tokens) == 2
        teamAway = team_tokens[0].strip()
        if ' - ' in teamAway:
            teamAway = teamAway.split(' - ')[1].strip()
        teamHome = team_tokens[1].strip()
        if ' - ' in teamHome:
            teamHome = teamHome.split(' - ')[0].strip()
        
        # The scorebox looks like this:
        """
        <div class="scorebox_meta">
		<div>Thursday Sep 8, 2011</div><div><strong>Start Time</strong>: 8:40pm</div><div><strong>Stadium</strong>: <a href="/stadiums/GNB00.htm">Lambeau Field</a> </div><div><strong>Attendance</strong>: <a href="/years/2011/attendance.htm">70,555</a></div><div><strong>Time of Game</strong>: 3:09</div>
		<div><em>Logos <a href="http://www.sportslogos.net/">via Sports Logos.net</a>
            / <a href="//www.sports-reference.com/blog/2016/06/redesign-team-and-league-logos-courtesy-sportslogos-net/">About logos</a></em></div>
        <div>
        """
        scoreboxes = game_soup.find_all('div',{'class':'scorebox_meta'})
        assert len(scoreboxes) == 1
        scorebox = scoreboxes[0]
        scorebox_divs = scorebox.find_all('div')
        date_text = scorebox_divs[0].getText().strip()
        time_text = scorebox_divs[1].getText()
        assert time_text.startswith('Start Time')
        time_text = time_text.split(':',1)[1].strip()
        
        datetime_text = date_text + ' ' + time_text
        
        # Now we have, e.g.:
        #
        # Thursday Sep 8, 2011 8:40pm
        #        
        # I'm *almost* positive it's returning games in browser-local time        
        game_start_time = dateparser.parse(datetime_text)
        
        game = GameInfo(teamAway,teamHome,game_start_time)
        games.append(game)
    
    # ...for each game
    
    # Sort games
    sorted_games = sorted(games, key=lambda x: x.start_time)
    
    return sorted_games
    

def week_to_numeric(year,week):
    
    if isinstance(year,str):
        year = int(year)
    assert isinstance(year,int)
    assert year >= 1966 and year <= 2050
    
    if isinstance(week,str):
        try:
            week = int(normalize_string(week))
        except:
            pass
        
    if isinstance(week,str):
        round_name = normalize_string(week)
        assert round_name in playoff_round_names,'Unrecognized week name {}'.format(round_name)
        number_of_regular_season_weeks = get_number_of_weeks_in_season(year)
        playoff_offset = playoff_round_to_offset(round_name,year)
        week = number_of_regular_season_weeks + playoff_offset
        
    # One way or another, *week* is an integer now
    assert isinstance(week,int)
    
    return year,week


def load_game_times(year,week):
    """
    Load all games from the specified week, return as a list of Game objects.
    
    Year refers to the year of week 1, i.e. the 2012 Super Bowl took place in 2013.
    
    Week can be a 1-indexed integer from 1 to 22 (19, 21, or 22 would be the Super Bowl, depending
    on the year), or it can be a string from playoff_game_names.
    
    Only seasons >= 1961 are supported.
    """
    
    year,week = week_to_numeric(year,week)
    
    url = base_url + '/years/' + str(year) + '/week_' + str(week) + '.htm'
    # os.startfile(url) 
    
    return load_game_times_from_url(url,week,year)


def team_name_from_team_string(team_string):
    
    # Converts "Dallas Cowboys" to "Cowboys"
    team_name_tokens = team_string.split(' ')
    if 'football team' in team_string.lower():
        team_name = 'Football Team'
    else:
        team_name = team_name_tokens[-1]
    
    return team_name

    
#%%
    
def game_list_to_html(games,week,year):    

    output_html = '<html><body>\n'
    
    year,week = week_to_numeric(year,week)
    is_postseason = (week > get_number_of_weeks_in_season(year))
    
    if is_postseason:
        
        season_portion = 'post'
        
        # The first week of the postseason is written as post-1, not, e.g., post-19
        week = week - get_number_of_weeks_in_season(year) 
        
    else:
        
        season_portion = 'reg'
        
    # Sample game URL:
    #
    # https://www.nfl.com/games/titans-at-seahawks-2021-reg-2
    previous_game_time = None
    
    # s = games[0]
    for s in games:
        
        # E.g. New Orleans Saints at Green Bay Packers, 2011-09-08 20:40:00'
        game_str = str(s)
        tokens = game_str.split(',')
        assert len(tokens) == 2
        teams_string = tokens[0]
        assert ' at ' in teams_string
        date_string = tokens[1]
        game_start_time = dateparser.parse(date_string)
        
        start_new_line = (previous_game_time is not None) and \
            (game_start_time - previous_game_time > timedelta(hours=1))
        
        if start_new_line:
            output_html += '\n<br/>\n\n'
        
        previous_game_time = game_start_time
        
        # E.g. New Orleans Saints at Green Bay Packers
        team_tokens = teams_string.split(' at ')
        assert len(team_tokens) == 2
        visiting_team = team_name_from_team_string(team_tokens[0]).lower().replace(' ','-')
        home_team = team_name_from_team_string(team_tokens[1]).lower().replace(' ','-')
        
        assert gamepass_base_url.endswith('/')
        gamepass_url = gamepass_base_url + visiting_team + '-at-' + home_team + '-' + \
            str(year) + '-' + season_portion + '-' + str(week)
        
        # print(gamepass_url)          
        output_html += '<p><a href="{}">{}</a></p>\n'.format(
            gamepass_url,game_str)

    # ...for each game
    
    output_html += '</body></html>'
    
    return output_html

# ...def game_list_to_html()

    
#%% Test driver

if False:

    #%%
    
    # https://www.pro-football-reference.com/years/2011/week_1.htm
    year = 2011
    week = 1        
    games = load_game_times(year,week)
    for s in games:
        print(s)
    
    #%%
    
    year = '2008'
    week = 'wild card'
    games = load_game_times(year,week)
    for s in games:
        print(s)
        
    #%%
    
    year = '1991'
    week = 'sUpeR      boWL'
    games = load_game_times(year,week)
    for s in games:
        print(s)
        
    #%%
    
    year = 2002
    week = 'super bowl'
    games = load_game_times(year,week)
    for s in games:
        print(s)
        
    #%%
    
    year = 2022
    week = 12
    games = load_game_times(year,week)
    for s in games:
        print(s)
    html = game_list_to_html(games,week,year)
    print(html)
    klembord.set_with_rich_text('',html)
    
    
#%% Command-line driver

import argparse
import sys

def main():
    
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'year',
        help='Year of the season start (i.e., year of week 1, not the calendar year of the game)')
    parser.add_argument(
        'week',
        help='Week to fetch, either a number (1-22) or a playoff week name (wild card, divisional, championship, super bowl)'
        )
    parser.add_argument(
        '--html',
        help='Output HTML with links to NFL Game Pass, instead of plain text',
        action='store_true')
    parser.add_argument(
        '--copy',
        help='Copy output text to the clipboard',
        action='store_true')
        
    if len(sys.argv[1:]) == 0:
        parser.print_help()
        parser.exit()

    args = parser.parse_args()
    games = load_game_times(args.year,args.week)
    
    if args.html:
        s = game_list_to_html(games,args.week,args.year)
        print(s)
    else:
        s = '\n'.join([str(g) for g in games])
        print(s)
        
    if args.copy:
        klembord.set_with_rich_text(s,s)

if __name__ == '__main__':
    main()
