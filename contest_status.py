"""Read the dashboard's contest totals and live NBA games without submitting anything."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
from math import fsum, isfinite

from autopilot import positions
from forecast import Challenge, ET, read_key, scoreboard, sides
from settlement import probability, settled


def contest_totals(client):
    # Read positions first so entries that settle between calls can be deduplicated.
    predictions = positions(client)
    tags = Counter()
    scores = []
    without_market = 0
    for market, row in settled(client):
        final_probability = probability(row['probability_submitted'])
        if market is None:
            without_market += 1
        else:
            predictions[market] = final_probability
        tags[row.get('outcome_tag')] += 1
        score = row.get('rbp')
        if score is not None:
            if type(score) not in (int, float) or not isfinite(score):
                raise ValueError('Invalid relative Brier points')
            scores.append(score)
    return dict(submitted=len(predictions) + without_market, predictions=predictions,
                successes=tags['beat_crowd'], losses=tags['lost_to_crowd'],
                points=round(fsum(scores), 2) if scores or not tags else None)


def ongoing_games(now):
    day = now.astimezone(ET).date()
    # A West Coast game can still be in progress after midnight Eastern.
    games = {g['id']: g for date in (day - timedelta(days=1), day) for g in scoreboard(date)}
    return [' vs '.join(t['team']['displayName'] for t in sides(game))
            for game in games.values() if game['status']['type']['state'] == 'in']


def read_status():
    def read(fn):
        try:
            return fn()
        except (ValueError, OSError, KeyError, TypeError, AttributeError, IndexError):
            # A failed feed is unknown, not zero. The other feed can still be shown.
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        contest = pool.submit(read, lambda: contest_totals(Challenge(read_key())))
        ongoing = pool.submit(read, lambda: ongoing_games(datetime.now(ET)))
        return dict(contest=contest.result(), ongoing=ongoing.result())


if __name__ == '__main__':
    print(json.dumps(read_status(), allow_nan=False))
