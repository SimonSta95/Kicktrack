use std::sync::Mutex;

use keyring::{Entry, Error as KeyringError};
use serde::{Deserialize, Serialize};

use crate::kickbase::{client::KickbaseClient, error::CommandError};

const KEYRING_SERVICE: &str = "KickTrack";
const KEYRING_ACCOUNT: &str = "kickbase-session";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KickbaseSession {
    pub token: String,
    pub token_expires_at: Option<serde_json::Value>,
    #[serde(default)]
    pub remembered: bool,
}

pub struct AppState {
    pub kickbase: KickbaseClient,
    pub session: Mutex<Option<KickbaseSession>>,
}

impl AppState {
    pub fn new() -> Result<Self, reqwest::Error> {
        Ok(Self {
            kickbase: KickbaseClient::new()?,
            session: Mutex::new(None),
        })
    }
}

fn credential_entry() -> Result<Entry, CommandError> {
    Entry::new(KEYRING_SERVICE, KEYRING_ACCOUNT)
        .map_err(|_| CommandError::internal("Der Windows Credential Manager konnte nicht geöffnet werden."))
}

pub fn save_persisted_session(session: &KickbaseSession) -> Result<(), CommandError> {
    let serialized = serde_json::to_string(session)
        .map_err(|_| CommandError::internal("Die Session konnte nicht für die sichere Speicherung vorbereitet werden."))?;

    credential_entry()?
        .set_password(&serialized)
        .map_err(|_| CommandError::internal("Die Session konnte nicht im Windows Credential Manager gespeichert werden."))
}

pub fn load_persisted_session() -> Result<Option<KickbaseSession>, CommandError> {
    let entry = credential_entry()?;

    match entry.get_password() {
        Ok(serialized) => {
            let mut session: KickbaseSession = serde_json::from_str(&serialized)
                .map_err(|_| CommandError::internal("Die gespeicherte Session ist ungültig."))?;
            session.remembered = true;
            Ok(Some(session))
        }
        Err(KeyringError::NoEntry) => Ok(None),
        Err(_) => Err(CommandError::internal(
            "Die gespeicherte Session konnte nicht aus dem Windows Credential Manager gelesen werden.",
        )),
    }
}

pub fn clear_persisted_session() -> Result<(), CommandError> {
    let entry = credential_entry()?;

    match entry.delete_credential() {
        Ok(()) | Err(KeyringError::NoEntry) => Ok(()),
        Err(_) => Err(CommandError::internal(
            "Die gespeicherte Session konnte nicht aus dem Windows Credential Manager entfernt werden.",
        )),
    }
}
