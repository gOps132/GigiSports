export const el = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
};

const number = new Intl.NumberFormat('en-US');
const points = new Intl.NumberFormat('en-US', {maximumFractionDigits: 2});
export const unknown = '\u2014';

export function drawContest(content, {contest, ongoing}) {
  const metrics = el('dl', undefined, 'contest-metrics');
  for (const [label, value, title] of [
    ['Ongoing games', ongoing?.length, 'NBA games currently in progress, per ESPN'],
    ['Submitted predictions', contest?.submitted, 'Includes both unsettled and settled entries in this lobby'],
    ['Successes', contest?.successes, 'Settled predictions that beat the crowd'],
    ['Losses', contest?.losses, 'Settled predictions that lost to the crowd'],
    ['Total points (RBP)', contest?.points, 'Sum of relative Brier points from scored predictions in this lobby'],
  ]) {
    const item = el('div');
    item.title = title;
    item.append(el('dt', label), el('dd', value == null ? unknown
      : (label === 'Total points (RBP)' ? points : number).format(value)));
    metrics.append(item);
  }
  content.replaceChildren(metrics);
  if (!contest) content.append(el('p', 'Contest totals unavailable.', 'footnote'));
  if (ongoing?.length) {
    const list = el('ul', undefined, 'live-games');
    list.setAttribute('aria-label', 'NBA games in progress');
    list.append(...ongoing.map((name) => el('li', name)));
    content.append(list);
  } else content.append(el('p', ongoing ? 'No NBA games in progress.' : 'Live game status unavailable.', 'footnote'));
  if (contest) content.append(el('p', 'Successes and losses are measured against the crowd. Ties and unscored predictions count as neither.', 'footnote'));
}
