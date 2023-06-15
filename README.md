## nfl-game-dates

Python script to retrieve a chronologically sorted list of NFL games for any week, historical or scheduled, from pro-football-reference.com.

Maybe more importantly, a set of pages that show records going *into* each NFL week since 2009, so you can look at games for a particular week and decide which games are good, without spoilers.  Optionally also view heuristic indicators of which games are likely "good", "bad", or "neither".  This set of pages lives [here](https://agentmorris.github.io/nfl-game-dates/).


### But why?

I am critically dependent on NFL football for my physical fitness.  So dependent that I wrote an [excessively long blog post](http://rockicon.net/wp/2019/10/22/the-doctor-of-rocks-tfip-total-football-immersion-program/) about how hard I work to avoid football scores so I'm motivated to exercise every day.  During the season, of course, that's football that was just played the prior weekend.  But even during the offseason, I watch old playoff games that I don't really remember.  Either way, I <i>need</i> to avoid knowing the outcomes of football games.

With the old NFL Game Pass Web site, this was easy: games were listed in order, so I could watch early games without fear of finding out the outcome of late games.  As of 8/2021, with a recent major revision to their site, this is no longer the case.  Ergo, before watching a week of new football, or even an old playoff week, I need to know the order in which games were played.

If you're wondering "but don't all the scores tick along the bottom of the screen?"... yes, they do, which is why I use a [nice little program](https://aka.ms/scoreblocker) that [Neel](https://www.microsoft.com/en-us/research/people/neel/) wrote to put a big black rectangle on the bottom of the screen.  Very sophisticated technology.  Sidebar: sports are more fun without the distracting ticker anyway.

If you're wondering "but don't they go to game breaks and tell you about other games?"... yes, they do, but <b>I'm a f'ing pro</b>, so I always know when a game break is coming and I can get my headphones out and my eyes averted in plenty of time.  Because I'm a pro.

If you're wondering "but don't you talk to other people about football?"... no, no I do not.


### Usage

`python nfl-game-dates.py [year] [week] [--html]`

"year" is the start of the season, not the calendar year of the game.  I.e., 2012 week 17 is in 2013.

"week" is the week to retrieve.  Can be:

* A 1-indexed number from 1 to 22, where 22 would be the Super Bowl after the start of the 17-game season
* A playoff round name, from ["wild card","divisional","championship","super bowl"]

The "html" option renders to HTML instead of text, with links to NFL Game Pass.


### Examples

#### Using a playoff round name
```
python nfl-game-dates.py 2012 divisional

Parsing games...
Baltimore Ravens at Denver Broncos, 2013-01-12 16:36:00
Green Bay Packers at San Francisco 49ers, 2013-01-12 20:25:00
Seattle Seahawks at Atlanta Falcons, 2013-01-13 13:05:00
Houston Texans at New England Patriots, 2013-01-13 16:40:00
```

#### Future games
```
python nfl-game-dates.py 2021 1

Parsing games...
Dallas Cowboys at Tampa Bay Buccaneers, 2021-09-09 20:20:00
Pittsburgh Steelers at Buffalo Bills, 2021-09-12 13:00:00
Philadelphia Eagles at Atlanta Falcons, 2021-09-12 13:00:00
Los Angeles Chargers at Washington Football Team, 2021-09-12 13:00:00
Arizona Cardinals at Tennessee Titans, 2021-09-12 13:00:00
Jacksonville Jaguars at Houston Texans, 2021-09-12 13:00:00
San Francisco 49ers at Detroit Lions, 2021-09-12 13:00:00
Seattle Seahawks at Indianapolis Colts, 2021-09-12 13:00:00
Minnesota Vikings at Cincinnati Bengals, 2021-09-12 13:00:00
New York Jets at Carolina Panthers, 2021-09-12 13:00:00
Denver Broncos at New York Giants, 2021-09-12 16:25:00
Miami Dolphins at New England Patriots, 2021-09-12 16:25:00
Green Bay Packers at New Orleans Saints, 2021-09-12 16:25:00
Cleveland Browns at Kansas City Chiefs, 2021-09-12 16:25:00
Chicago Bears at Los Angeles Rams, 2021-09-12 20:20:00
Baltimore Ravens at Las Vegas Raiders, 2021-09-13 20:15:00
```

