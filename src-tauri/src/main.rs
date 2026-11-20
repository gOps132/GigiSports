mod data;
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

fn show_dashboard(app: &tauri::AppHandle) {
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
        .invoke_handler(tauri::generate_handler![
            dashboard,
            upcoming,
            test_notification
        ])
        .setup(|app| {
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
                    if matches!(
                        event,
                        TrayIconEvent::Click {
                            button: MouseButton::Left,
                            button_state: MouseButtonState::Up,
                            ..
                        }
                    ) {
                        show_dashboard(tray.app_handle());
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
