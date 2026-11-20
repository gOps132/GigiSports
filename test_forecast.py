import unittest
from datetime import date, timedelta
from unittest.mock import Mock, patch

import forecast as f


class ForecastTests(unittest.TestCase):
    def test_moneyline_requires_two_matching_teams(self):
        offer = {'homeTeamOdds': {'teamId': '1', 'moneyLine': -241},
                 'awayTeamOdds': {'teamId': '30', 'moneyLine': 199},
                 'provider': {'name': 'Test'}}
        summary = {'pickcenter': [offer]}
        home, _ = f.moneyline(summary, ('1', '30'), 0)
        away, _ = f.moneyline(summary, ('1', '30'), 1)
        self.assertAlmostEqual(home, .679, places=3)
        self.assertAlmostEqual(home + away, 1)
        self.assertIsNone(f.moneyline(summary, ('1', 'wrong'), 0)[0])
        offer['awayTeamOdds']['moneyLine'] = None
        self.assertIsNone(f.moneyline(summary, ('1', '30'), 0)[0])

    def test_walk_forward_uses_only_prior_days(self):
        start = date(2026, 11, 1)
        rows = [(start + timedelta(days=i // 5), ('1', '2'), ((False,) * 10, (True,) * 10))
                for i in range(60)]
        observed = []

        def fit(train, teams, metric, side):
            observed.append(len(train))
            return .25, .5

        with patch.object(f, 'fit', side_effect=fit):
            scores, games = f.validate(rows)
        self.assertEqual(games, 20)
        self.assertEqual(set(observed), {40, 45, 50, 55})
        self.assertEqual(scores[1], (.0625, .25))
        self.assertEqual(scores[2], (.3125, .25))
        self.assertEqual(f.validate(rows[:30]), ({}, 0))

    def test_market_render_refuses_mismatch_and_marks_unpriced_questions(self):
        match = {'id': 'test', 'name': 'Home vs Away', 'multiplier': 1}
        teams = [{'homeAway': side.lower(), 'team': {'displayName': side, 'id': str(i)}}
                 for i, side in enumerate(('Home', 'Away'))]
        game = {'id': '100', 'date': '2026-11-21T00:00Z', 'competitions': [{'competitors': teams}]}
        market = {'match': {'id': 'test'}, 'lobby_id': f.LOBBY, 'status': 'open'}
        report = f.render_match(match, [dict(market, question='Will the Away win?'),
                                       dict(market, question='Unknown?')], game, {}, [], {})
        self.assertIn('Will the Away win? | — | No verified two-sided moneyline', report)
        self.assertIn('Unknown? | — | Unrecognized wording', report)
        for field, value in [('status', 'closed'), ('lobby_id', 'wrong'), ('match', {'id': 'wrong'})]:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'wrong match or lobby'):
                f.render_match(match, [dict(market, question='Unknown?', **{field: value})], game, {}, [], {})

    def test_no_matches_does_not_query_espn(self):
        client = Mock()
        client.call.side_effect = [[{'id': f.LOBBY, 'joined': True}], []]
        with patch.object(f, 'Challenge', return_value=client), patch.object(f, 'read_key'), \
                patch.object(f, 'scoreboard') as scoreboard:
            self.assertIn('No open pre-tip contest matches', f.research(date(2026, 11, 20), 19))
        scoreboard.assert_not_called()
        self.assertEqual([call.args[0] for call in client.call.call_args_list], ['list_lobbies', 'list_matches'])

    def test_not_joined_stops_before_research(self):
        client = Mock()
        client.call.return_value = [{'id': f.LOBBY, 'joined': False}]
        with patch.object(f, 'Challenge', return_value=client), patch.object(f, 'read_key'), \
                self.assertRaisesRegex(ValueError, 'has not joined'):
            f.research(date(2026, 11, 20), 19)
        client.call.assert_called_once_with('list_lobbies', event_id=f.EVENT)

    def test_client_refuses_mutating_tools(self):
        client = f.Challenge.__new__(f.Challenge)
        client.rpc = Mock()
        for name in ('join_lobby', 'submit_prediction', 'submit_predictions_batch',
                     'update_prediction', 'delete_prediction'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Only read-only'):
                client.call(name)
        client.rpc.assert_not_called()


if __name__ == '__main__':
    unittest.main()
