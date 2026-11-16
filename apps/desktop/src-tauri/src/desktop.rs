//! Behaviour that makes Monelyth feel like a Windows app rather than a page in a window:
//! a tray icon, keeping running in the tray when the window is closed (if the user wants
//! that), starting quietly at sign-in, and focusing the open window when the app is launched
//! a second time.
//!
//! The user's choices live in the `preferences.json` store, which the Settings screen edits
//! through `@tauri-apps/plugin-store`; Rust only reads them.

use std::sync::atomic::{AtomicBool, Ordering};

use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, Runtime, Window, WindowEvent};
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_store::StoreExt;

/// The window defined in `tauri.conf.json`.
pub const MAIN_WINDOW: &str = "main";
/// Passed by the "start at sign-in" entry, so Monelyth starts in the tray, not on screen.
pub const MINIMIZED_ARG: &str = "--minimized";
/// Shared with the Settings screen (`src/screens/settings/desktopPreferences.ts`).
pub const PREFERENCES_STORE: &str = "preferences.json";
/// `true`: closing the window hides it and Monelyth keeps running in the tray.
pub const CLOSE_TO_TRAY_KEY: &str = "closeToTray";
/// Event that asks the webview to open a route, e.g. `"/import"` from the tray menu.
pub const NAVIGATE_EVENT: &str = "navigate";

const TRAY_ID: &str = "main";
const MENU_OPEN: &str = "open";
const MENU_IMPORT: &str = "import";
const MENU_QUIT: &str = "quit";

/// Set once the "still running in the tray" notice has been shown this session.
static TRAY_NOTICE_SHOWN: AtomicBool = AtomicBool::new(false);

/// Builds the tray icon and its menu. Call once from `setup`.
///
/// # Errors
///
/// Returns an error if the menu or tray icon can't be created.
pub fn create_tray<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, MENU_OPEN, "Open Monelyth", true, None::<&str>)?;
    let import = MenuItem::with_id(
        app,
        MENU_IMPORT,
        "Import a statement\u{2026}",
        true,
        None::<&str>,
    )?;
    let separator = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(app, MENU_QUIT, "Quit Monelyth", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &import, &separator, &quit])?;

    let mut tray = TrayIconBuilder::with_id(TRAY_ID)
        .tooltip("Monelyth")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            MENU_OPEN => show_main_window(app),
            MENU_IMPORT => {
                show_main_window(app);
                if let Err(error) = app.emit(NAVIGATE_EVENT, "/import") {
                    log::error!("Could not open the Import screen: {error}");
                }
            }
            MENU_QUIT => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_main_window(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}

/// Shows the window unless Monelyth was started at sign-in, in which case it stays in the tray.
///
/// The window is created hidden (`"visible": false` in `tauri.conf.json`) so the window-state
/// plugin can restore its size and position first, without it flashing in the default place.
pub fn show_on_launch<R: Runtime>(app: &AppHandle<R>) {
    if std::env::args().any(|arg| arg == MINIMIZED_ARG) {
        log::info!("Started at sign-in; staying in the tray");
    } else {
        show_main_window(app);
    }
}

/// Brings the main window to the front, restoring it if it was hidden or minimized.
pub fn show_main_window<R: Runtime>(app: &AppHandle<R>) {
    let Some(window) = app.get_webview_window(MAIN_WINDOW) else {
        log::error!("The main window is missing");
        return;
    };
    for (action, result) in [
        ("unminimize", window.unminimize()),
        ("show", window.show()),
        ("focus", window.set_focus()),
    ] {
        if let Err(error) = result {
            log::warn!("Could not {action} the window: {error}");
        }
    }
}

/// Window events: closing hides to the tray when the user chose that, otherwise it quits.
pub fn on_window_event<R: Runtime>(window: &Window<R>, event: &WindowEvent) {
    if window.label() != MAIN_WINDOW {
        return;
    }
    match event {
        WindowEvent::CloseRequested { api, .. } if close_to_tray(window.app_handle()) => {
            api.prevent_close();
            if let Err(error) = window.hide() {
                log::error!("Could not hide the window: {error}");
                return;
            }
            notify_still_running(window.app_handle());
        }
        // Keeping running in the tray only ever hides the window, so once it is actually
        // destroyed the user has closed the app: quit explicitly, so nothing (such as the
        // tray icon) can keep the process and its engine alive without a window.
        WindowEvent::Destroyed => window.app_handle().exit(0),
        _ => {}
    }
}

fn close_to_tray<R: Runtime>(app: &AppHandle<R>) -> bool {
    match app.store(PREFERENCES_STORE) {
        Ok(store) => store
            .get(CLOSE_TO_TRAY_KEY)
            .and_then(|value| value.as_bool())
            .unwrap_or(false),
        Err(error) => {
            log::warn!("Could not read preferences; closing normally: {error}");
            false
        }
    }
}

/// Tells the user once per session where the app went, so closing never looks like a crash.
fn notify_still_running<R: Runtime>(app: &AppHandle<R>) {
    if TRAY_NOTICE_SHOWN.swap(true, Ordering::Relaxed) {
        return;
    }
    if let Err(error) = app
        .notification()
        .builder()
        .title("Monelyth is still running")
        .body("It's in the system tray. Right-click the icon to quit.")
        .show()
    {
        log::warn!("Could not show the tray notice: {error}");
    }
}
