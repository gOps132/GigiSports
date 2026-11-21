from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import patch
from uuid import UUID

from contest_status import contest_totals, ongoing_games, read_status


def market(n):
    return str(UUID(int=n))


class ContestStatusTests(TestCase):
    def test_counts_confirmed_entries_once_and_uses_settled_probability(self):
        class Client:
            def call(self, name, **params):
                if name == 'list_predictions':
                    items = [dict(market_id=market(1), probability=60),
                             dict(market_id=market(2), probability=65)]
                elif name == 'list_results':
                    items = [dict(market_id=market(1), probability_submitted=71, outcome_tag='beat_crowd', rbp=5.8),
                             dict(market_id=market(3), probability_submitted=40, outcome_tag='lost_to_crowd', rbp=-8.3),
                             dict(market_id=market(4), probability_submitted=50, outcome_tag='tied_crowd', rbp=0),
                             dict(market_id=None, probability_submitted=80, outcome_tag=None, rbp=None)]
                else:
                    raise AssertionError(name)
                return dict(total=len(items), items=items, offset=params['offset'])

        self.assertEqual(contest_totals(Client()), dict(submitted=5, successes=1, losses=1, points=-2.5,
                              predictions={market(1): 71, market(2): 65, market(3): 40, market(4): 50}))

    def test_no_entries_and_unscored_entries_are_distinct(self):
        class Client:
            items = []

            def call(self, name, **params):
                items = self.items if name == 'list_results' else []
                return dict(total=len(items), items=items, offset=params['offset'])

        client = Client()
        self.assertEqual(contest_totals(client), dict(submitted=0, predictions={}, successes=0, losses=0, points=0))
        client.items = [dict(market_id=market(1), probability_submitted=51, rbp=None)]
        self.assertIsNone(contest_totals(client)['points'])

    @patch('contest_status.scoreboard')
    def test_overnight_game_is_live_until_espn_marks_it_final(self, scoreboard):
        def game(id, state):
            return {'id': id, 'status': {'type': {'state': state}}, 'competitions': [{'competitors': [
                {'homeAway': 'home', 'team': {'displayName': 'Utah Jazz'}},
                {'homeAway': 'away', 'team': {'displayName': 'Phoenix Suns'}},
            ]}]}

        now = datetime(2026, 11, 21, 5, 10, tzinfo=timezone.utc)
        scoreboard.side_effect = [[game('late', 'in'), game('finished', 'post')], [game('next', 'pre')]]
        self.assertEqual(ongoing_games(now), ['Utah Jazz vs Phoenix Suns'])
        self.assertEqual([str(call.args[0]) for call in scoreboard.call_args_list], ['2026-11-20', '2026-11-21'])
        scoreboard.side_effect = [[game('late', 'in')], [game('late', 'post')]]
        self.assertEqual(ongoing_games(now), [])

    @patch('contest_status.scoreboard', return_value=[])
    @patch('contest_status.read_key', side_effect=ValueError('not configured'))
    def test_unavailable_contest_does_not_hide_live_feed(self, key, scoreboard):
        self.assertEqual(read_status(), {'contest': None, 'ongoing': []})

    @patch('contest_status.scoreboard', side_effect=OSError('offline'))
    @patch('contest_status.Challenge')
    @patch('contest_status.read_key', return_value='test-key')
    def test_unavailable_scoreboard_does_not_hide_totals(self, key, challenge, scoreboard):
        challenge.return_value.call.return_value = dict(total=0, offset=0, items=[])
        status = read_status()
        self.assertIsNone(status['ongoing'])
        self.assertEqual(status['contest']['submitted'], 0)
