//! Monelyth desktop shell: opens the window and manages the local engine process.

mod desktop;
mod engine;

use tauri::{Manager, RunEvent};
use tauri_plugin_autostart::MacosLauncher;
use tauri_plugin_window_state::StateFlags;

/// Starts the application and blocks until it exits.
///
/// # Panics
///
/// Panics if Tauri cannot build the application (for example, an invalid
/// `tauri.conf.json`), which is unrecoverable at startup.
pub fn run() {
    let app = tauri::Builder::default()
        // Must be first: a second launch hands over to the running app and exits before
        // anything else starts (a second engine would fight over the same database).
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            desktop::show_main_window(app);
        }))
        .plugin(
            tauri_plugin_log::Builder::new()
                .level(log::LevelFilter::Info)
                .timezone_strategy(tauri_plugin_log::TimezoneStrategy::UseLocal)
                .build(),
        )
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec![desktop::MINIMIZED_ARG]),
        ))
        .plugin(
            // Size, position and maximized state, but never visibility: when the window
            // appears is decided by `show_on_launch`.
            tauri_plugin_window_state::Builder::new()
                .with_state_flags(StateFlags::all() - StateFlags::VISIBLE)
                .build(),
        )
        .manage(engine::EngineManager::default())
        .invoke_handler(tauri::generate_handler![engine::get_engine_status])
        .on_window_event(desktop::on_window_event)
        .setup(|app| {
            desktop::create_tray(app.handle())?;
            desktop::show_on_launch(app.handle());
            engine::start(app.handle().clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the Tauri application");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            handle.state::<engine::EngineManager>().shutdown();
        }
    });
}
