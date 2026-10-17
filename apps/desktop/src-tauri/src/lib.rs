//! Monelyth desktop shell: opens the window and manages the local engine process.

mod engine;

use tauri::{Manager, RunEvent};

/// Starts the application and blocks until it exits.
///
/// # Panics
///
/// Panics if Tauri cannot build the application (for example, an invalid
/// `tauri.conf.json`), which is unrecoverable at startup.
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(
            tauri_plugin_log::Builder::new()
                .level(log::LevelFilter::Info)
                .timezone_strategy(tauri_plugin_log::TimezoneStrategy::UseLocal)
                .build(),
        )
        .plugin(tauri_plugin_shell::init())
        .manage(engine::EngineManager::default())
        .invoke_handler(tauri::generate_handler![engine::get_engine_status])
        .setup(|app| {
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
