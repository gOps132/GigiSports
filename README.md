# GigiSports — Forecasters Challenge

Generate a reviewable NBA forecast card from the live contest slate and ESPN data. The research and settlement commands are read-only. `autopilot.py` generates and submits forecasts for the bot; it never revises or cancels existing entries.

## macOS dashboard

Build and open the local Tauri app from this checkout (arm64 Mac, Xcode Command Line Tools, Rust 1.99 and Node/npm):

```sh
RUSTUP_TOOLCHAIN=1.99.0 npx --yes @tauri-apps/cli@2.12.6 build --debug --bundles app -- --locked
open src-tauri/target/debug/bundle/macos/GigiSports.app
cargo +1.99.0 test --locked --manifest-path src-tauri/Cargo.toml
```

The dashboard shows the latest archived probability per market, grouped by Eastern Time slate and matchup, plus the LaunchAgent's current state and recent output. It refreshes every 30 seconds while visible. Older cards without machine-readable baseline records do not appear. Click the macOS menu-bar chart icon to reopen the window after closing it. Right-click for **Quit Dashboard**, which stops dashboard notifications but leaves autopilot running.

**Upcoming tipoffs** lists scheduled game starts in Eastern Time and the associated autopilot windows. With the app running (even with its window closed), GigiSports checks the contest schedule about once a minute and sends a reminder when a game enters the submission window. A reminder signals the window is open, not that entries were accepted. Use **Test alert** and allow notifications in macOS System Settings if needed. You normally do not need to start the bot manually. This build reads the checkout it was built from; rebuild after moving the repo or launch the binary with `GIGISPORTS_DIR` pointing at the existing workspace.

Icons and the chart logo use [Lucide](https://lucide.dev/) SVGs vendored with their [license](dashboard/assets/LUCIDE-LICENSE). The app and macOS menu-bar icons are rasterized from the chart SVG.

## Architecture

```text
 PRE-TIP RESEARCH

 [Challenge MCP] -- open games, exact questions --+
                                                   |
 [ESPN] -- schedule, odds, injury notes -----------+--> [forecast.py]
       \-- final box scores and play-by-play ------+    | Match games by teams + tipoff
                                                        | Win: de-vig ESPN moneylines
 [Local cache: .forecast-cache/] <--------------------> | Props: league or team baseline
       Verified historical summaries only                |        selected via walk-forward Brier
                                                        v
                                               [Markdown card on stdout]
                                                        | archive with the README shell command
                                                        v
                                               [reports/*.md]
                                                Market ID + pre-tip probability
                                                + capture time and method
                                                    |                 |
                           earliest baseline by ID  |                 | fresh pre-tip card
                                                    |                 v
                                                    |        [Autopilot submits entries]
                                                    |                 |
 POST-SETTLEMENT REVIEW                             |                 v
                                                    |        [Challenge MCP: list_results]
                                                    |                 | submitted %, outcome, RBP
                                                    v                 v
 [Optional overrides.json] -- reasons by ID --> [settlement.py: join by market ID]
                                                        |
                                                        v
                                               [Markdown review on stdout]
                                                Baseline vs submitted Brier,
                                                changed-only comparison, and RBP
```

All commands share the MCP client and load `BOT_KEY` from the environment or `.env`. Only autopilot calls the write endpoint.

## Run

From this directory, use Python 3.9+ with system timezone data and network access. No packages are required. The challenge bot must have joined the lobby. Keep `BOT_KEY` in the environment or the local `.env` (one `BOT_KEY=…` assignment); do not commit it. The script connects directly to the MCP server, so it doesn't require Codex to run.

```sh
python3 forecast.py                            # today's ET slate, Markdown to stdout
python3 forecast.py --date 2026-11-20           # explicit ET slate, only games still pre-tip
python3 forecast.py --lookback 28               # 7–60 days; default 19
python3 -m unittest -v                          # offline tests
```

## Daily workflow

1. **Generate and archive a card.** Run early for the slate, then again 30–60 minutes before the relevant tipoffs. Use a scheduler with this repo as its working directory if you want unattended research. Keep timestamped reports rather than overwriting the previous forecast; failed runs should not publish a card. For example, this shell block works for both manual runs and a scheduler:

   ```sh
   (
     set -eu
     mkdir -p reports
     tmp=$(mktemp reports/.draft.XXXXXX)
     trap 'rm -f "$tmp"' EXIT
     python3 forecast.py > "$tmp"
     mv "$tmp" "reports/$(date -u +%Y%m%dT%H%M%SZ)-${tmp##*.}.md"
   )
   ```

2. **Submit automatically.** Autopilot runs fresh research for games in its pre-tip window, archives that card, and sends only priced markets without an existing entry. No basketball knowledge or manual approval is needed. ESPN injury notes are recorded but are not model inputs yet.
3. **After settlement, measure.** Run `python3 settlement.py` to pull all settled predictions for this lobby and compare them with the earliest archived pre-tip probability for the same market ID. The review shows final submitted probabilities, outcomes, paired Brier scores, and contest RBP per matched market. Lower Brier is better; a positive baseline-minus-submitted difference favors the submitted forecasts. Missing RBP means no crowd comparison, not zero. Use MCP `get_event_standing` separately for leaderboard rank.
4. **Improve one input at a time.** Start with confirmed availability/minutes for double-doubles, 30+ points, 5+ threes, and bench scoring. Log the baseline and proposed adjustment before tip, and evaluate across later slates without tuning on those evaluation results. Keep changes that improve Brier out of sample, not just on a few standout games.

## Autopilot

On the configured Mac, the `com.gigisports.autopilot` user LaunchAgent checks every 10 minutes while the login session is active. It considers open games between 2 and 40 minutes from tipoff, archives the fresh card in `reports/`, submits at most 50 forecasts per batch, and verifies accepted probabilities against `list_predictions`. Unknown questions and markets with no price are skipped. Existing predictions are never overwritten. An unconfirmed write is not retried within the same run; later runs query existing entries before trying again.

- Inspect output in `reports/autopilot.log` and errors in `reports/autopilot.err`.
- Pause it with `launchctl bootout "gui/$(id -u)/com.gigisports.autopilot"`.
- Resume it with `launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.gigisports.autopilot.plist"`.
- `python3 autopilot.py` runs a submission check immediately using the same window and safeguards. It is **not** a dry run.

The Mac needs to be awake, online, and logged in near tipoff. This is a free contest workflow; it does not place bets or transfer money.

## Settlement tracking

Keep the original Markdown cards in `reports/` (or use `python3 settlement.py --reports PATH`). New cards embed baseline records as Markdown comments with the market ID, captured time, tipoff, probability, and method. Cards created before tracking was added cannot be matched. Use the market ID from the card source or MCP `list_markets` to record any override before tipoff. Save an optional local `reports/overrides.json` in this format:

```json
{
  "88dea06b-7014-4d43-9b49-ff4308a11b6f": {
    "probability": 64,
    "reason": "Confirmed starter ruled out"
  }
}
```

Run `python3 settlement.py --reasons reports/overrides.json` to include those notes. A note is shown only if its probability matches the final submitted probability and differs from the baseline. Review output goes to stdout; the tracker does not write to the contest or change report files. Results with no ID or no archived baseline are counted separately and excluded from the paired metrics. Compare changed forecasts separately to see whether adjustments helped, not just whether the whole slate was accurate.

## What the card does

- Matches the contest's open NBA games to ESPN by home/away names and tipoff. It skips ambiguous games, games that started during the run, and games without open markets. A dash means the script could not price that question safely.
- Uses two-sided ESPN moneylines with the bookmaker margin removed for win questions. Other markets use verified ESPN final box scores and play-by-play. Only verified historical summaries are cached in `.forecast-cache/`; live summaries are fetched each run. A game with inconsistent fourth-quarter scoring is excluded and reported rather than silently treated as a NO. The script stops if fewer than 40 games validate or if fewer than 90% of the retrieved finals validate.
- Compares a league baseline with a sample of games involving either team, shrunk toward the league baseline. It selects team adjustment per market only if walk-forward Brier improves by more than 0.005 on the model-selection window. That window is not independent evidence of an edge. Strict comparisons treat ties as NO; the historical labels are reconstructed from ESPN, not the platform's settlement feed.

Local reports, cached data, transcript exports, and credentials are ignored by Git.
