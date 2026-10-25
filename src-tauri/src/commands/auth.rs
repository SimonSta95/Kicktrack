use tauri::State;

use crate::{
    kickbase::{dto::SessionStatus, error::CommandError},
    state::{
        clear_persisted_auth, default_refresh_after_epoch, save_persisted_auth, AppState,
        KickbaseSession, PersistedAuth, StoredCredentials,
    },
};

#[tauri::command]
pub async fn login(
    email: String,
    password: String,
    remember: bool,
    state: State<'_, AppState>,
) -> Result<SessionStatus, CommandError> {
    let email = email.trim();
    if email.is_empty() || password.is_empty() {
        return Err(CommandError::http(
            400,
            "E-Mail und Passwort sind erforderlich.",
        ));
    }

    let response = state.kickbase.login(email, &password).await?;
    let expires_at = response.tknex.clone();
    let session = KickbaseSession {
        token: response.tkn,
        token_expires_at: expires_at.clone(),
        remembered: remember,
        refresh_after_epoch: Some(default_refresh_after_epoch()),
    };

    if remember {
        let persisted = PersistedAuth {
            session: session.clone(),
            credentials: Some(StoredCredentials {
                email: email.to_owned(),
                password,
            }),
        };
        tauri::async_runtime::spawn_blocking(move || save_persisted_auth(&persisted))
            .await
            .map_err(|_| {
                CommandError::internal("Die Session konnte nicht gespeichert werden.")
            })??;
    } else {
        tauri::async_runtime::spawn_blocking(clear_persisted_auth)
            .await
            .map_err(|_| {
                CommandError::internal(
                    "Eine alte gespeicherte Session konnte nicht entfernt werden.",
                )
            })??;
    }

    state.set_memory_session(session)?;
    Ok(SessionStatus {
        authenticated: true,
        token_expires_at: expires_at,
        remembered: remember,
    })
}

#[tauri::command]
pub async fn session_status(state: State<'_, AppState>) -> Result<SessionStatus, CommandError> {
    if let Err(error) = state.active_token().await {
        if matches!(error.code, "SESSION_EXPIRED" | "INVALID_CREDENTIALS") {
            return Ok(SessionStatus {
                authenticated: false,
                token_expires_at: None,
                remembered: false,
            });
        }
        return Err(error);
    }

    let session = state
        .session
        .lock()
        .map_err(|_| CommandError::internal("Die lokale Session konnte nicht gelesen werden."))?;
    let session = session.as_ref().ok_or_else(CommandError::session_expired)?;
    Ok(SessionStatus {
        authenticated: true,
        token_expires_at: session.token_expires_at.clone(),
        remembered: session.remembered,
    })
}

#[tauri::command]
pub fn logout(state: State<'_, AppState>) -> Result<(), CommandError> {
    state.clear_memory_session()?;
    clear_persisted_auth()
}
