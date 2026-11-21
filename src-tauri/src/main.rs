mod data;
mod menu_bar;
mod schedule;

use tauri::{
    image::Image,
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, WindowEvent,
};

#[tauri::command]
async fn dashboard() -> Result<data::Snapshot, String> {
    tauri::async_runtime::spawn_blocking(data::snapshot)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
async fn contest_status() -> Result<serde_json::Value, String> {
    tauri::async_runtime::spawn_blocking(|| {
        let out = std::process::Command::new("/usr/bin/python3")
            .args(["-B", "contest_status.py"])
            .current_dir(data::workspace())
            .output()
            .map_err(|_| "Could not start the contest status reader.")?;
        if !out.status.success() {
            return Err("Could not load contest status.");
        }
        serde_json::from_slice(&out.stdout).map_err(|_| "Invalid contest status response.")
    })
    .await
    .map_err(|e| e.to_string())?
    .map_err(str::to_owned)
}

#[tauri::command]
fn upcoming(state: tauri::State<'_, schedule::State>) -> schedule::Schedule {
    state.snapshot()
}

#[tauri::command]
fn test_notification(app: tauri::AppHandle) -> Result<(), String> {
    schedule::notify(
        &app,
        "GigiSports notifications",
        "Pre-tipoff reminders will appear here.",
    )
}

#[tauri::command]
fn dismiss_menu_status(window: tauri::WebviewWindow) -> tauri::Result<()> {
    if window.label() == menu_bar::LABEL {
        window.hide()?;
    }
    Ok(())
}

fn show_dashboard(app: &tauri::AppHandle) {
    menu_bar::hide(app);
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .manage(schedule::State::default())
        .manage(menu_bar::Clicks::default())
        .invoke_handler(tauri::generate_handler![
            dashboard,
            contest_status,
            dismiss_menu_status,
            upcoming,
            test_notification
        ])
        .setup(|app| {
            menu_bar::setup(app.handle())?;
            let show = MenuItem::with_id(app, "show", "Open GigiSports", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit Dashboard", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;
            TrayIconBuilder::with_id("gigisports")
                .icon(Image::from_bytes(include_bytes!("../icons/tray.png"))?)
                .icon_as_template(true)
                .tooltip("GigiSports Forecast Dashboard")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_tray_icon_event(|tray, event| {
                    let app = tray.app_handle();
                    let clicks = app.state::<menu_bar::Clicks>();
                    match event {
                        TrayIconEvent::Click {
                            button: MouseButton::Left,
                            button_state: MouseButtonState::Up,
                            ..
                        } => clicks.left_click(app),
                        TrayIconEvent::Click {
                            button: MouseButton::Right,
                            button_state: MouseButtonState::Down,
                            ..
                        } => {
                            clicks.reset();
                            menu_bar::hide(app);
                        }
                        _ => {}
                    }
                })
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "show" => show_dashboard(app),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;
            schedule::start(app.handle().clone());
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .run(tauri::generate_context!())
        .expect("error running GigiSports");
}
