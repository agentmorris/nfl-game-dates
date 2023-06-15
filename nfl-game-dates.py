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

import os
import re
import requests
import klembord
import time
import pickle
import copy

from dateutil import parser as dateparser
from datetime import timedelta
from bs4 import BeautifulSoup

base_url = 'https://www.pro-football-reference.com'
gamepass_base_url = 'https://nfl.com/plus/games/'

playoff_round_names = ['wildcard','divisional','championship','superbowl']
playoff_round_names_long = ['wild card','divisisional','championship','super bowl']
klembord.init()

# Will sleep this many seconds after every request for either a whole page or an
# individual box score.
sleep_after_request_time = 0


#%% Classes

class GameInfo:

    def __init__(self,team_away,team_home,start_time,away_scores,home_scores,away_record,home_record):
        self.team_away = team_away
        self.team_home = team_home
        self.start_time = start_time
        self.away_scores = away_scores
        self.home_scores = home_scores
        
        self.boxscore_url = ''
        self.boxscore_html = ''
                
    def __str__(self):
        return '{} at {}, {}'.format(self.team_away,self.team_home,self.start_time)
    
    def __repr__(self):
        return '{} at {}, {}'.format(self.team_away,self.team_home,self.start_time)
        
        
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


def week_to_numeric(year,week):
    """
    Convert a week string (which might be "1" (int or str) or "19" (postseason) or "wild card") 
    to a 1-indexed week number.
    """
    
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


def week_index_to_name(week,year):
    """
    Given a zero-indexed week number, return a string name for that week, e.g.
    "week 12" or "divsionional round"
    """
    
    assert year >= 1966 and year <= 2050
    
    n_regular_season_weeks = get_number_of_weeks_in_season(year)
    if week < n_regular_season_weeks:
        return 'week {}'.format(week+1)
    else:
        playoff_round_index = week - n_regular_season_weeks
        if year < 1978:
            round_mapping = {0:'divisional',1:'championship',2:'super bowl'}        
        else:
            round_mapping = {0:'wild card',1:'divisional',2:'championship',3:'super bowl'}        
        return round_mapping[playoff_round_index]


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
        

def parse_game_from_boxscore_html(boxscore_html):
    
    game_soup = BeautifulSoup(boxscore_html,'html.parser')
    
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
    assert ' at ' in title_raw or ' vs. ' in title_raw, 'Could not parse title: {}'.format(title_raw)
    team_tokens = re.split(r' at | vs. ',title_raw,maxsplit=1)
    assert len(team_tokens) == 2
    team_away = team_tokens[0].strip()
    if ' - ' in team_away:
        team_away = team_away.split(' - ')[1].strip()
    team_home = team_tokens[1].strip()
    if ' - ' in team_home:
        team_home = team_home.split(' - ')[0].strip()
    
    # Get records *after* this game
    scorebox = game_soup.find_all('div','scorebox')
    assert len(scorebox) == 1
    scorebox = scorebox[0]
    score_divs = scorebox.find_all('div','score')
    assert len(score_divs) == 2
    away_final_score = int(score_divs[0].text)
    home_final_score = int(score_divs[1].text)
            
    scorebox_inner_divs = scorebox.find_all('div')
    team_record_strings = []
    for div in scorebox_inner_divs:
        if len(div.text) < 10 and '-' in div.text:
            team_record_strings.append(div.text)
    assert len(team_record_strings) == 2
    away_record = team_record_strings[0]
    home_record = team_record_strings[1]
            
    # Get scores
    linescores = game_soup.find_all('table','linescore')
    assert len(linescores) == 1
    linescore_table = linescores[0]
    linescore_table_body = linescore_table.find('tbody')
    linescore_table_rows = linescore_table_body.find_all('tr')
    
    assert len(linescore_table_rows) == 2
    
    home_scores = None
    away_scores = None
    
    for i_row,row in enumerate(linescore_table_rows):
        cols = row.find_all('td')
        
        # This depends on whether the game went into OT
        # 
        # 7 cols == logo,name,q1,q2,q3,q4,final
        # 8 cols == logo,name,q1,q2,q3,q4,ot,final
        # 9 cols == logo,name,q1,q2,q3,q4,ot,ot2,final
        assert len(cols) >= 7
        
        # team_logo_col = cols[0]
        team_name_col = str(cols[1])
        if i_row == 0:
            assert team_away in team_name_col
        else:
            assert team_home in team_name_col
        
        # Team score by quarter, then overtime, then final
        #
        # In the (rare) case of a 2OT game, column 4 will be a comma-separated string.
        team_scores = [0] * 6            
        team_scores[0] = int(cols[2].text)
        team_scores[1] = int(cols[3].text)            
        team_scores[2] = int(cols[4].text)            
        team_scores[3] = int(cols[5].text)
        
        # If there was no overtime
        if len(cols) == 7:        
            team_scores[4] = 0
            team_scores[5] = int(cols[6].text)
        else:
            assert len(cols) == 8 or len(cols) == 9
            if len(cols) == 8:
                team_scores[4] = int(cols[6].text)
                team_scores[5] = int(cols[7].text)
            else:
                assert len(cols) == 9
                team_scores[4] = cols[6].text.strip() + ',' + cols[7].text
                team_scores[5] = int(cols[8].text)
                    
        if i_row == 0:
            away_scores = team_scores
        else:
            home_scores = team_scores
    
    # ...for each row in the two-row scoring table
    
    if away_final_score != away_scores[-1]:
        assert away_final_score == home_scores[-1]
        print('Warning: game {} has the home/away scores reversed'.format(title_raw))        
    if home_final_score != home_scores[-1]:
        assert home_final_score == away_scores[-1]
        print('Warning: game {} has the away/home scores reversed'.format(title_raw))        
    
    # Get date/time
    # The scorebox meta information looks like this:
    """
    <div class="scorebox_meta">
iv>Thursday Sep 8, 2011</div><div><strong>Start Time</strong>: 8:40pm</div><div><strong>Stadium</strong>: <a href="/stadiums/GNB00.htm">Lambeau Field</a> </div><div><strong>Attendance</strong>: <a href="/years/2011/attendance.htm">70,555</a></div><div><strong>Time of Game</strong>: 3:09</div>
iv><em>Logos <a href="http://www.sportslogos.net/">via Sports Logos.net</a>
        / <a href="//www.sports-reference.com/blog/2016/06/redesign-team-and-league-logos-courtesy-sportslogos-net/">About logos</a></em></div>
    <div>
    """
    scorebox_meta = game_soup.find_all('div',{'class':'scorebox_meta'})
    assert len(scorebox_meta) == 1
    scorebox_meta = scorebox_meta[0]
    scorebox_meta_divs = scorebox_meta.find_all('div')
    date_text = scorebox_meta_divs[0].getText().strip()
    time_text = scorebox_meta_divs[1].getText()
    assert time_text.startswith('Start Time')
    time_text = time_text.split(':',1)[1].strip()        
    datetime_text = date_text + ' ' + time_text
    
    # Now we have, e.g.:
    #
    # Thursday Sep 8, 2011 8:40pm
    #        
    # I'm *almost* positive it's returning games in browser-local time        
    game_start_time = dateparser.parse(datetime_text)
    
    game = GameInfo(team_away,team_home,game_start_time,
                    away_scores,home_scores,away_record,home_record)
    game.boxscore_html = boxscore_html
    
    return game
    
    
def load_game_times_from_url(url,week,year):
    """
    Load game times from a single-week URL, e.g.:
        
    https://www.pro-football-reference.com/years/2009/week_1.htm
    
    Will initiate multiple http requests, one per box score.
    
    See load_game_times() for return values.
    """
    
    assert isinstance(week,int)
    assert isinstance(year,int)
    
    s = requests.Session() 
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36'}
    html_text = s.get(url, headers=headers).text    
    time.sleep(sleep_after_request_time)
    
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
    
    # i_game = 0; game_table = game_tables[i_game]
    for i_game,game_table in enumerate(game_tables):
        
        game_links = game_table.find_all('a')
        boxscore_links = [s for s in game_links if 'boxscores' in str(s)]
        assert len(boxscore_links) == 1
        boxscore_link = boxscore_links[0]
        relative_path = boxscore_link['href']
        
        # E.g.: https://www.pro-football-reference.com/boxscores/200909100pit.htm
        boxscore_url = base_url + relative_path
        
        boxscore_html = requests.get(boxscore_url).text
        time.sleep(sleep_after_request_time)
        
        game = parse_game_from_boxscore_html(boxscore_html)
        game.boxscore_url = boxscore_url        
        games.append(game)
    
    # ...for each game
    
    # Sort games
    sorted_games = sorted(games, key=lambda x: x.start_time)
    
    return sorted_games
    

def load_game_times(year,week):
    """
    Load all games from the specified week, return as a list of Game objects.
    
    Year refers to the year of week 1, i.e. the 2012 Super Bowl took place in 2013.
    
    Week can be a 1-indexed integer from 1 to 22 (19, 21, or 22 would be the Super Bowl, depending
    on the year), or it can be a string from playoff_game_names.
    
    Only seasons >= 1961 are supported.
    
    Processes a single URL per call, e.g.:
        
    https://www.pro-football-reference.com/years/2009/week_1.htm
    """
    
    year,week = week_to_numeric(year,week)
    
    url = base_url + '/years/' + str(year) + '/week_' + str(week) + '.htm'
    # os.startfile(url) 
    
    return load_game_times_from_url(url,week,year)


def team_name_from_team_string(team_string):
    """
    Converts, e.g., "Dallas Cowboys" to "Cowboys".
    """
    
    team_name_tokens = team_string.split(' ')
    if 'football team' in team_string.lower():
        team_name = 'Football Team'
    else:
        team_name = team_name_tokens[-1]
    
    return team_name

    
def game_list_to_html(games,week,year,output_format='html',
                      include_quality_info=False,
                      team_records=None,
                      include_gamepass_links=False):
    """
    Given a list of games (created by load_game_times()), generate the nice HTML content
    we did all this work for.
    """
    assert output_format in ['html','markdown']
    
    output_html = ''
    
    p_open = ''
    p_close = '\n'
    
    if output_format == 'html':
        output_html += '<html><body>\n'
        p_open -= '<p>'
        p_close = '</p>'
    
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
    
    # game = games[0]
    for game in games:

        away_record_string = ''
        home_record_string = ''
        
        if team_records is not None:
            away_record = team_records[game.team_away]
            home_record = team_records[game.team_home]
            away_record_string = ' ({}-{}'.format(away_record['wins'],away_record['losses'])
            if away_record['ties'] > 0:
                away_record_string += '-{}'.format(away_record['ties'])
            home_record_string = ' ({}-{}'.format(home_record['wins'],home_record['losses'])
            if home_record['ties'] > 0:
                home_record_string += '-{}'.format(home_record['ties'])
            away_record_string += ')'
            home_record_string += ')'
                
        zero_padding_specifier = '#'        
        if os.name != 'nt':
            zero_padding_specifier = '-'
            
        quality_string = ''
        
        if include_quality_info:
            if ('game_tags' not in game.__dict__.keys()) or \
                (len(game.game_tags) == 0):
                quality_string = ''
            else:
                assert len(game.game_tags) == 1
                if 'bad' in game.game_tags:
                    
                    quality_string = \
                        ' (	:red_circle: bad game)'
                    #     ' ![bad game](https://img.shields.io/badge/-bad_game-aa4444)'
                        
                else:
                    assert 'good' in game.game_tags
                    quality_string = \
                        ' (	:green_circle: good game)'
                    #    ' ![good game](https://img.shields.io/badge/-good_game-44aa44)'
                        
            
        game_str = '{}{} at {}{}, {}{}'.format(
            game.team_away,away_record_string,
            game.team_home,home_record_string,
            game.start_time.strftime('%A, %b %{}d, %{}I:%M %p'.format(
                zero_padding_specifier,zero_padding_specifier)),
            quality_string)
                
        start_new_line = (previous_game_time is not None) and \
            (game.start_time - previous_game_time > timedelta(hours=1))
        
        if start_new_line:
            output_html += '<br/>'        
        
        previous_game_time = game.start_time
        
        # E.g. New Orleans Saints at Green Bay Packers
        visiting_team = game.team_away
        home_team = game.team_home
        
        assert gamepass_base_url.endswith('/')
        gamepass_url = gamepass_base_url + visiting_team + '-at-' + home_team + '-' + \
            str(year) + '-' + season_portion + '-' + str(week)
        
        if include_gamepass_links:
            output_html += '{}<a href="{}">{}</a>{}\n'.format(
                p_open,gamepass_url,game_str,p_close)
        else:
            output_html += '{}{}{}\n'.format(p_open,game_str,p_close)

    # ...for each game
    
    if output_format == 'html':
        output_html += '</body></html>'
    
    return output_html

# ...def game_list_to_html()


#%% Interactive driver

if False:
    
    pass

    #%% Estimate total time
    
    import humanfriendly
    time_per_game = 15
    games_per_week = 15    
    weeks_per_year = 18
    n_years = 14
    humanfriendly.format_timespan(time_per_game*games_per_week*weeks_per_year*n_years)
    
    
    #%% Get a list of all games for every year since 2009

    from md_utils import path_utils
    data_folder = r'g:\temp\nfl-game-ranks'
    
    def back_up_game_data(year_to_games):

        output_filename = os.path.join(data_folder,'nfl-game-data.pickle')
        output_filename = path_utils.insert_before_extension(output_filename)
        
        with open(output_filename,'wb') as f:
            pickle.dump(year_to_games,f)

    sleep_after_request_time = 10
    initial_sleep_time = 0 # 60*30
    n_playoff_rounds = 4
    
    min_year = 2009
    max_year = 2022
    
    from collections import defaultdict
    from tqdm import tqdm
    
    year_to_games = defaultdict(list)
    
    if initial_sleep_time > 0:
        print('Starting initial sleep')
        time.sleep(initial_sleep_time)
        
    for year in tqdm(range(min_year,max_year+1),total=(max_year-min_year)+1):
        
        print('Retrieving game times for {}'.format(year))
        n_weeks = get_number_of_weeks_in_season(year) + n_playoff_rounds
        
        for i_week in range(1,n_weeks+1):

            games = load_game_times(year,i_week)
            year_to_games[year].append(games)            
            
        # ...for each week
        
        back_up_game_data(year_to_games)
    
    # ...for each year
    
    
    #%% Restore data from a folder full of backups
    
    data_folder = r'g:\temp\nfl-game-ranks'
    
    pickled_files = os.listdir(data_folder)
    pickled_files = [fn for fn in pickled_files if fn.endswith('.pickle')]
    pickled_files = [os.path.join(data_folder,fn) for fn in pickled_files]
    
    year_to_games = {}
    
    for fn in pickled_files:        
        with open(fn,'rb') as f:
            d = pickle.load(f)
            years = list(d.keys())
            print('File {} contains games from {} to {}'.format(
                os.path.basename(fn),min(years),max(years)))
            for year in years:
                year_to_games[year] = d[year]
                
    
    #%% Restore data from the one and only backup file
    
    fn = r"G:\temp\nfl-game-ranks\nfl-game-data.2023.06.15.06.18.01.pickle"
    with open(fn,'rb') as f:
        year_to_games = pickle.load(f)
        
    
    #%% Test html parsing from stored games
    
    years = sorted(list(year_to_games.keys()))
    
    # year = years[0]
    for year in years:
        
        weeks = year_to_games[year]
        
        # i_week = 0
        for i_week in range(0,len(weeks)):
            
            games = weeks[i_week]
            
            for i_game in range(0,len(games)):
                
                game = games[i_game]
                game_reparsed = parse_game_from_boxscore_html(games[i_game].boxscore_html)
                
                assert game.home_scores == game_reparsed.home_scores
                assert game.away_scores == game_reparsed.away_scores
                assert game.team_away == game_reparsed.team_away
                assert game.team_home == game_reparsed.team_home
                assert game.start_time == game_reparsed.start_time
                
            # ...for each game
            
        # ...for each week
        
    # ...for each year
    
    print('Finished validating game parsing')
    
    
    #%% Generate markdown for every week
    
    output_folder = r'C:\git\nfl-game-dates\docs'
    years = sorted(list(year_to_games.keys()))
    
    markdown_folder = output_folder # os.path.join(output_folder,'games')
    os.makedirs(markdown_folder,exist_ok=True)
        
    header_file = os.path.join(output_folder,'../header.txt')    
    with open(header_file,'r') as f:
        header_lines = f.readlines()
        
    main_s = ''.join(header_lines) + '\n'
    
    for year in years:
        main_s += '* [{}](season_{}.md)\n'.format(year,year)
                
    trailer_file = os.path.join(output_folder,'../trailer.txt')    
    with open(trailer_file,'r') as f:
        trailer_lines = f.readlines()
    main_s += '\n' + ''.join(trailer_lines) + '\n'
    
    main_file = os.path.join(markdown_folder,'README.md')
    with open(main_file,'w') as f:
        f.write(main_s)        
    
    
    # year = years[0]
    for year in years:
                        
        weeks = year_to_games[year]
        n_regular_season_weeks = get_number_of_weeks_in_season(year)
        assert n_regular_season_weeks == len(weeks) - 4
        
        # Parse team names
        team_names = set()
        for week in weeks:
            for game in week:
                team_names.add(game.team_home)
                team_names.add(game.team_away)
        assert len(team_names) == 32
        
        # Parse team records, also mark games as good and bad
        
        # Each element will be a dicts, mapping the team name to their record *before* that week
        team_to_record_so_far = {}
        for team_name in team_names:        
            team_to_record_so_far[team_name] = {'wins':0,'losses':0,'ties':0}                        
        
        team_records_by_week = [copy.deepcopy(team_to_record_so_far)]
        
        # i_week = 0
        for i_week in range(0,n_regular_season_weeks):
            
            games = weeks[i_week]
            
            # i_game = 0
            for i_game in range(0,len(games)):
                
                game = games[i_game]
                
                # Update records
                home_final_score = game.home_scores[-1]
                away_final_score = game.away_scores[-1]
                
                if home_final_score > away_final_score:
                    result = 'home_win'
                elif home_final_score < away_final_score:
                    result = 'away_win'
                else:
                    result = 'tie'
                    
                if result == 'home_win':
                    team_to_record_so_far[game.team_home]['wins'] = \
                        team_to_record_so_far[game.team_home]['wins'] + 1
                    team_to_record_so_far[game.team_away]['losses'] = \
                        team_to_record_so_far[game.team_away]['losses'] + 1
                elif result == 'away_win':
                    team_to_record_so_far[game.team_away]['wins'] = \
                        team_to_record_so_far[game.team_away]['wins'] + 1
                    team_to_record_so_far[game.team_home]['losses'] = \
                        team_to_record_so_far[game.team_home]['losses'] + 1
                else:
                    team_to_record_so_far[game.team_away]['ties'] = \
                        team_to_record_so_far[game.team_away]['ties'] + 1
                    team_to_record_so_far[game.team_home]['ties'] = \
                        team_to_record_so_far[game.team_home]['ties'] + 1
                              
                # Update good/bad tags
                
                game.game_tags = set()
            
                home_halftime_score = game.home_scores[0] + game.home_scores[1]
                away_halftime_score = game.away_scores[0] + game.away_scores[1]
                
                halftime_result = None
                if home_halftime_score > away_halftime_score:
                    halftime_result = 'home_win'
                elif home_halftime_score < away_halftime_score:
                    halftime_result = 'away_win'
                else:
                    halftime_result = 'tie'
                                
                final_score_differential = abs(home_final_score - away_final_score)
                
                # Bad games are blowouts where the halftime leader was the final winner
                if (final_score_differential > 16) and \
                    (result == halftime_result):
                        game.game_tags.add('bad')
                    
                second_half_comeback = False
                if (halftime_result != 'tie') and \
                    (halftime_result != result):
                        second_half_comeback = True
                
                total_points = home_final_score + away_final_score
                
                # Good games are:
                #                    
                # The game finished as a one-score game, or...
                # The winning team was losing at halftime...
                # It was a two-score game with an absurd amount of scoring
                if (final_score_differential <= 8) or \
                    (second_half_comeback) or \
                    ((final_score_differential <= 16) and (total_points > 60)):
                    
                    game.game_tags.add('good')
                
                assert len(game.game_tags) <= 1
                
            # ...for each game
            
            # Update team records by week
            team_records_by_week.append(copy.deepcopy(team_to_record_so_far))
                    
        # ...for each week
        
        # Make sure records add up to the number of weeks in the season (plus one bye)
        for team_name in team_names:
            record = team_to_record_so_far[team_name]
            if year == 2022 and (team_name == 'Buffalo Bills' or team_name == 'Cincinnati Bengals'):
                pass
            else:
                assert record['wins'] + record['losses'] + record['ties'] == n_regular_season_weeks - 1
            
            
        no_quality_links = []
        with_quality_links = []
        
        output_format='markdown'
        
        # i_week = 0
        for i_week in range(0,len(weeks)):
            
            games = weeks[i_week]
            
            team_records = None
            if i_week < n_regular_season_weeks:
                team_records = team_records_by_week[i_week]
                
            md_header = '---\n'
            md_header += 'title: NFL simulated-real-time schedules, 2009-present\n'
            md_header += 'description: " "\n'
            md_header += '---\n\n'
            
            md_header += '# Game info for {} {}\n\n'.format(year,week_index_to_name(i_week,year))
            
            md_no_quality = game_list_to_html(games,i_week,year,output_format=output_format,
                                              include_quality_info=False,team_records=team_records)
            md_with_quality = game_list_to_html(games,i_week,year,output_format=output_format,
                                              include_quality_info=True,team_records=team_records)
                                        
            md_no_quality_string = md_header + md_no_quality
            md_with_quality_string = md_header + md_with_quality
            
            md_no_quality_file = 'year_{}_week_{}_no_quality.md'.format(year,i_week)
            md_with_quality_file = 'year_{}_week_{}_with_quality.md'.format(year,i_week)
            
            no_quality_links.append(md_no_quality_file)
            with_quality_links.append(md_with_quality_file)
            
            with open(os.path.join(markdown_folder,md_no_quality_file),'w') as f:
                f.write(md_no_quality_string)
            with open(os.path.join(markdown_folder,md_with_quality_file),'w') as f:
                f.write(md_with_quality_string)                
                    
        # ...for each week
                
        # Write the year page
        
        year_s = '---\n'
        year_s += 'title: NFL simulated-real-time schedules, 2009-present\n'
        year_s += 'description: " "\n'
        year_s += '---\n\n'

        year_s += '# Game info for the {} season\n\n'.format(year)
        
        year_s += '## Records only\n\n'        
        for i_week in range(0,len(weeks)):
            year_s += '* [{}]({})\n'.format(week_index_to_name(i_week,year).title(),no_quality_links[i_week])
        
        year_s += '\n## With quality indicators\n\n'
        for i_week in range(0,len(weeks)):
            year_s += '* [{}]({})\n'.format(week_index_to_name(i_week,year).title(),with_quality_links[i_week])
            
        year_file = os.path.join(markdown_folder,'season_{}.md'.format(year))
        with open(year_file,'w') as f:
            f.write(year_s)
        
    # ...for each year
        
    
#%% Test driver

if False:

    #%%
    
    # https://www.pro-football-reference.com/years/2009/week_1.htm
    year = 2009
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
