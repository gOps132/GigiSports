"""Submit fresh baseline forecasts for games tipping in the next 40 minutes."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import fcntl
import json
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile
from uuid import UUID

from forecast import Challenge, ET, EVENT, LOBBY, instant, read_key, research


def positions(client):
    result = {}
    offset, total = 0, None
    while total is None or offset < total:
        page = client.call('list_predictions', event_id=EVENT, lobby_id=LOBBY, limit=200, offset=offset)
        items = page['items']
        if (page['offset'] != offset or type(page['total']) is not int or not isinstance(items, list)
                or offset + len(items) > page['total'] or (total is not None and total != page['total'])
                or (not items and offset < page['total'])):
            raise ValueError('Prediction pages changed or were incomplete; retry on the next run')
        total = page['total']
        for item in items:
            market = str(UUID(item['market_id']))
            if market in result:
                raise ValueError('Duplicate market in prediction pages; retry on the next run')
            result[market] = item['probability']
        offset += len(items)
    return result


def archive(directory, card):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory, prefix='.autopilot-', delete=False) as f:
        temp = Path(f.name)
        try:
            f.write(card)
            f.flush()
            temp.rename(directory / f'{stamp}-{temp.name[1:]}.md')
        finally:
            temp.unlink(missing_ok=True)


LEAD = timedelta(minutes=40)
CUTOFF = timedelta(minutes=2)


def schedule(client, now):
    upcoming = []
    for match in client.call('list_matches', event_id=EVENT, lobby_id=LOBBY):
        tip = instant(match['opening_time'])
        if tip > now:
            upcoming.append(dict(id=match['id'], name=match['name'], tip=tip.isoformat(),
                                 window_start=(tip - LEAD).isoformat(),
                                 window_end=(tip - CUTOFF).isoformat()))
    return sorted(upcoming, key=lambda game: instant(game['tip']))


def run(client, directory):
    now = datetime.now(timezone.utc)
    matches = defaultdict(set)
    for game in schedule(client, now):
        if instant(game['window_start']) <= now < instant(game['window_end']):
            matches[instant(game['tip']).astimezone(ET).date()].add(game['id'])
    if not matches:
        print('No games in the pre-tip submission window.')
        return
    entries = []
    for day, selected in matches.items():
        archive(directory, research(day, 19, client=client, selected=selected, entries=entries))
    if len({row['market_id'] for row in entries}) != len(entries):
        raise ValueError('Duplicate market in research; nothing submitted')
    existing = positions(client) if entries else {}
    pending = [row for row in entries if row['market_id'] not in existing]
    print(f'{len(entries)} priced markets; {len(entries) - len(pending)} already entered.', flush=True)
    failures = []
    for start in range(0, len(pending), 50):
        cutoff = datetime.now(timezone.utc) + CUTOFF
        chunk = [row for row in pending[start:start + 50] if instant(row['tip']) > cutoff]
        if not chunk:
            continue
        payload = [{key: row[key] for key in ('market_id', 'lobby_id', 'probability')} for row in chunk]
        # Do not immediately retry an uncertain write. Verify against the bot's actual positions.
        try:
            client.submit(payload)
        except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
            print(f'Submission response uncertain: {exc}', file=sys.stderr)
        actual = positions(client)
        missing = [row['market_id'] for row in chunk if actual.get(row['market_id']) != row['probability']]
        print(f'Confirmed {len(chunk) - len(missing)}/{len(chunk)} new forecasts.', flush=True)
        failures.extend(missing)
    if failures:
        raise ValueError('Unconfirmed market IDs (next run rechecks existing positions): ' + ', '.join(failures))


def main():
    try:
        if sys.argv[1:] == ['--schedule']:
            print(json.dumps(schedule(Challenge(read_key()), datetime.now(timezone.utc))))
            return 0
        if sys.argv[1:]:
            raise ValueError('Usage: autopilot.py [--schedule]')
        directory = Path('reports')
        directory.mkdir(exist_ok=True)
        with (directory / '.autopilot.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print('Another autopilot run is active.')
                return 0
            run(Challenge(read_key()), directory)
    except (ValueError, OSError, KeyError, TypeError, AttributeError, IndexError) as exc:
        print(f'Autopilot failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
