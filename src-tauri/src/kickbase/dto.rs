use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionStatus {
    pub authenticated: bool,
    pub token_expires_at: Option<serde_json::Value>,
    pub remembered: bool,
}

#[derive(Debug, Deserialize)]
pub struct KickbaseLoginResponse {
    pub tkn: String,
    #[serde(default)]
    pub tknex: Option<serde_json::Value>,
}

#[derive(Debug, Serialize)]
pub struct KickbaseLoginRequest<'a> {
    pub em: &'a str,
    pub pass: &'a str,
    pub loy: bool,
    pub rep: serde_json::Value,
}
