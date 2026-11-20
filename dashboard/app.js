const $ = (id) => document.getElementById(id);
const el = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
};
const zone = 'America/New_York';
const formatter = (options, lang = 'en-US') => new Intl.DateTimeFormat(lang, { timeZone: zone, ...options });
const dateKey = formatter({ year: 'numeric', month: '2-digit', day: '2-digit' }, 'sv-SE');
const dayLabel = formatter({ weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
const clock = formatter({ hour: 'numeric', minute: '2-digit', timeZoneName: 'short' });
const short = formatter({ month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
let snapshot, selected, busy = false;
const status = {
  running: ['Running now', 'The LaunchAgent is currently executing a check.', 'good'],
  scheduled: ['Scheduled', 'The LaunchAgent is loaded and waiting for its next check.', 'good'],
  attention: ['Needs attention', 'The last check did not exit successfully. See recent errors below.', 'warn'],
  'not loaded': ['Not loaded', 'The autopilot LaunchAgent is not loaded in this login session.', 'warn'],
  unavailable: ['Unavailable', 'The app could not read the macOS LaunchAgent status.', 'warn'],
};

function drawBot(bot, at) {
  const [title, detail, tone] = status[bot.state] || status.unavailable;
  $('top-status').className = `chip ${tone}`;
  $('top-status').replaceChildren(el('i'), document.createTextNode(title));
  $('bot-detail').textContent = detail;
  $('runs').textContent = bot.runs ?? '\u2014';
  $('interval').textContent = bot.interval == null ? '\u2014' : `${bot.interval / 60} min`;
  $('last-exit').textContent = bot.last_exit == null ? '\u2014' : bot.last_exit === 0 ? 'OK (0)' : bot.last_exit;
  $('activity').replaceChildren(...(bot.activity.length ? bot.activity : ['No output yet.']).map((s) => el('li', s)));
  $('errors').replaceChildren(...bot.errors.map((s) => el('li', s)));
  $('error-box').hidden = !bot.errors.length;
  $('updated').textContent = `Checked ${clock.format(new Date(at))}.`;
}

function drawGame(name, rows, key, open) {
  const block = el('details', undefined, 'game');
  block.dataset.gameKey = key;
  block.open = open;
  const summary = el('summary');
  const icon = el('img'); icon.src = 'assets/chevron-right.svg'; icon.alt = '';
  summary.append(icon, el('strong', name), el('span', clock.format(new Date(rows[0].tip))));
  const table = el('table');
  const head = table.createTHead().insertRow();
  for (const label of ['Contest question', 'YES', 'Method']) {
    const th = el('th', label); th.scope = 'col'; head.append(th);
  }
  const body = table.createTBody();
  for (const row of rows) {
    const tr = body.insertRow();
    for (const val of [row.question, `${row.probability}%`, row.method]) tr.append(el('td', val));
  }
  block.append(summary, table);
  return block;
}

function drawSlate() {
  const slates = new Map();
  for (const row of snapshot.forecasts) {
    const key = dateKey.format(new Date(row.tip));
    if (!slates.has(key)) slates.set(key, []);
    slates.get(key).push(row);
  }
  const days = [...slates.keys()].sort();
  if (!slates.has(selected)) selected = slates.has(dateKey.format(new Date())) ? dateKey.format(new Date()) : days.at(-1);
  const idx = days.indexOf(selected);
  const slate = slates.get(selected) || [];
  $('date-nav').hidden = !slate.length;
  if (slate.length) $('slate-date').textContent = dayLabel.format(new Date(slate[0].tip));
  $('prev').disabled = idx < 1;
  $('next').disabled = idx < 0 || idx === days.length - 1;
  $('prev').onclick = () => { selected = days[idx - 1]; drawSlate(); };
  $('next').onclick = () => { selected = days[idx + 1]; drawSlate(); };
  const games = new Map();
  for (const row of slate) {
    const key = `${row.tip} ${row.match}`;
    if (!games.has(key)) games.set(key, []);
    games.get(key).push(row);
  }
  $('game-count').textContent = games.size;
  $('market-count').textContent = slate.length;
  const latest = Math.max(...slate.map((row) => Date.parse(row.captured)));
  $('latest').textContent = Number.isFinite(latest) ? short.format(latest) : '\u2014';
  const old = new Map([...$('games').querySelectorAll('details')].map((item) => [item.dataset.gameKey, item.open]));
  $('games').replaceChildren(...(games.size
    ? [...games].map(([key, rows], i) => drawGame(rows[0].match, rows, key, old.get(key) ?? i === 0))
    : [el('div', 'No priced forecast cards yet. New cards appear here after research or a pre-tip autopilot run.', 'empty')]));
}

const scheduleTime = formatter({ weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' });

async function drawSchedule(invoke) {
  const { games, updated, error } = await invoke('upcoming');
  const now = Date.now();
  $('schedule-status').textContent = error ? `${error}${updated ? ' Showing last available schedule.' : ''}`
    : !updated ? 'Loading contest schedule…' : !games.length ? 'No upcoming open games.' : '';
  $('schedule-games').replaceChildren(...games.map((game) => {
    const item = el('li');
    const start = new Date(game.window_start);
    const end = new Date(game.window_end);
    const active = start <= now && now < end;
    item.append(el('strong', game.name), el('span', `Tipoff: ${scheduleTime.format(new Date(game.tip))}`),
      el('span', now >= end ? 'Autopilot window ended'
        : `${active ? 'Window open' : `Window opens ${scheduleTime.format(start)}`} · ends ${clock.format(end)}`,
      active ? 'open-window' : undefined));
    return item;
  }));
}

$('test-alert').addEventListener('click', async () => {
  try {
    await globalThis.__TAURI_INTERNALS__.invoke('test_notification');
    $('alert-result').textContent = 'Test requested. If nothing appears, check macOS Notifications settings.';
  } catch {
    $('alert-result').textContent = 'Could not request a test notification.';
  }
});

async function refresh() {
  if (busy) return;
  busy = true;
  $('refresh').disabled = true;
  try {
    const invoke = globalThis.__TAURI_INTERNALS__?.invoke;
    if (!invoke) throw new Error('Open the GigiSports desktop app to load local data.');
    snapshot = await invoke('dashboard');
    drawBot(snapshot.bot, snapshot.checked_at);
    drawSlate();
    await drawSchedule(invoke).catch(() => { $('schedule-status').textContent = 'Schedule unavailable.'; });
    $('notice').hidden = !snapshot.warnings.length;
    $('notice').textContent = snapshot.warnings.join(' ');
    $('updated').title = snapshot.workspace;
  } catch (error) {
    $('notice').hidden = false;
    $('notice').textContent = `Could not refresh: ${error.message ?? error}`;
    if (!snapshot) {
      $('games').replaceChildren(el('div', 'Forecast archive unavailable.', 'empty'));
      drawBot({state: 'unavailable', activity: [], errors: []}, Date.now());
    }
  } finally {
    busy = false;
    $('refresh').disabled = false;
  }
}
$('refresh').addEventListener('click', refresh);
refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 30000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
