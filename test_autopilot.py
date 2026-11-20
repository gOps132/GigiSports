from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import autopilot as a


class AutopilotTests(unittest.TestCase):
    def test_archive_and_skip_existing_verify_new(self):
        for confirmed in (True, False):
            with self.subTest(confirmed=confirmed), TemporaryDirectory() as root:
                client = Mock()
                directory = Path(root)
                now = datetime.now(timezone.utc)
                tip = (now + timedelta(minutes=25)).isoformat()
                client.call.return_value = [{'name': 'Eligible game', 'id': 'eligible', 'opening_time': tip},
                                            {'name': 'Later game', 'id': 'early', 'opening_time': (now + timedelta(hours=2)).isoformat()}]
                def research(day, lookback, *, client, selected, entries):
                    self.assertEqual(selected, {'eligible'})
                    entries.extend(dict(market_id=i, lobby_id=a.LOBBY, probability=67, tip=tip)
                                   for i in ('existing', 'new'))
                    return '# Card\n'

                def submit(entries):
                    self.assertEqual([x['market_id'] for x in entries], ['new'])
                    self.assertEqual(next(directory.glob('*.md')).read_text(), '# Card\n')
                    if not confirmed:
                        raise OSError('lost reply')

                client.submit.side_effect = submit
                with patch.object(a, 'research', side_effect=research), patch.object(a, 'positions',
                        side_effect=[{'existing': 62}, {'new': 67} if confirmed else {}]):
                    if confirmed:
                        a.run(client, directory)
                    else:
                        with self.assertRaisesRegex(ValueError, 'Unconfirmed market IDs'):
                            a.run(client, directory)
                client.submit.assert_called_once()

    def test_empty_window_never_writes(self):
        client = Mock()
        client.call.return_value = []
        with patch.object(a, 'research') as research:
            a.run(client, Path('unused'))
        research.assert_not_called()
        client.submit.assert_not_called()

    def test_positions_rejects_missing_page(self):
        client = Mock()
        client.call.return_value = {'total': 1, 'offset': 0, 'items': []}
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            a.positions(client)
