use serde::Serialize;

#[derive(Debug, Serialize)]
pub struct CommandError {
    pub code: &'static str,
    pub message: String,
    pub status: Option<u16>,
}

impl CommandError {
    pub fn network(message: impl Into<String>) -> Self {
        Self {
            code: "NETWORK_ERROR",
            message: message.into(),
            status: None,
        }
    }

    pub fn http(status: u16, message: impl Into<String>) -> Self {
        let code = match status {
            401 | 403 => "INVALID_CREDENTIALS",
            429 => "RATE_LIMITED",
            500..=599 => "KICKBASE_UNAVAILABLE",
            _ => "KICKBASE_HTTP_ERROR",
        };

        Self {
            code,
            message: message.into(),
            status: Some(status),
        }
    }

    pub fn session_expired() -> Self {
        Self {
            code: "SESSION_EXPIRED",
            message: "Deine Kickbase-Session ist abgelaufen. Bitte melde dich erneut an.".to_string(),
            status: Some(401),
        }
    }

    pub fn invalid_response(message: impl Into<String>) -> Self {
        Self {
            code: "INVALID_RESPONSE",
            message: message.into(),
            status: None,
        }
    }

    pub fn internal(message: impl Into<String>) -> Self {
        Self {
            code: "INTERNAL_ERROR",
            message: message.into(),
            status: None,
        }
    }
}
