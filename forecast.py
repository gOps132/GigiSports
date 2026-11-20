"""Forecasters Challenge research; Python 3.9+, standard library only."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from itertools import count
import json
from pathlib import Path
import re
from statistics import mean
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID
from zoneinfo import ZoneInfo

MCP_URL = 'https://api.theforecasterschallenge.com/api/v1/mcp'
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/'
EVENT = '6e54f461-33fd-4089-8c88-478880601c26'
LOBBY = '14e606a7-0334-4992-b9e0-5b0f9e49cdf9'
ET = ZoneInfo('America/New_York')
METRICS = ('win', 'double-double', 'bench', 'turnovers', 'fouls', 'Q4 leads',
           'Q1 scoring', '30+ points', '5+ threes', 'losing scorer')


def read_key():
    import os
    key = os.environ.get('BOT_KEY', '').strip()
    if not key and Path('.env').is_file():
        match = re.search(r'^\s*(?:export\s+)?BOT_KEY\s*=[ \t]*([^\r\n]+)',
                          Path('.env').read_text(), re.M)
        if match:
            key = match[1].strip().strip('"\'')
    if not key or any(c.isspace() for c in key):
        raise ValueError('Set BOT_KEY in the environment or in .env')
    return key


class Challenge:
    def __init__(self, key):
        self.ids = count(1)
        self.headers = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                        'Accept': 'application/json, text/event-stream'}
        result = self.rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
                                        'clientInfo': {'name': 'GigiSports', 'version': '1.0'}})
        self.headers['MCP-Protocol-Version'] = result['protocolVersion']
        self.rpc('notifications/initialized', notification=True)

    def rpc(self, method, params=None, notification=False):
        message = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            message['params'] = params
        if not notification:
            message['id'] = next(self.ids)
        with urlopen(Request(MCP_URL, json.dumps(message).encode(), self.headers), timeout=15) as r:
            if method == 'initialize' and r.headers.get('Mcp-Session-Id'):
                self.headers['Mcp-Session-Id'] = r.headers['Mcp-Session-Id']
            if notification:
                return None
            if r.headers.get_content_type() == 'text/event-stream':
                response = next((item for item in (json.loads(line[6:]) for line in r
                                 if line.startswith(b'data: ')) if item.get('id') == message['id']), {})
            else:
                response = json.load(r)
        if response.get('id') != message['id'] or 'result' not in response:
            raise ValueError(f'MCP {method} did not return a successful reply')
        return response['result']

    def call(self, name, **params):
        if name not in {'list_lobbies', 'list_matches', 'list_markets', 'list_predictions', 'list_results'}:
            raise ValueError('Only read-only contest tools are supported')
        return self._tool(name, params)

    def submit(self, entries):
        return self._tool('submit_predictions_batch', {'predictions': entries})

    def _tool(self, name, params):
        result = self.rpc('tools/call', {'name': name, 'arguments': params})
        if result.get('isError'):
            raise ValueError(f'MCP tool failed: {name}')
        if 'structuredContent' in result:
            return result['structuredContent']
        return json.loads(result['content'][0]['text'])


def espn(path, **params):
    with urlopen(ESPN + path + '?' + urlencode(params), timeout=15) as response:
        return json.load(response)


def scoreboard(day):
    return espn('scoreboard', dates=day.strftime('%Y%m%d'))['events']


def sides(game):
    teams = {x['homeAway']: x for x in game['competitions'][0]['competitors']}
    return teams['home'], teams['away']


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def outcomes(game, summary):
    home, away = sides(game)
    ids = [team['team']['id'] for team in (home, away)]
    scores = [int(team['score']) for team in (home, away)]
    if scores[0] == scores[1]:
        raise ValueError('tied final score')
    winner = int(scores[1] > scores[0])
    box = summary['boxscore']
    players = {}
    for team in box['players']:
        group = team['statistics'][0]
        athletes = [a for a in group['athletes'] if not a.get('didNotPlay')]
        if any(len(a['stats']) != len(group['keys']) for a in athletes):
            raise ValueError('incomplete player stats')
        players[team['team']['id']] = [(a['starter'], dict(zip(group['keys'], a['stats']))) for a in athletes]
    for team, score in zip(ids, scores):
        if sum(starter for starter, _ in players[team]) != 5 or sum(
                int(p['points']) for _, p in players[team]) != score:
            raise ValueError('box score does not reconcile')
    stats = {x['team']['id']: {z['name']: z['displayValue'] for z in x['statistics']} for x in box['teams']}
    quarters = [[int(q['value']) for q in team['linescores']] for team in (home, away)]
    plays = [p for p in summary['plays'] if p['period']['number'] == 4]
    if any(len(q) < 4 for q in quarters) or not plays or [int(plays[-1][key]) for key in (
            'homeScore', 'awayScore')] != [sum(q[:4]) for q in quarters]:
        raise ValueError('fourth-quarter play-by-play does not reconcile')
    leads = [sum(quarters[0][:3]) - sum(quarters[1][:3])]
    leads.extend(int(p['homeScore']) - int(p['awayScore']) for p in plays)
    all_players = [p for team in ids for _, p in players[team]]
    doubles = sum(sum(int(p[k]) >= 10 for k in ('points', 'rebounds', 'assists', 'blocks', 'steals')) >= 2
                  for p in all_players)
    bench = [sum(int(p['points']) for starter, p in players[team] if not starter) for team in ids]
    turnovers = [int(stats[team]['totalTurnovers']) for team in ids]
    fouls = [int(stats[team]['fouls']) for team in ids]
    shared = (min(leads) < 0 < max(leads), all(q[0] >= 25 for q in quarters),
              any(int(p['points']) >= 30 for p in all_players),
              any(int(p['threePointFieldGoalsMade-threePointFieldGoalsAttempted'].split('-')[0]) >= 5
                  for p in all_players),
              any(int(p['points']) >= 25 for _, p in players[ids[1 - winner]]))
    return tuple((winner == i, doubles >= 2, bench[i] > bench[1 - i],
                  turnovers[i] > turnovers[1 - i], fouls[i] > fouls[1 - i], *shared) for i in range(2))


def historical_row(game):
    # Cache only verified final box scores, not odds, injuries, or the live slate.
    game_id = game['id']
    if not re.fullmatch(r'[0-9]+', game_id):
        raise ValueError('invalid ESPN game ID')
    path = Path('.forecast-cache') / (game_id + '.json')
    if path.is_file():
        summary = json.loads(path.read_text())
    else:
        summary = espn('summary', event=game_id)
        summary.pop('pickcenter', None)
        summary.pop('injuries', None)
    result = outcomes(game, summary)
    if not path.exists():
        from tempfile import NamedTemporaryFile
        with NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as f:
            temp = Path(f.name)
            try:
                json.dump(summary, f, separators=(',', ':'))
                f.flush()
                temp.replace(path)
            finally:
                if temp.exists():
                    temp.unlink()
    home, away = sides(game)
    return (instant(game['date']).astimezone(ET).date(),
            (home['team']['id'], away['team']['id']), result)


def fit(rows, teams, i, side):
    symmetric = i not in (0, 2, 3, 4)
    base = (sum(r[2][side][i] for r in rows) + 2) / (len(rows) + 4)
    local = [r[2][side][i] for r in rows if (set(r[1]) & set(teams) if symmetric else
                                           r[1][0] == teams[0] or r[1][1] == teams[1])]
    return base, (sum(local) + 20 * base) / (len(local) + 20)


def validate(rows):
    # Forecast each held-out ET day using only preceding days. Choose team shrinkage
    # only when the average gain clears a small, pre-set threshold.
    days = sorted({r[0] for r in rows})
    folds = [(tuple(r for r in rows if r[0] < day), tuple(r for r in rows if r[0] == day))
             for day in days[len(days) * 2 // 3:]]
    scores = {}
    for i in range(1, len(METRICS)):
        pairs = [(fit(train, r[1], i, side), r[2][side][i]) for train, test in folds if len(train) >= 40
                 for r in test for side in ((0, 1) if i in (2, 3, 4) else (0,))]
        if pairs:
            scores[i] = tuple(mean((p[j] - y) ** 2 for p, y in pairs) for j in (0, 1))
    return scores, sum(len(test) for train, test in folds if len(train) >= 40)


def market_questions(home, away):
    questions = {}
    for side, (a, b) in enumerate(((home, away), (away, home))):
        questions.update({f'Will the {a} win?': (0, side),
                          f'Will the {a} bench outscore the {b} bench?': (2, side),
                          f'Will the {a} commit more turnovers?': (3, side),
                          f'Will the {a} commit more team fouls? (excluding technicals)': (4, side)})
    questions.update({q: (i, 0) for i, q in {
        1: 'Will 2 or more players record a double-double?',
        5: 'Will both teams lead at some point in the 4th quarter?',
        6: 'Will both teams score 25+ points in the 1st quarter?',
        7: 'Will any player score 30+ points?',
        8: 'Will any player make 5+ three-pointers?',
        9: 'Will any player on the losing team score 25+ points?',
    }.items()})
    return questions


def moneyline(summary, teams, side):
    for offer in summary.get('pickcenter', []):
        implied = []
        for i, field in enumerate(('homeTeamOdds', 'awayTeamOdds')):
            odds = offer.get(field, {})
            line = odds.get('moneyLine')
            if str(odds.get('teamId')) != teams[i] or not isinstance(line, (float, int)) or abs(line) < 100:
                break
            implied.append(-line / (100 - line) if line < 0 else 100 / (100 + line))
        if len(implied) == 2:
            return implied[side] / sum(implied), offer['provider']['name'] + ' moneylines, de-vigged'
    return None, 'No verified two-sided moneyline'


def render_match(match, markets, game, summary, rows, scores, captured=None, entries=None):
    tip = instant(game['date']).astimezone(ET)
    home, away = sides(game)
    teams = tuple(t['team']['id'] for t in (home, away))
    lookup = market_questions(*(t['team']['displayName'] for t in (home, away)))
    lines = [f'## {match["name"]} — {tip:%I:%M %p %Z}', '',
             f'[ESPN game and availability](https://www.espn.com/nba/game/_/gameId/{game["id"]}) · '
             f'Contest match `{match["id"]}` · multiplier {match["multiplier"]}×', '']
    injuries = [(t['team']['displayName'], ', '.join(f'{p["athlete"]["displayName"]} ({p["status"]})'
                 for p in t['injuries'])) for t in summary.get('injuries', []) if t.get('injuries')]
    lines.extend(f'- {team}: {players}' for team, players in injuries)
    if not injuries:
        lines.append('- No injury entries returned; availability is not confirmed.')
    lines += ['', '| Exact contest question | Yes | Method |', '|---|---:|---|']
    records = []
    for market in markets:
        question = market['question']
        if market['status'] != 'open' or market['lobby_id'] != LOBBY or market['match']['id'] != match['id']:
            raise ValueError('market is closed or belongs to the wrong match or lobby')
        p, method = None, 'Unrecognized wording; review manually'
        if question in lookup:
            i, side = lookup[question]
            if i == 0:
                p, method = moneyline(summary, teams, side)
            else:
                base, team = fit(rows, teams, i, side)
                use_team = i in scores and scores[i][0] - scores[i][1] > .005
                p, method = (team, 'Team-adjusted baseline') if use_team else (base, 'League baseline')
        probability = None if p is None else max(1, min(99, round(100 * p)))
        yes = '—' if probability is None else f'{probability}%'
        if captured is not None and probability is not None:
            record = {'market_id': str(UUID(market['id'])), 'lobby_id': LOBBY, 'event_id': EVENT,
                      'question': question, 'match': match['name'], 'tip': tip.isoformat(),
                      'captured': captured.isoformat(), 'probability': probability, 'method': method}
            # Escape HTML comment delimiters in externally supplied strings.
            data = json.dumps(record, sort_keys=True).replace('-', chr(92) + 'u002d')
            records.append(f'<!-- gigisports-baseline-v1 {data} -->')
            if entries is not None:
                entries.append(record)
        lines.append(f'| {question.replace(chr(124), chr(92) + chr(124))} | {yes} | {method} |')
    return '\n'.join(lines + ([''] + records if records else []))


def research(day, lookback, *, client=None, selected=None, entries=None):
    if client is None:
        client = Challenge(read_key())
    lobbies = client.call('list_lobbies', event_id=EVENT)
    if not any(x['id'] == LOBBY and x['joined'] for x in lobbies):
        raise ValueError('The bot has not joined the Forecasters Challenge lobby; join before running research')
    now = datetime.now(timezone.utc)
    matches = [m for m in client.call('list_matches', event_id=EVENT, lobby_id=LOBBY)
               if instant(m['opening_time']).astimezone(ET).date() == day and instant(m['opening_time']) > now
               and (selected is None or m['id'] in selected)]
    head = f'# Forecasters Challenge research — {day} (ET)\n\nGenerated {now:%Y-%m-%d %H:%M UTC}. Research snapshot only.'
    if not matches:
        return head + '\n\nNo open pre-tip contest matches for this date.'
    slate = scoreboard(day)
    pairs = []
    notes = []
    for match in matches:
        games = [g for g in slate if g['status']['type']['state'] == 'pre'
                 and instant(g['date']) == instant(match['opening_time'])
                 and match['name'] == ' vs '.join(t['team']['displayName'] for t in sides(g))]
        if len(games) != 1:
            notes.append(f'- Skipped {match["name"]}: no unique ESPN pre-tip matchup and time match.')
        else:
            pairs.append((match, games[0]))
    if not pairs:
        return '\n\n'.join((head, '\n'.join(notes)))
    latest = min(day, now.astimezone(ET).date())
    days = [latest - timedelta(days=i) for i in range(1, lookback + 1)]
    Path('.forecast-cache').mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        games = {g['id']: g for batch in pool.map(scoreboard, days) for g in batch
                 if g['status']['type']['name'] == 'STATUS_FINAL'
                 and instant(g['date']).astimezone(ET).date() in days}

        def load(game):
            try:
                return historical_row(game)
            except (KeyError, ValueError, OSError) as exc:
                return f'{game["id"]}: {exc}'

        loaded = list(pool.map(load, games.values()))
        rows = [r for r in loaded if not isinstance(r, str)]
        skipped = [r for r in loaded if isinstance(r, str)]
        if len(rows) < 40 or len(rows) < .9 * len(games):
            raise ValueError(f'Insufficient verified history: {len(rows)}/{len(games)} games; '
                             f'first exclusions: {"; ".join(skipped[:3]) or "none"}')
        scores, n_test = validate(rows)
        summaries = list(pool.map(lambda pair: espn('summary', event=pair[1]['id']), pairs))
    sections = [head, f'History: {len(rows)}/{len(games)} final ESPN games, {min(r[0] for r in rows)} to '
                      f'{max(r[0] for r in rows)}. Model selection: {n_test} walk-forward games; '
                      'these scores are not an independent test. Injury entries are listed for review '
                      'but do not change model probabilities.']
    if notes or skipped:
        sections.append('\n'.join(notes + [f'- Excluded historical game {error}' for error in skipped]))
    for (match, game), summary in zip(pairs, summaries):
        markets = client.call('list_markets', match_id=match['id'], lobby_id=LOBBY)
        captured = datetime.now(timezone.utc)
        if instant(game['date']) <= captured:
            sections.append(f'- Skipped {match["name"]}: tipoff passed while preparing this report.')
        elif not markets:
            sections.append(f'- Skipped {match["name"]}: no markets still open.')
        else:
            sections.append(render_match(match, markets, game, summary, rows, scores, captured, entries))
    if scores:
        sections.append('\n'.join(['## Model-selection Brier scores (lower is better)', '',
                                   '| Market | League | Team |', '|---|---:|---:|'] +
                                  [f'| {METRICS[i]} | {a:.4f} | {b:.4f} |' for i, (a, b) in scores.items()]))
    return '\n\n'.join(sections)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', type=date.fromisoformat, default=datetime.now(ET).date(), help='slate date in ET')
    parser.add_argument('--lookback', type=int, choices=range(7, 61), default=19, metavar='7–60', help='history days (default 19)')
    args = parser.parse_args()
    try:
        print(research(args.date, args.lookback))
    except (ValueError, OSError, KeyError, IndexError) as exc:
        print(f'Research failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
