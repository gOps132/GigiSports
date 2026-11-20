use crate::data;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::{collections::BTreeSet, process::Command, sync::Mutex, time::Duration};
use tauri::{AppHandle, Manager};
use tauri_plugin_notification::NotificationExt;

#[derive(Clone, Deserialize, Serialize)]
struct Game {
    id: String,
    name: String,
    tip: DateTime<Utc>,
    window_start: DateTime<Utc>,
    window_end: DateTime<Utc>,
}

#[derive(Clone, Default, Serialize)]
pub struct Schedule {
    games: Vec<Game>,
    updated: Option<DateTime<Utc>>,
    error: Option<String>,
}

#[derive(Default)]
pub struct State(Mutex<Schedule>);

impl State {
    pub fn snapshot(&self) -> Schedule {
        let mut snapshot = self.0.lock().unwrap().clone();
        snapshot.games.retain(|g| g.tip > Utc::now());
        snapshot
    }
}

fn load() -> Result<Vec<Game>, String> {
    let out = Command::new("/usr/bin/python3")
        .args(["autopilot.py", "--schedule"])
        .current_dir(data::workspace())
        .output()
        .map_err(|_| "Could not start the schedule reader.")?;
    if !out.status.success() {
        return Err(
            "Could not load the contest schedule. Check your connection and bot setup.".into(),
        );
    }
    serde_json::from_slice(&out.stdout)
        .map_err(|_| "The schedule reader returned invalid data.".into())
}

fn due<'a>(games: &'a [Game], now: DateTime<Utc>, notified: &BTreeSet<String>) -> Vec<&'a Game> {
    games
        .iter()
        .filter(|g| g.window_start <= now && now < g.window_end && !notified.contains(&g.id))
        .collect()
}

pub fn notify(app: &AppHandle, title: &str, body: &str) -> Result<(), String> {
    app.notification()
        .builder()
        .title(title)
        .body(body)
        .show()
        .map_err(|e| e.to_string())
}

pub fn start(app: AppHandle) {
    std::thread::spawn(move || {
        let mut notified = BTreeSet::new();
        // The dashboard can be hidden; this loop is independent of the webview.
        loop {
            let state = app.state::<State>();
            match load() {
                Ok(games) => {
                    let now = Utc::now();
                    let due = due(&games, now, &notified);
                    if !due.is_empty() {
                        let body = format!(
                            "{} game(s) in the pre-tipoff window. {}",
                            due.len(),
                            data::reminder_status()
                        );
                        if notify(&app, "GigiSports: forecast window is open", &body).is_ok() {
                            notified.extend(due.iter().map(|g| g.id.clone()));
                        }
                    }
                    *state.0.lock().unwrap() = Schedule {
                        games,
                        updated: Some(now),
                        error: None,
                    };
                }
                Err(error) => state.0.lock().unwrap().error = Some(error),
            }
            std::thread::sleep(Duration::from_secs(60));
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeDelta;

    #[test]
    fn reminder_window_includes_start_excludes_cutoff_and_deduplicates() {
        let start = Utc::now();
        let game = Game {
            id: "test".into(),
            name: "Test".into(),
            tip: start + TimeDelta::minutes(40),
            window_start: start,
            window_end: start + TimeDelta::minutes(38),
        };
        let games = [game];
        let mut notified = BTreeSet::new();
        assert!(due(&games, start - TimeDelta::seconds(1), &notified).is_empty());
        assert_eq!(due(&games, start, &notified).len(), 1);
        assert!(due(&games, games[0].window_end, &notified).is_empty());
        notified.insert("test".into());
        assert!(due(&games, start, &notified).is_empty());
    }
}
