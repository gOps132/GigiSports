use std::{
    sync::Mutex,
    time::{Duration, Instant},
};
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent};

pub const LABEL: &str = "menu-status";

#[derive(Debug, PartialEq, Eq)]
enum Action {
    ToggleStatus,
    OpenDashboard,
}

fn click(last: &mut Option<Instant>, now: Instant, interval: Duration) -> Action {
    if last
        .take()
        .is_some_and(|previous| now.duration_since(previous) <= interval)
    {
        Action::OpenDashboard
    } else {
        *last = Some(now);
        Action::ToggleStatus
    }
}

pub fn setup(app: &AppHandle) -> tauri::Result<()> {
    let window = WebviewWindowBuilder::new(app, LABEL, WebviewUrl::App("menu-status.html".into()))
        .title("GigiSports Contest Status")
        .inner_size(340.0, 390.0)
        .decorations(false)
        .resizable(false)
        .always_on_top(true)
        .visible_on_all_workspaces(true)
        .skip_taskbar(true)
        .visible(false)
        .background_color(tauri::window::Color(23, 30, 39, 255))
        .build()?;
    let handle = app.clone();
    window.on_window_event(move |event| {
        if matches!(event, WindowEvent::Focused(false)) {
            hide(&handle);
        }
    });
    Ok(())
}

pub fn hide(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(LABEL) {
        let _ = window.hide();
    }
}

#[derive(Default)]
pub struct Clicks(Mutex<Option<Instant>>);

impl Clicks {
    pub fn left_click(&self, app: &AppHandle) {
        #[cfg(target_os = "macos")]
        let interval = Duration::from_secs_f64(objc2_app_kit::NSEvent::doubleClickInterval());
        #[cfg(not(target_os = "macos"))]
        let interval = Duration::from_millis(500);
        let action = click(&mut self.0.lock().unwrap(), Instant::now(), interval);
        if action == Action::OpenDashboard {
            crate::show_dashboard(app);
        } else if let Some(window) = app.get_webview_window(LABEL) {
            if window.is_visible().unwrap_or(false) {
                hide(app);
            } else {
                anchor(&window);
                let _ = window.show();
                let _ = window.set_focus();
                let _ = window.eval("window.refreshMenuStatus?.()");
            }
        }
    }

    pub fn reset(&self) {
        self.0.lock().unwrap().take();
    }
}

// AppKit screen coordinates are already in points on the correct display, even on mixed-DPI setups.
#[cfg(target_os = "macos")]
fn anchor(window: &WebviewWindow) {
    use objc2::MainThreadMarker;
    use objc2_app_kit::{NSEvent, NSScreen, NSWindow};

    let Some(main_thread) = MainThreadMarker::new() else {
        return;
    };
    let mut cursor = NSEvent::mouseLocation();
    let screens = NSScreen::screens(main_thread);
    let Some(screen) = screens.iter().find(|screen| {
        let frame = screen.frame();
        cursor.x >= frame.origin.x
            && cursor.x < frame.origin.x + frame.size.width
            && cursor.y >= frame.origin.y
            && cursor.y < frame.origin.y + frame.size.height
    }) else {
        return;
    };
    let Ok(native) = window.ns_window() else {
        return;
    };
    // Tauri owns this NSWindow and the WebviewWindow handle keeps it alive on the main thread.
    let native = unsafe { &*native.cast::<NSWindow>() };
    let area = screen.visibleFrame();
    let width = native.frame().size.width;
    cursor.x = (cursor.x - width / 2.0).clamp(
        area.origin.x,
        area.origin.x + (area.size.width - width).max(0.0),
    );
    cursor.y = area.origin.y + area.size.height - 4.0;
    native.setFrameTopLeftPoint(cursor);
}

#[cfg(not(target_os = "macos"))]
fn anchor(_window: &WebviewWindow) {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn single_click_toggles_double_click_opens_and_third_starts_over() {
        let now = Instant::now();
        let interval = Duration::from_millis(450);
        let mut last = None;
        assert_eq!(click(&mut last, now, interval), Action::ToggleStatus);
        assert_eq!(
            click(&mut last, now + interval, interval),
            Action::OpenDashboard
        );
        let third = now + interval + Duration::from_millis(1);
        assert_eq!(click(&mut last, third, interval), Action::ToggleStatus);
        assert_eq!(
            click(
                &mut last,
                third + interval + Duration::from_millis(1),
                interval
            ),
            Action::ToggleStatus
        );
    }
}
