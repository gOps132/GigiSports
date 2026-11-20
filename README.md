<a id="readme-top"></a>

<div align="center">

[![GitHub issues][issues-shield]][issues-url]
[![GitHub stars][stars-shield]][stars-url]

</div>

<div align="center">
  <a href="https://github.com/gOps132/GigiSports">
    <img src="src-tauri/icons/app.png" alt="GigiSports logo" width="112" height="112">
  </a>
  <h1>GigiSports</h1>
  <p>NBA forecast cards, automated submissions, and settlement reviews for the Forecasters Challenge.</p>
  <p>
    <a href="#getting-started"><strong>Get started</strong></a>
    &middot;
    <a href="#macos-dashboard">macOS dashboard</a>
    &middot;
    <a href="https://github.com/gOps132/GigiSports/issues">Report a bug or request a feature</a>
  </p>
</div>

<details>
  <summary>Table of Contents</summary>
  <ol>
    <li><a href="#about-the-project">About the Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
        <li><a href="#what-the-card-does">What the card does</a></li>
        <li><a href="#architecture">Architecture</a></li>
      </ul>
    </li>
    <li><a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
        <li><a href="#macos-dashboard">macOS dashboard</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a>
      <ul>
        <li><a href="#daily-workflow">Daily workflow</a></li>
        <li><a href="#autopilot">Autopilot</a></li>
        <li><a href="#settlement-tracking">Settlement tracking</a></li>
      </ul>
    </li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>

## About the Project

Generate a reviewable NBA forecast card from the live contest slate and ESPN data. The research and settlement commands are read-only. `autopilot.py` generates and submits forecasts for the bot; it never revises or cancels existing entries.

### Built With

- [Python](https://www.python.org/) (standard library only) for forecasting, submissions, and settlement reviews.
- [Rust](https://www.rust-lang.org/) and [Tauri](https://tauri.app/) with plain HTML, CSS, and JavaScript for the macOS dashboard.

### What the card does

- Matches the contest's open NBA games to ESPN by home/away names and tipoff. It skips ambiguous games, games that started during the run, and games without open markets. A dash means the script could not price that question safely.
- Uses two-sided ESPN moneylines with the bookmaker margin removed for win questions. Other markets use verified ESPN final box scores and play-by-play. Only verified historical summaries are cached in `.forecast-cache/`; live summaries are fetched each run. A game with inconsistent fourth-quarter scoring is excluded and reported rather than silently treated as a NO. The script stops if fewer than 40 games validate or if fewer than 90% of the retrieved finals validate.
- Compares a league baseline with a sample of games involving either team, shrunk toward the league baseline. It selects team adjustment per market only if walk-forward Brier improves by more than 0.005 on the model-selection window. That window is not independent evidence of an edge. Strict comparisons treat ties as NO; the historical labels are reconstructed from ESPN, not the platform's settlement feed.

### Architecture

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
                                                        | archive with the daily workflow below
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

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Getting Started

### Prerequisites

- Python 3.9+ with system timezone data. No Python packages are required.
- Network access to the Forecasters Challenge and ESPN for live runs.
- A Forecasters Challenge bot that has joined the lobby, and its `BOT_KEY`.

### Installation

```sh
git clone https://github.com/gOps132/GigiSports.git
cd GigiSports
```

Set `BOT_KEY` in your environment or add a single `BOT_KEY=…` assignment to a local `.env` in the checkout. Do not commit the key. Run the Python commands from the checkout; they connect directly to the contest MCP server without Codex.

### macOS dashboard

Optionally, build and open the local Tauri app from this checkout (arm64 Mac, Xcode Command Line Tools, Rust 1.99 and Node/npm):

```sh
RUSTUP_TOOLCHAIN=1.99.0 npx --yes @tauri-apps/cli@2.12.6 build --debug --bundles app -- --locked
open src-tauri/target/debug/bundle/macos/GigiSports.app
```

The dashboard shows the latest archived probability per market, grouped by Eastern Time slate and matchup, plus the LaunchAgent's current state and recent output. It refreshes every 30 seconds while visible. Older cards without machine-readable baseline records do not appear. Click the macOS menu-bar chart icon to reopen the window after closing it. Right-click for **Quit Dashboard**, which stops dashboard notifications but leaves autopilot running.

**Upcoming tipoffs** lists scheduled game starts in Eastern Time and the associated autopilot windows. With the app running (even with its window closed), GigiSports checks the contest schedule about once a minute and sends a reminder when a game enters the submission window. A reminder signals the window is open, not that entries were accepted. Use **Test alert** and allow notifications in macOS System Settings if needed. You normally do not need to start the bot manually. This build reads the checkout it was built from; rebuild after moving the repo or launch the binary with `GIGISPORTS_DIR` pointing at the existing workspace.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Usage

```sh
python3 forecast.py                            # today's ET slate, Markdown to stdout
python3 forecast.py --date 2026-11-20           # explicit ET slate, only games still pre-tip
python3 forecast.py --lookback 28               # 7–60 days; default 19
```

### Daily workflow

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

### Autopilot

On the configured Mac, the `com.gigisports.autopilot` user LaunchAgent checks every 10 minutes while the login session is active. It considers open games between 2 and 40 minutes from tipoff, archives the fresh card in `reports/`, submits at most 50 forecasts per batch, and verifies accepted probabilities against `list_predictions`. Unknown questions and markets with no price are skipped. Existing predictions are never overwritten. An unconfirmed write is not retried within the same run; later runs query existing entries before trying again.

- Inspect output in `reports/autopilot.log` and errors in `reports/autopilot.err`.
- Pause it with `launchctl bootout "gui/$(id -u)/com.gigisports.autopilot"`.
- Resume it with `launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.gigisports.autopilot.plist"`.
- `python3 autopilot.py` runs a submission check immediately using the same window and safeguards. It is **not** a dry run.

The Mac needs to be awake, online, and logged in near tipoff. This is a free contest workflow; it does not place bets or transfer money.

### Settlement tracking

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

Local reports, cached data, transcript exports, and credentials are ignored by Git.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Contributing

Use [GitHub Issues][issues-url] to report bugs or propose improvements. Include the affected command or dashboard view, what you expected, and what happened. Redact credentials and avoid attaching private reports.

Run the offline Python tests and, for macOS dashboard changes, the Rust tests:

```sh
python3 -m unittest -v
cargo +1.99.0 test --locked --manifest-path src-tauri/Cargo.toml
```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Acknowledgments

- README layout adapted from [gOps132/ReadMeTemplate](https://github.com/gOps132/ReadMeTemplate).
- The dashboard icons and chart logo use [Lucide](https://lucide.dev/). The app and menu-bar icons are rasterized from the chart SVG. See the [vendored Lucide license](dashboard/assets/LUCIDE-LICENSE).

<p align="right">(<a href="#readme-top">back to top</a>)</p>

[issues-shield]: https://img.shields.io/github/issues/gOps132/GigiSports?style=for-the-badge
[issues-url]: https://github.com/gOps132/GigiSports/issues
[stars-shield]: https://img.shields.io/github/stars/gOps132/GigiSports?style=for-the-badge
[stars-url]: https://github.com/gOps132/GigiSports/stargazers
