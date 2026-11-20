use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    env, fs,
    io::{Read, Seek, SeekFrom},
    path::{Path, PathBuf},
    process::Command,
};

const EVENT: &str = "6e54f461-33fd-4089-8c88-478880601c26";
const LOBBY: &str = "14e606a7-0334-4992-b9e0-5b0f9e49cdf9";
const PREFIX: &str = "<!-- gigisports-baseline-v1 ";

#[derive(Deserialize, Serialize)]
pub struct Forecast {
    market_id: String,
    event_id: String,
    lobby_id: String,
    #[serde(rename = "match")]
    game: String,
    question: String,
    method: String,
    tip: DateTime<Utc>,
    captured: DateTime<Utc>,
    probability: u8,
}

#[derive(Serialize)]
struct Bot {
    state: &'static str,
    runs: Option<u64>,
    interval: Option<u64>,
    last_exit: Option<i32>,
    activity: Vec<String>,
    errors: Vec<String>,
}

#[derive(Serialize)]
pub struct Snapshot {
    forecasts: Vec<Forecast>,
    bot: Bot,
    warnings: Vec<String>,
    workspace: String,
    checked_at: String,
}

pub fn workspace() -> PathBuf {
    env::var_os("GIGISPORTS_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .expect("workspace parent")
                .to_path_buf()
        })
}

fn read_forecasts(dir: &Path, warnings: &mut Vec<String>) -> Vec<Forecast> {
    let mut latest: BTreeMap<String, Forecast> = BTreeMap::new();
    let records = match fs::read_dir(dir) {
        Ok(records) => records,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Vec::new(),
        Err(e) => {
            warnings.push(format!("Cannot read reports: {e}"));
            return Vec::new();
        }
    };
    for entry in records {
        let entry = match entry {
            Ok(entry) => entry,
            Err(e) => {
                warnings.push(format!("Cannot list a report: {e}"));
                continue;
            }
        };
        let path = entry.path();
        if path.extension().and_then(|s| s.to_str()) != Some("md")
            || !entry.file_type().is_ok_and(|t| t.is_file())
        {
            continue;
        }
        let content = match fs::read_to_string(&path) {
            Ok(content) => content,
            Err(e) => {
                warnings.push(format!(
                    "Cannot read {}: {e}",
                    entry.file_name().to_string_lossy()
                ));
                continue;
            }
        };
        let mut bad = 0;
        for line in content.lines().filter_map(|line| line.strip_prefix(PREFIX)) {
            let parsed = line
                .strip_suffix(" -->")
                .and_then(|s| serde_json::from_str::<Forecast>(s).ok());
            let Some(row) = parsed else {
                bad += 1;
                continue;
            };
            if row.event_id != EVENT || row.lobby_id != LOBBY {
                continue;
            }
            if !(1..=99).contains(&row.probability)
                || row.captured >= row.tip
                || row.market_id.is_empty()
            {
                bad += 1;
                continue;
            }
            if latest
                .get(&row.market_id)
                .is_none_or(|old| old.captured < row.captured)
            {
                latest.insert(row.market_id.clone(), row);
            }
        }
        if bad > 0 {
            warnings.push(format!(
                "{}: skipped {bad} invalid forecast records",
                entry.file_name().to_string_lossy()
            ));
        }
    }
    let mut rows: Vec<_> = latest.into_values().collect();
    rows.sort_by(|a, b| (&a.tip, &a.game, &a.question).cmp(&(&b.tip, &b.game, &b.question)));
    rows
}

fn tail(path: &Path) -> Vec<String> {
    let result = (|| -> std::io::Result<Vec<String>> {
        let mut file = fs::File::open(path)?;
        let start = file.metadata()?.len().saturating_sub(8192);
        file.seek(SeekFrom::Start(start))?;
        let mut bytes = Vec::new();
        file.take(8192).read_to_end(&mut bytes)?;
        Ok({
            let text = String::from_utf8_lossy(&bytes);
            let complete = if start > 0 {
                text.split_once('\n').map_or("", |(_, rest)| rest)
            } else {
                &text
            };
            complete
                .lines()
                .rev()
                .filter(|line| !line.trim().is_empty())
                .take(8)
                .map(str::to_owned)
                .collect()
        })
    })();
    result.unwrap_or_default()
}

fn bot_from(text: &str, state: &'static str) -> Bot {
    let value = |key: &str| {
        text.lines()
            .filter_map(|s| s.split_once(" = "))
            .find(|(name, _)| name.trim() == key)
            .map(|(_, v)| v.trim())
    };
    let last_exit = value("last exit code").and_then(|s| s.parse().ok());
    let state = if state == "loaded" {
        if matches!(
            value("state"),
            Some("running" | "xpcproxy" | "spawn scheduled")
        ) {
            "running"
        } else if last_exit.is_some_and(|code| code != 0) {
            "attention"
        } else {
            "scheduled"
        }
    } else {
        state
    };
    Bot {
        state,
        runs: value("runs").and_then(|s| s.parse().ok()),
        interval: value("run interval").and_then(|s| s.split_whitespace().next()?.parse().ok()),
        last_exit,
        activity: Vec::new(),
        errors: Vec::new(),
    }
}

fn launch_status() -> Bot {
    let uid = Command::new("/usr/bin/id")
        .arg("-u")
        .output()
        .ok()
        .filter(|o| o.status.success());
    if let Some(uid) = uid {
        let target = format!(
            "gui/{}/com.gigisports.autopilot",
            String::from_utf8_lossy(&uid.stdout).trim()
        );
        if let Ok(result) = Command::new("/bin/launchctl")
            .args(["print", &target])
            .output()
        {
            if result.status.success() {
                return bot_from(&String::from_utf8_lossy(&result.stdout), "loaded");
            }
            if String::from_utf8_lossy(&result.stderr).contains("Could not find service") {
                return bot_from("", "not loaded");
            }
        }
    }
    bot_from("", "unavailable")
}

pub fn snapshot() -> Snapshot {
    let root = workspace();
    let reports = root.join("reports");
    let mut warnings = Vec::new();
    let forecasts = read_forecasts(&reports, &mut warnings);
    if !root.join("autopilot.py").is_file() {
        warnings.push(
            "Forecast workspace not found. Set GIGISPORTS_DIR to the project directory.".to_owned(),
        );
    }
    let mut bot = launch_status();
    bot.activity = tail(&reports.join("autopilot.log"));
    bot.errors = tail(&reports.join("autopilot.err"));
    Snapshot {
        forecasts,
        bot,
        warnings,
        workspace: root.display().to_string(),
        checked_at: Utc::now().to_rfc3339(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn launch_agent_states_distinguish_idle_running_and_failed() {
        let idle = "state = not running\n last exit code = 0\n runs = 4\n run interval = 600 seconds\n state = active";
        let bot = bot_from(idle, "loaded");
        assert_eq!(
            (bot.state, bot.runs, bot.interval, bot.last_exit),
            ("scheduled", Some(4), Some(600), Some(0))
        );
        assert_eq!(
            bot_from("state = running\nlast exit code = 1", "loaded").state,
            "running"
        );
        assert_eq!(
            bot_from("state = not running\nlast exit code = 1", "loaded").state,
            "attention"
        );
        assert_eq!(bot_from("", "not loaded").state, "not loaded");
        assert_eq!(bot_from("", "unavailable").state, "unavailable");
    }

    #[test]
    fn selects_latest_valid_local_archive_record_and_tails_logs() {
        let dir = env::temp_dir().join(format!("gigisports-test-{}", std::process::id()));
        fs::create_dir(&dir).unwrap();
        struct Cleanup(PathBuf);
        impl Drop for Cleanup {
            fn drop(&mut self) {
                let _ = fs::remove_dir_all(&self.0);
            }
        }
        let _cleanup = Cleanup(dir.clone());
        let row = |hour, probability, lobby| {
            format!(
                "{PREFIX}{} -->\n",
                serde_json::json!({
                    "market_id": "88dea06b-7014-4d43-9b49-ff4308a11b6f", "event_id": EVENT, "lobby_id": lobby,
                    "match": "Atlanta vs Charlotte", "question": "Will Atlanta win?", "method": "De-vig",
                    "tip": "2026-11-20T19:00:00-05:00", "captured": format!("2026-11-20T{hour}:00:00-05:00"),
                    "probability": probability
                })
            )
        };
        fs::write(dir.join("old.md"), row("17", 54, LOBBY)).unwrap();
        fs::write(
            dir.join("new.md"),
            row("18", 67, LOBBY) + &row("19", 80, LOBBY) + &row("18", 99, "other") + PREFIX,
        )
        .unwrap();
        fs::write(
            dir.join("log"),
            format!("{}\n\nfirst\nsecond\n", "x".repeat(9000)),
        )
        .unwrap();
        let mut warnings = Vec::new();
        let rows = read_forecasts(&dir, &mut warnings);
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].probability, 67);
        assert!(warnings[0].contains("skipped 2 invalid forecast records"));
        assert_eq!(tail(&dir.join("log")), ["second", "first"]);
        assert!(read_forecasts(&dir.join("absent"), &mut warnings).is_empty());
        assert!(tail(&dir.join("absent")).is_empty());
    }
}

pub fn reminder_status() -> &'static str {
    match launch_status().state {
        "running" | "scheduled" => "Autopilot is scheduled; no action needed.",
        "attention" => "The last bot check failed. Open GigiSports to check the status.",
        _ => "Autopilot is not confirmed active. Open GigiSports to check the status.",
    }
}
