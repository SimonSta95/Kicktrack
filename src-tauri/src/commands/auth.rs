use tauri::State;

use crate::{
    kickbase::{dto::SessionStatus, error::CommandError},
    state::{
        clear_persisted_session, load_persisted_session, save_persisted_session, AppState,
        KickbaseSession,
    },
};

#[tauri::command]
pub async fn login(
    email: String,
    password: String,
    remember: bool,
    state: State<'_, AppState>,
) -> Result<SessionStatus, CommandError> {
    if email.trim().is_empty() || password.is_empty() {
        return Err(CommandError::http(400, "E-Mail und Passwort sind erforderlich."));
    }

    let response = state.kickbase.login(email.trim(), &password).await?;
    let expires_at = response.tknex.clone();

    let session_value = KickbaseSession {
        token: response.tkn,
        token_expires_at: expires_at.clone(),
        remembered: remember,
    };

    // Persist only the authenticated Kickbase session. The user's password never leaves this
    // command except for the actual login request and is never written to disk.
    if remember {
        save_persisted_session(&session_value)?;
    } else {
        // A successful non-persistent login explicitly replaces any previously remembered session.
        clear_persisted_session()?;
    }

    let mut session = state
        .session
        .lock()
        .map_err(|_| CommandError::internal("Die lokale Session konnte nicht aktualisiert werden."))?;

    *session = Some(session_value);

    Ok(SessionStatus {
        authenticated: true,
        token_expires_at: expires_at,
        remembered: remember,
    })
}

#[tauri::command]
pub async fn session_status(state: State<'_, AppState>) -> Result<SessionStatus, CommandError> {
    // Fast path: an in-memory session never touches the Windows Credential Manager.
    {
        let session = state
            .session
            .lock()
            .map_err(|_| CommandError::internal("Die lokale Session konnte nicht gelesen werden."))?;
        if let Some(session) = session.as_ref() {
            return Ok(SessionStatus {
                authenticated: true,
                token_expires_at: session.token_expires_at.clone(),
                remembered: session.remembered,
            });
        }
    }

    // Windows Credential Manager access is blocking I/O. Keep it off Tauri's
    // command thread so the WebView can paint the startup UI immediately.
    let persisted = tauri::async_runtime::spawn_blocking(load_persisted_session)
        .await
        .map_err(|_| CommandError::internal("Die gespeicherte Session konnte nicht gelesen werden."))??;

    if let Some(persisted) = persisted {
        let status = SessionStatus {
            authenticated: true,
            token_expires_at: persisted.token_expires_at.clone(),
            remembered: true,
        };
        let mut session = state
            .session
            .lock()
            .map_err(|_| CommandError::internal("Die lokale Session konnte nicht aktualisiert werden."))?;
        *session = Some(persisted);
        return Ok(status);
    }

    Ok(SessionStatus { authenticated: false, token_expires_at: None, remembered: false })
}

#[tauri::command]
pub fn logout(state: State<'_, AppState>) -> Result<(), CommandError> {
    {
        let mut session = state
            .session
            .lock()
            .map_err(|_| CommandError::internal("Die lokale Session konnte nicht beendet werden."))?;
        *session = None;
    }

    clear_persisted_session()?;
    Ok(())
}
