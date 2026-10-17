//! Starts the Python engine as a sidecar process, tracks its status, and stops it with the app.
//!
//! Startup contract (the other half lives in `engine/src/monelyth_engine/__main__.py`):
//!
//! 1. The shell generates a random token and starts the engine with it in `MONELYTH_TOKEN`.
//! 2. The engine binds a loopback port and prints `MONELYTH_READY {"port": N, "version": "…"}`
//!    as its first and only line on stdout.
//! 3. The shell publishes the port and token to the webview, which calls the engine directly.
//! 4. On exit the shell writes `shutdown` to the engine's stdin and waits briefly before killing
//!    it. If the shell crashes, stdin closes and the engine exits on its own.

use std::fmt::Write as _;
use std::path::Path;
use std::sync::{Mutex, MutexGuard, PoisonError};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::{Command, CommandChild, CommandEvent};

/// Event emitted to the webview on every status change. Mirrored in `src/engine/status.ts`.
const STATUS_EVENT: &str = "engine-status";
/// Must match `bundle.externalBin` in `tauri.conf.json` (without the `binaries/` folder).
const SIDECAR_NAME: &str = "monelyth-engine";
const TOKEN_ENV_VAR: &str = "MONELYTH_TOKEN";
const READY_PREFIX: &str = "MONELYTH_READY ";
const TOKEN_BYTES: usize = 32;

/// Generous because a one-file executable unpacks itself before Python starts.
const STARTUP_TIMEOUT: Duration = Duration::from_secs(30);
const SHUTDOWN_GRACE: Duration = Duration::from_secs(3);
const SHUTDOWN_POLL_INTERVAL: Duration = Duration::from_millis(25);

/// The origin the bundled webview loads the UI from.
#[cfg(windows)]
const APP_ORIGIN: &str = "http://tauri.localhost";
#[cfg(not(windows))]
const APP_ORIGIN: &str = "tauri://localhost";

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(tag = "state", rename_all = "camelCase")]
pub enum EngineStatus {
    #[default]
    Starting,
    Ready {
        port: u16,
        token: String,
        version: String,
    },
    Failed {
        message: String,
    },
}

/// A status plus a sequence number that increases on every change, so the webview can order
/// snapshots that arrive through different channels (event vs. command response).
#[derive(Clone, Debug, Serialize)]
pub struct EngineSnapshot {
    seq: u64,
    #[serde(flatten)]
    status: EngineStatus,
}

#[derive(Debug, Deserialize, PartialEq, Eq)]
struct ReadyAnnouncement {
    port: u16,
    version: String,
}

/// Shared engine state, registered with `tauri::Builder::manage`.
#[derive(Default)]
pub struct EngineManager {
    inner: Mutex<Inner>,
}

#[derive(Default)]
struct Inner {
    seq: u64,
    status: EngineStatus,
    child: Option<CommandChild>,
    /// True from spawn until the process is known to have exited.
    running: bool,
    /// Set once the app starts exiting; an engine that stops after this is not a failure.
    stopping: bool,
}

impl EngineManager {
    fn lock(&self) -> MutexGuard<'_, Inner> {
        // Every update to `Inner` is a plain field assignment, so a panic elsewhere while the
        // lock was held cannot leave it half-updated. Recover instead of propagating poison.
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn snapshot(&self) -> EngineSnapshot {
        let inner = self.lock();
        EngineSnapshot {
            seq: inner.seq,
            status: inner.status.clone(),
        }
    }

    fn publish(&self, app: &AppHandle, status: EngineStatus) {
        let snapshot = {
            let mut inner = self.lock();
            inner.seq += 1;
            inner.status = status;
            EngineSnapshot {
                seq: inner.seq,
                status: inner.status.clone(),
            }
        };
        if let Err(error) = app.emit(STATUS_EVENT, &snapshot) {
            log::error!("Could not send the engine status to the window: {error}");
        }
    }

    /// Keep the spawned process. Hands it back if the app is already exiting.
    fn attach(&self, child: CommandChild) -> Result<(), CommandChild> {
        let mut inner = self.lock();
        if inner.stopping {
            return Err(child);
        }
        inner.child = Some(child);
        inner.running = true;
        Ok(())
    }

    /// Record that the process exited. Returns whether the exit was requested by the app.
    fn mark_exited(&self) -> bool {
        let mut inner = self.lock();
        inner.running = false;
        inner.child = None;
        inner.stopping
    }

    fn kill(&self) {
        let child = {
            let mut inner = self.lock();
            inner.running = false;
            inner.child.take()
        };
        if let Some(child) = child
            && let Err(error) = child.kill()
        {
            log::error!("Could not stop the engine process: {error}");
        }
    }

    /// Stop the engine: ask it to exit cleanly, then kill it if it is still running after
    /// [`SHUTDOWN_GRACE`]. Blocks the calling thread for at most that long.
    pub fn shutdown(&self) {
        let child = {
            let mut inner = self.lock();
            inner.stopping = true;
            inner.child.take()
        };
        let Some(mut child) = child else {
            return;
        };

        if let Err(error) = child.write(b"shutdown\n") {
            log::warn!("Could not ask the engine to shut down: {error}");
        }
        let deadline = Instant::now() + SHUTDOWN_GRACE;
        while self.lock().running && Instant::now() < deadline {
            std::thread::sleep(SHUTDOWN_POLL_INTERVAL);
        }
        if self.lock().running {
            log::warn!(
                "The engine did not stop within {} seconds; killing it",
                SHUTDOWN_GRACE.as_secs()
            );
            if let Err(error) = child.kill() {
                log::error!("Could not stop the engine process: {error}");
            }
        }
    }
}

/// Returns the current engine status. The webview calls this once on load and then follows
/// the `engine-status` event.
#[tauri::command]
#[allow(
    clippy::needless_pass_by_value,
    reason = "Tauri passes command state by value"
)]
pub fn get_engine_status(manager: State<'_, EngineManager>) -> EngineSnapshot {
    manager.snapshot()
}

/// Launches the engine in the background and supervises it for the life of the app.
pub fn start(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        if let Err(message) = supervise(&app).await {
            log::error!("Engine failed: {message}");
            app.state::<EngineManager>()
                .publish(&app, EngineStatus::Failed { message });
        }
    });
}

/// Runs until the engine exits. Returns `Ok` only for an exit the app asked for.
async fn supervise(app: &AppHandle) -> Result<(), String> {
    let manager = app.state::<EngineManager>();
    let token = generate_token()?;
    let (mut events, child) = build_command(app, &token)?
        .spawn()
        .map_err(|error| format!("Could not start the engine ({error})."))?;

    if let Err(child) = manager.attach(child) {
        // The app began exiting while the engine was being launched.
        if let Err(error) = child.kill() {
            log::error!("Could not stop the engine process: {error}");
        }
        return Ok(());
    }

    let startup_deadline = tokio::time::sleep(STARTUP_TIMEOUT);
    tokio::pin!(startup_deadline);
    let mut ready = false;

    loop {
        tokio::select! {
            event = events.recv() => {
                let Some(event) = event else {
                    return if manager.mark_exited() {
                        Ok(())
                    } else {
                        Err("Lost contact with the engine.".to_owned())
                    };
                };
                match event {
                    CommandEvent::Stdout(bytes) => {
                        let line = String::from_utf8_lossy(&bytes);
                        let line = line.trim_end();
                        if ready {
                            log::warn!("Unexpected engine output: {line}");
                            continue;
                        }
                        match parse_ready_line(line) {
                            Ok(announcement) => {
                                ready = true;
                                log::info!(
                                    "Engine {} is ready on port {}",
                                    announcement.version,
                                    announcement.port
                                );
                                manager.publish(
                                    app,
                                    EngineStatus::Ready {
                                        port: announcement.port,
                                        token: token.clone(),
                                        version: announcement.version,
                                    },
                                );
                            }
                            Err(message) => {
                                manager.kill();
                                return Err(message);
                            }
                        }
                    }
                    CommandEvent::Stderr(bytes) => {
                        log::info!(
                            target: "monelyth_engine",
                            "{}",
                            String::from_utf8_lossy(&bytes).trim_end()
                        );
                    }
                    CommandEvent::Error(error) => {
                        log::error!("Error reading engine output: {error}");
                    }
                    CommandEvent::Terminated(payload) => {
                        if manager.mark_exited() {
                            return Ok(());
                        }
                        return Err(describe_exit(payload.code, ready));
                    }
                    _ => {}
                }
            }
            () = &mut startup_deadline, if !ready => {
                manager.kill();
                return Err(format!(
                    "The engine did not start within {} seconds.",
                    STARTUP_TIMEOUT.as_secs()
                ));
            }
        }
    }
}

fn build_command(app: &AppHandle, token: &str) -> Result<Command, String> {
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("Could not find the app data folder ({error})."))?;

    let command = if tauri::is_dev() {
        dev_command(app)
    } else {
        app.shell()
            .sidecar(SIDECAR_NAME)
            .map_err(|error| format!("Could not find the engine program ({error})."))?
    };

    let mut command = command
        .arg("--data-dir")
        .arg(data_dir)
        .arg("--exit-on-stdin-eof")
        .env(TOKEN_ENV_VAR, token);
    for origin in allowed_origins(app) {
        command = command.arg("--allowed-origin").arg(origin);
    }
    Ok(command)
}

/// During `tauri dev`, run the engine from source with `uv` so Python changes take effect on
/// the next launch without rebuilding the sidecar executable.
fn dev_command(app: &AppHandle) -> Command {
    let engine_dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../engine");
    app.shell()
        .command("uv")
        .arg("run")
        .arg("--project")
        .arg(engine_dir)
        .args(["--frozen", "--quiet", "monelyth-engine"])
}

/// The only origin allowed to call the engine: the dev server during `tauri dev`, otherwise
/// the bundled app's own origin.
fn allowed_origins(app: &AppHandle) -> Vec<String> {
    let dev_origin = tauri::is_dev()
        .then(|| app.config().build.dev_url.as_ref())
        .flatten()
        .map(|url| url.origin().ascii_serialization());
    vec![dev_origin.unwrap_or_else(|| APP_ORIGIN.to_owned())]
}

fn generate_token() -> Result<String, String> {
    let mut bytes = [0_u8; TOKEN_BYTES];
    getrandom::fill(&mut bytes)
        .map_err(|error| format!("Could not generate a security token ({error})."))?;
    let mut hex = String::with_capacity(TOKEN_BYTES * 2);
    for byte in bytes {
        // Writing to a `String` cannot fail.
        let _ = write!(hex, "{byte:02x}");
    }
    Ok(hex)
}

fn parse_ready_line(line: &str) -> Result<ReadyAnnouncement, String> {
    let payload = line
        .strip_prefix(READY_PREFIX)
        .ok_or_else(|| format!("The engine sent an unexpected message while starting: {line:?}"))?;
    let announcement: ReadyAnnouncement = serde_json::from_str(payload)
        .map_err(|error| format!("The engine's ready message was malformed ({error})."))?;
    if announcement.port == 0 {
        return Err("The engine reported an invalid port.".to_owned());
    }
    Ok(announcement)
}

fn describe_exit(code: Option<i32>, ready: bool) -> String {
    let when = if ready {
        "unexpectedly"
    } else {
        "while starting"
    };
    match code {
        Some(code) => format!("The engine stopped {when} (exit code {code})."),
        None => format!("The engine stopped {when}."),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_ready_line() {
        let announcement =
            parse_ready_line(r#"MONELYTH_READY {"port": 51234, "version": "0.1.0"}"#).unwrap();

        assert_eq!(
            announcement,
            ReadyAnnouncement {
                port: 51234,
                version: "0.1.0".to_owned()
            }
        );
    }

    #[test]
    fn rejects_other_first_lines() {
        let error = parse_ready_line("Traceback (most recent call last):").unwrap_err();

        assert!(error.contains("unexpected message"), "{error}");
    }

    #[test]
    fn rejects_malformed_ready_payloads() {
        for line in [
            "MONELYTH_READY ",
            "MONELYTH_READY not-json",
            r#"MONELYTH_READY {"port": "51234", "version": "0.1.0"}"#,
            r#"MONELYTH_READY {"port": 70000, "version": "0.1.0"}"#,
            r#"MONELYTH_READY {"version": "0.1.0"}"#,
        ] {
            let error = parse_ready_line(line).unwrap_err();
            assert!(error.contains("malformed"), "{line}: {error}");
        }
    }

    #[test]
    fn rejects_port_zero() {
        let error =
            parse_ready_line(r#"MONELYTH_READY {"port": 0, "version": "0.1.0"}"#).unwrap_err();

        assert!(error.contains("invalid port"), "{error}");
    }

    #[test]
    fn tokens_are_random_lowercase_hex() {
        let first = generate_token().unwrap();
        let second = generate_token().unwrap();

        assert_eq!(first.len(), TOKEN_BYTES * 2);
        assert!(
            first
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        );
        assert_ne!(first, second);
    }

    #[test]
    fn snapshot_json_matches_the_webview_contract() {
        let ready = EngineSnapshot {
            seq: 3,
            status: EngineStatus::Ready {
                port: 51234,
                token: "abc".to_owned(),
                version: "0.1.0".to_owned(),
            },
        };
        let failed = EngineSnapshot {
            seq: 4,
            status: EngineStatus::Failed {
                message: "boom".to_owned(),
            },
        };
        let starting = EngineSnapshot {
            seq: 0,
            status: EngineStatus::Starting,
        };

        assert_eq!(
            serde_json::to_value(ready).unwrap(),
            serde_json::json!({"seq": 3, "state": "ready", "port": 51234, "token": "abc", "version": "0.1.0"})
        );
        assert_eq!(
            serde_json::to_value(failed).unwrap(),
            serde_json::json!({"seq": 4, "state": "failed", "message": "boom"})
        );
        assert_eq!(
            serde_json::to_value(starting).unwrap(),
            serde_json::json!({"seq": 0, "state": "starting"})
        );
    }

    #[test]
    fn describes_exits() {
        assert_eq!(
            describe_exit(Some(1), false),
            "The engine stopped while starting (exit code 1)."
        );
        assert_eq!(
            describe_exit(None, true),
            "The engine stopped unexpectedly."
        );
    }
}
