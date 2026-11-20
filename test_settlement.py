from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

import forecast as f
import settlement as s

MARKET = '88dea06b-7014-4d43-9b49-ff4308a11b6f'


class SettlementTests(unittest.TestCase):
    def card(self, p, hour):
        match = {'id': 'test', 'name': 'Home -- Away', 'multiplier': 1}
        team = lambda side: {'homeAway': side.lower(), 'team': {'displayName': side, 'id': side}}
        game = {'id': '100', 'date': '2026-11-21T00:00Z',
                'competitions': [{'competitors': [team('Home'), team('Away')]}]}
        market = {'id': MARKET, 'match': {'id': 'test'}, 'lobby_id': f.LOBBY, 'status': 'open',
                  'question': 'Will the Home win?'}
        offer = {'homeTeamOdds': {'teamId': 'Home', 'moneyLine': p},
                 'awayTeamOdds': {'teamId': 'Away', 'moneyLine': 199}, 'provider': {'name': 'Test'}}
        return f.render_match(match, [market], game, {'pickcenter': [offer]}, [], {},
                              datetime(2026, 11, 20, hour, tzinfo=timezone.utc))

    def test_first_card_round_trips_and_pairs(self):
        first = self.card(-241, 12)
        self.assertNotIn('Home -- Away', next(line for line in first.splitlines() if line.startswith(s.PREFIX)))
        with TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'a-refresh.md').write_text(self.card(-150, 23))
            (path / 'z-first.md').write_text(first)
            (path / 'old.md').write_text('# Untracked card')
            archive = s.baselines(path)
        self.assertEqual(archive[MARKET]['probability'], 68)
        self.assertEqual(archive[MARKET]['match'], 'Home -- Away')
        data = [(MARKET, {'result_value': 100, 'probability_submitted': 80, 'rbp': 0}),
                (None, {}), ('unmatched', {})]
        result = s.report(archive, data, {MARKET: {'probability': 80, 'reason': 'Starter confirmed'}})
        for text in ('3 settled predictions; 1 paired', '1 without a matching baseline', '1 without a market ID',
                     '0.1024', '0.0400', '+0.0624', 'YES (100)', '+0.00', 'Starter confirmed'):
            self.assertIn(text, result)
        data[0][1].update(result_value=0, rbp=None)
        result = s.report(archive, data, {MARKET: {'probability': 81, 'reason': 'Stale note'}})
        self.assertIn('NO (0)', result)
        self.assertIn('| — | Not recorded |', result)
        data[0][1]['result_value'] = 50
        with self.assertRaisesRegex(ValueError, 'non-binary'):
            s.report(archive, data, {})

    def test_invalid_archive_fails(self):
        line = next(line for line in self.card(-241, 12).splitlines() if line.startswith(s.PREFIX))
        row = json.loads(line[len(s.PREFIX):-4])
        with TemporaryDirectory() as directory:
            path = Path(directory)
            for field, value in [('captured', row['tip']), ('probability', True)]:
                bad = dict(row, **{field: value})
                (path / 'invalid.md').write_text(s.PREFIX + json.dumps(bad) + ' -->')
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'invalid.md:'):
                    s.baselines(path)

    def test_paginates_and_refuses_partial_or_duplicate_data(self):
        first = {'total': 2, 'offset': 0, 'items': [{'market_id': MARKET}]}
        client = Mock()
        client.call.side_effect = [first, {'total': 2, 'offset': 1, 'items': [{}]}]
        self.assertEqual([market for market, _ in s.settled(client)], [MARKET, None])
        self.assertEqual([call.kwargs['offset'] for call in client.call.call_args_list], [0, 1])
        for items, error in [([], 'incomplete'), (first['items'], 'duplicate')]:
            client.call.side_effect = [first, {'total': 2, 'offset': 1, 'items': items}]
            with self.subTest(items=items), self.assertRaisesRegex(ValueError, error):
                list(s.settled(client))


if __name__ == '__main__':
    unittest.main()
