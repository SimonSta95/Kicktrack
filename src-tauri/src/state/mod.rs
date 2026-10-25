use std::{
    sync::{Arc, Mutex},
    time::{SystemTime, UNIX_EPOCH},
};

use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use keyring::{Entry, Error as KeyringError};
use serde::{Deserialize, Serialize};
use tokio::sync::Mutex as AsyncMutex;

use crate::kickbase::{client::KickbaseClient, error::CommandError};

const KEYRING_SERVICE: &str = "KickTrack";
const KEYRING_ACCOUNT: &str = "kickbase-session";
const EXPIRY_SAFETY_MARGIN_SECONDS: u64 = 5 * 60;
const FALLBACK_REFRESH_SECONDS: u64 = 6 * 24 * 60 * 60;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KickbaseSession {
    pub token: String,
    pub token_expires_at: Option<serde_json::Value>,
    #[serde(default)]
    pub remembered: bool,
    #[serde(default)]
    pub refresh_after_epoch: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoredCredentials {
    pub email: String,
    pub password: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PersistedAuth {
    pub session: KickbaseSession,
    #[serde(default)]
    pub credentials: Option<StoredCredentials>,
}

pub struct AppState {
    pub kickbase: KickbaseClient,
    pub player_request_limit: Arc<tokio::sync::Semaphore>,
    pub session: Mutex<Option<KickbaseSession>>,
    refresh_lock: AsyncMutex<()>,
}

impl AppState {
    pub fn new() -> Result<Self, reqwest::Error> {
        Ok(Self {
            kickbase: KickbaseClient::new()?,
            player_request_limit: Arc::new(tokio::sync::Semaphore::new(4)),
            session: Mutex::new(None),
            refresh_lock: AsyncMutex::new(()),
        })
    }

    pub async fn active_token(&self) -> Result<String, CommandError> {
        if let Some(token) = self.current_valid_token()? {
            return Ok(token);
        }

        let _refresh_guard = self.refresh_lock.lock().await;
        if let Some(token) = self.current_valid_token()? {
            return Ok(token);
        }

        let persisted = tauri::async_runtime::spawn_blocking(load_persisted_auth)
            .await
            .map_err(|_| {
                CommandError::internal("Die gespeicherte Session konnte nicht gelesen werden.")
            })??;
        let Some(mut persisted) = persisted else {
            self.clear_memory_session()?;
            return Err(CommandError::session_expired());
        };

        if !session_expires_soon(&persisted.session) {
            let token = persisted.session.token.clone();
            self.set_memory_session(persisted.session)?;
            return Ok(token);
        }

        let Some(credentials) = persisted.credentials.clone() else {
            self.clear_memory_session()?;
            tauri::async_runtime::spawn_blocking(clear_persisted_auth)
                .await
                .map_err(|_| {
                    CommandError::internal("Die abgelaufene Session konnte nicht entfernt werden.")
                })??;
            return Err(CommandError::session_expired());
        };

        let response = match self
            .kickbase
            .login(credentials.email.trim(), &credentials.password)
            .await
        {
            Ok(response) => response,
            Err(error) => {
                if matches!(error.code, "INVALID_CREDENTIALS" | "SESSION_EXPIRED") {
                    self.clear_memory_session()?;
                    let _ = tauri::async_runtime::spawn_blocking(clear_persisted_auth).await;
                }
                return Err(error);
            }
        };
        let session = KickbaseSession {
            token: response.tkn,
            token_expires_at: response.tknex,
            remembered: true,
            refresh_after_epoch: Some(default_refresh_after_epoch()),
        };
        persisted.session = session.clone();
        let persisted_for_keyring = persisted.clone();
        tauri::async_runtime::spawn_blocking(move || save_persisted_auth(&persisted_for_keyring))
            .await
            .map_err(|_| {
                CommandError::internal("Die erneuerte Session konnte nicht gespeichert werden.")
            })??;
        let token = session.token.clone();
        self.set_memory_session(session)?;
        Ok(token)
    }

    fn current_valid_token(&self) -> Result<Option<String>, CommandError> {
        let session = self.session.lock().map_err(|_| {
            CommandError::internal("Die lokale Session konnte nicht gelesen werden.")
        })?;
        Ok(session
            .as_ref()
            .filter(|value| !session_expires_soon(value))
            .map(|value| value.token.clone()))
    }

    pub fn set_memory_session(&self, value: KickbaseSession) -> Result<(), CommandError> {
        let mut session = self.session.lock().map_err(|_| {
            CommandError::internal("Die lokale Session konnte nicht aktualisiert werden.")
        })?;
        *session = Some(value);
        Ok(())
    }

    pub fn clear_memory_session(&self) -> Result<(), CommandError> {
        let mut session = self.session.lock().map_err(|_| {
            CommandError::internal("Die lokale Session konnte nicht beendet werden.")
        })?;
        *session = None;
        Ok(())
    }
}

fn credential_entry() -> Result<Entry, CommandError> {
    Entry::new(KEYRING_SERVICE, KEYRING_ACCOUNT).map_err(|_| {
        CommandError::internal("Der Windows Credential Manager konnte nicht geöffnet werden.")
    })
}

pub fn save_persisted_auth(auth: &PersistedAuth) -> Result<(), CommandError> {
    let serialized = serde_json::to_string(auth).map_err(|_| {
        CommandError::internal(
            "Die Session konnte nicht für die sichere Speicherung vorbereitet werden.",
        )
    })?;
    credential_entry()?.set_password(&serialized).map_err(|_| {
        CommandError::internal(
            "Die Session konnte nicht im Windows Credential Manager gespeichert werden.",
        )
    })
}

pub fn load_persisted_auth() -> Result<Option<PersistedAuth>, CommandError> {
    let entry = credential_entry()?;
    match entry.get_password() {
        Ok(serialized) => {
            if let Ok(auth) = serde_json::from_str::<PersistedAuth>(&serialized) {
                return Ok(Some(auth));
            }
            let mut session: KickbaseSession = serde_json::from_str(&serialized)
                .map_err(|_| CommandError::internal("Die gespeicherte Session ist ungültig."))?;
            session.remembered = true;
            Ok(Some(PersistedAuth {
                session,
                credentials: None,
            }))
        }
        Err(KeyringError::NoEntry) => Ok(None),
        Err(_) => Err(CommandError::internal(
            "Die gespeicherte Session konnte nicht aus dem Windows Credential Manager gelesen werden.",
        )),
    }
}

pub fn clear_persisted_auth() -> Result<(), CommandError> {
    let entry = credential_entry()?;
    match entry.delete_credential() {
        Ok(()) | Err(KeyringError::NoEntry) => Ok(()),
        Err(_) => Err(CommandError::internal(
            "Die gespeicherte Session konnte nicht aus dem Windows Credential Manager entfernt werden.",
        )),
    }
}

fn session_expires_soon(session: &KickbaseSession) -> bool {
    let Some(expires_at) = jwt_expiry_seconds(&session.token)
        .or_else(|| value_expiry_seconds(session.token_expires_at.as_ref()))
        .or(session.refresh_after_epoch)
    else {
        return true;
    };
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(u64::MAX);
    expires_at <= now.saturating_add(EXPIRY_SAFETY_MARGIN_SECONDS)
}

pub fn default_refresh_after_epoch() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs().saturating_add(FALLBACK_REFRESH_SECONDS))
        .unwrap_or(0)
}

fn jwt_expiry_seconds(token: &str) -> Option<u64> {
    let payload = token.split('.').nth(1)?;
    let bytes = URL_SAFE_NO_PAD.decode(payload).ok()?;
    serde_json::from_slice::<serde_json::Value>(&bytes)
        .ok()?
        .get("exp")?
        .as_u64()
}

fn value_expiry_seconds(value: Option<&serde_json::Value>) -> Option<u64> {
    match value? {
        serde_json::Value::Number(number) => normalize_epoch(number.as_u64()?),
        serde_json::Value::String(value) => {
            value.parse().ok().and_then(normalize_epoch).or_else(|| {
                time::OffsetDateTime::parse(value, &time::format_description::well_known::Rfc3339)
                    .ok()?
                    .unix_timestamp()
                    .try_into()
                    .ok()
            })
        }
        _ => None,
    }
}

fn normalize_epoch(value: u64) -> Option<u64> {
    if value >= 100_000_000_000 {
        Some(value / 1_000)
    } else {
        Some(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_expiry_from_jwt_payload() {
        let payload = URL_SAFE_NO_PAD.encode(br#"{"exp":4102444800}"#);
        assert_eq!(
            jwt_expiry_seconds(&format!("header.{payload}.signature")),
            Some(4_102_444_800)
        );
    }

    #[test]
    fn legacy_session_format_remains_deserializable() {
        let json = r#"{"token":"abc","token_expires_at":123,"remembered":true}"#;
        let session: KickbaseSession = serde_json::from_str(json).expect("legacy session");
        assert_eq!(session.token, "abc");
    }

    #[test]
    fn reads_numeric_and_rfc3339_expiry_values() {
        assert_eq!(
            value_expiry_seconds(Some(&serde_json::json!(4_102_444_800_000_u64))),
            Some(4_102_444_800)
        );
        assert_eq!(
            value_expiry_seconds(Some(&serde_json::json!("2100-01-01T00:00:00Z"))),
            Some(4_102_444_800)
        );
    }

    #[test]
    fn treats_sessions_without_any_expiry_as_expired() {
        assert!(session_expires_soon(&KickbaseSession {
            token: "opaque".to_string(),
            token_expires_at: None,
            remembered: false,
            refresh_after_epoch: None,
        }));
    }
}
