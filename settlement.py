"""Compare archived pre-tip baselines with actual Forecasters Challenge results."""
import argparse
import json
from pathlib import Path
from statistics import mean
import sys
from uuid import UUID

from forecast import Challenge, EVENT, LOBBY, instant, read_key

PREFIX = '<!-- gigisports-baseline-v1 '


def probability(value):
    if type(value) is not int or not 1 <= value <= 99:
        raise ValueError('expected an integer probability from 1 to 99')
    return value


def baselines(directory):
    first = {}
    for path in sorted(directory.glob('*.md')):
        for line in path.read_text().splitlines():
            if not line.startswith(PREFIX):
                continue
            try:
                if not line.endswith(' -->'):
                    raise ValueError('incomplete baseline record')
                row = json.loads(line[len(PREFIX):-4])
                if (row['event_id'], row['lobby_id']) != (EVENT, LOBBY):
                    continue
                market = str(UUID(row['market_id']))
                captured, tip = (instant(row[k]) for k in ('captured', 'tip'))
                if captured.tzinfo is None or tip.tzinfo is None or captured >= tip:
                    raise ValueError('baseline must have a timezone and precede tipoff')
                probability(row['probability'])
                for field in ('question', 'match', 'method'):
                    if not isinstance(row[field], str) or not row[field]:
                        raise ValueError(f'invalid {field}')
                previous = first.get(market)
                if previous is None or captured < instant(previous['captured']):
                    first[market] = row
                elif captured == instant(previous['captured']) and row != previous:
                    raise ValueError(f'conflicting baselines for {market} at the same time')
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise ValueError(f'{path.name}: {exc}') from exc
    return first


def settled(client):
    # Keep a complete result set or fail; a partial page would skew the comparison.
    offset, total, seen = 0, None, set()
    while total is None or offset < total:
        page = client.call('list_results', event_id=EVENT, lobby_id=LOBBY, limit=200, offset=offset)
        items = page['items']
        if (type(page['total']) is not int or page['offset'] != offset or not isinstance(items, list)
                or offset + len(items) > page['total'] or (total is not None and total != page['total'])
                or (not items and offset < page['total'])):
            raise ValueError('settlement pages changed or were incomplete; rerun the report')
        total = page['total']
        for row in items:
            market = str(UUID(row['market_id'])) if row.get('market_id') else None
            if market in seen:
                raise ValueError(f'duplicate settled market {market}; rerun the report')
            if market is not None:
                seen.add(market)
            yield market, row
        offset += len(items)


def report(archive, results, reasons):
    matched, missing_id, unmatched = [], 0, 0
    results = list(results)
    for market, row in results:
        if market is None:
            missing_id += 1
            continue
        base = archive.get(market)
        if base is None:
            unmatched += 1
            continue
        outcome = row['result_value']
        if type(outcome) is not int or outcome not in (0, 100):
            raise ValueError(f'non-binary settlement for market {market}')
        submitted = probability(row['probability_submitted'])
        base_error = ((base['probability'] - outcome) / 100) ** 2
        final_error = ((submitted - outcome) / 100) ** 2
        note = reasons.get(market, {})
        reason = note.get('reason', '') if note.get('probability') == submitted else ''
        matched.append((market, base, submitted, outcome, base_error, final_error, row.get('rbp'), reason))
    output = ['# Forecasters Challenge settlement review', '',
              f'{len(results)} settled predictions; {len(matched)} paired with the first archived pre-tip baseline. '
              f'{unmatched} without a matching baseline; {missing_id} without a market ID in the result.', '']
    if not matched:
        return '\n'.join(output + ['No paired Brier comparison yet.'])
    base_mean, submitted_mean = (mean(item[i] for item in matched) for i in (4, 5))
    output += [f'Paired mean Brier: baseline **{base_mean:.4f}**, submitted **{submitted_mean:.4f}** '
               f'(baseline minus submitted: **{base_mean - submitted_mean:+.4f}**; positive favors submissions).']
    changed = [item for item in matched if item[1]['probability'] != item[2]]
    if changed:
        output.append(f'Changed forecasts only: {len(changed)} markets; mean Brier improvement '
                      f'**{mean(item[4] - item[5] for item in changed):+.4f}**.')
    output += ['', '| Match | Question | Baseline (captured) | Submitted | Result | Baseline Brier | Submitted Brier | RBP | Override reason |',
               '|---|---|---|---:|---|---:|---:|---:|---|']
    for market, base, submitted, outcome, a, b, rbp, reason in sorted(matched, key=lambda x: (x[1]['tip'], x[0])):
        fields = (base['match'], f"{base['question']} (`{market}`)",
                  f"{base['probability']}% ({base['captured']})", f'{submitted}%',
                  'YES (100)' if outcome else 'NO (0)', f'{a:.4f}', f'{b:.4f}',
                  '—' if rbp is None else f'{rbp:+.2f}',
                  (reason or 'Not recorded') if submitted != base['probability'] else '—')
        output.append('| ' + ' | '.join(v.replace('|', r'\|').replace('\n', ' ').replace('\r', '') for v in fields) + ' |')
    return '\n'.join(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports', type=Path, default=Path('reports'), help='directory of archived forecast cards')
    parser.add_argument('--reasons', type=Path, help='optional JSON file of pre-tip override notes keyed by market ID')
    args = parser.parse_args()
    try:
        archive = baselines(args.reports)
        reasons = json.loads(args.reasons.read_text()) if args.reasons else {}
        if not isinstance(reasons, dict):
            raise ValueError('override notes must be a JSON object keyed by market ID')
        for market, note in reasons.items():
            UUID(market)
            if not isinstance(note, dict) or not isinstance(note.get('reason'), str) or not note['reason'].strip():
                raise ValueError(f'invalid override reason for {market}')
            probability(note.get('probability'))
        print(report(archive, settled(Challenge(read_key())), reasons))
    except (ValueError, OSError, KeyError, TypeError, AttributeError, IndexError) as exc:
        print(f'Settlement review failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
