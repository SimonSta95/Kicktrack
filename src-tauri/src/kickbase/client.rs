use std::time::Duration;

use reqwest::{header, StatusCode};
use serde_json::Value;

use super::{
    dto::{KickbaseLoginRequest, KickbaseLoginResponse},
    error::CommandError,
};

const KICKBASE_BASE_URL: &str = "https://api.kickbase.com";

pub struct KickbaseClient {
    http: reqwest::Client,
}

impl KickbaseClient {
    pub fn new() -> Result<Self, reqwest::Error> {
        let mut default_headers = header::HeaderMap::new();
        default_headers.insert(
            header::ACCEPT_LANGUAGE,
            header::HeaderValue::from_static("de-DE,de;q=0.9,en;q=0.5"),
        );

        let http = reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(10))
            .timeout(Duration::from_secs(20))
            .user_agent("KickTrack/0.2")
            .default_headers(default_headers)
            .build()?;

        Ok(Self { http })
    }

    pub async fn login(
        &self,
        email: &str,
        password: &str,
    ) -> Result<KickbaseLoginResponse, CommandError> {
        let payload = KickbaseLoginRequest {
            em: email,
            pass: password,
            loy: false,
            rep: serde_json::json!({}),
        };

        let response = self
            .http
            .post(format!("{KICKBASE_BASE_URL}/v4/user/login"))
            .header(header::ACCEPT, "application/json")
            .json(&payload)
            .send()
            .await
            .map_err(|error| CommandError::network(readable_network_error(&error)))?;

        let status = response.status();
        let body = response
            .text()
            .await
            .map_err(|_| CommandError::invalid_response("Kickbase hat eine unlesbare Antwort geliefert."))?;

        if !status.is_success() {
            return Err(CommandError::http(status.as_u16(), http_error_message(status, &body)));
        }

        serde_json::from_str::<KickbaseLoginResponse>(&body).map_err(|_| {
            CommandError::invalid_response(
                "Der Login war erfolgreich, aber die Kickbase-Antwort hatte ein unbekanntes Format.",
            )
        })
    }

    pub async fn get_json(&self, token: &str, path: &str) -> Result<Value, CommandError> {
        let response = self
            .http
            .get(format!("{KICKBASE_BASE_URL}{path}"))
            .header(header::ACCEPT, "application/json")
            .bearer_auth(token)
            .header(header::COOKIE, format!("kkstrauth={token}"))
            .send()
            .await
            .map_err(|error| CommandError::network(readable_network_error(&error)))?;

        let status = response.status();
        let body = response
            .text()
            .await
            .map_err(|_| CommandError::invalid_response("Kickbase hat eine unlesbare Antwort geliefert."))?;

        if !status.is_success() {
            if matches!(status, StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN) {
                return Err(CommandError::session_expired());
            }

            return Err(CommandError::http(status.as_u16(), http_error_message(status, &body)));
        }

        serde_json::from_str::<Value>(&body).map_err(|_| {
            CommandError::invalid_response("Kickbase hat JSON in einem unbekannten Format geliefert.")
        })
    }
    pub async fn get_bytes(&self, token: &str, path: &str) -> Result<Vec<u8>, CommandError> {
        let normalized = if path.starts_with('/') {
            path.to_string()
        } else {
            format!("/{path}")
        };

        let response = self
            .http
            .get(format!("{KICKBASE_BASE_URL}{normalized}"))
            .bearer_auth(token)
            .header(header::COOKIE, format!("kkstrauth={token}"))
            .send()
            .await
            .map_err(|error| CommandError::network(readable_network_error(&error)))?;

        let status = response.status();
        if !status.is_success() {
            if matches!(status, StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN) {
                return Err(CommandError::session_expired());
            }

            return Err(CommandError::http(
                status.as_u16(),
                "Ein Kickbase-Asset konnte nicht geladen werden.",
            ));
        }

        response
            .bytes()
            .await
            .map(|bytes| bytes.to_vec())
            .map_err(|_| CommandError::invalid_response("Ein Kickbase-Asset konnte nicht gelesen werden."))
    }

    pub async fn post_json(&self, token: &str, path: &str, payload: Option<Value>) -> Result<Value, CommandError> {
        let mut request = self.http.post(format!("{KICKBASE_BASE_URL}{path}"))
            .header(header::ACCEPT, "application/json")
            .bearer_auth(token)
            .header(header::COOKIE, format!("kkstrauth={token}"));
        if let Some(payload) = payload { request = request.json(&payload); }
        self.read_json_response(request.send().await.map_err(|error| CommandError::network(readable_network_error(&error)))?).await
    }

    pub async fn delete_json(&self, token: &str, path: &str) -> Result<Value, CommandError> {
        let response = self.http.delete(format!("{KICKBASE_BASE_URL}{path}"))
            .header(header::ACCEPT, "application/json")
            .bearer_auth(token)
            .header(header::COOKIE, format!("kkstrauth={token}"))
            .send().await.map_err(|error| CommandError::network(readable_network_error(&error)))?;
        self.read_json_response(response).await
    }

    async fn read_json_response(&self, response: reqwest::Response) -> Result<Value, CommandError> {
        let status = response.status();
        let body = response.text().await.map_err(|_| CommandError::invalid_response("Kickbase hat eine unlesbare Antwort geliefert."))?;
        if !status.is_success() {
            if matches!(status, StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN) { return Err(CommandError::session_expired()); }
            return Err(CommandError::http(status.as_u16(), http_error_message(status, &body)));
        }
        if body.trim().is_empty() { return Ok(Value::Null); }
        serde_json::from_str::<Value>(&body).or_else(|_| Ok(Value::String(body)))
    }

}

fn http_error_message(status: StatusCode, body: &str) -> String {
    if matches!(status, StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN) {
        return "Die Kickbase-Session ist nicht mehr gültig.".to_string();
    }

    if status == StatusCode::TOO_MANY_REQUESTS {
        return "Zu viele Anfragen an Kickbase. Bitte versuche es gleich erneut.".to_string();
    }

    if status.is_server_error() {
        return "Kickbase ist gerade nicht verfügbar.".to_string();
    }

    if let Ok(json) = serde_json::from_str::<Value>(body) {
        for key in ["message", "msg", "error"] {
            if let Some(message) = json.get(key).and_then(Value::as_str) {
                if !message.trim().is_empty() {
                    return message.to_string();
                }
            }
        }
    }

    format!("Kickbase hat die Anfrage abgelehnt (HTTP {}).", status.as_u16())
}

fn readable_network_error(error: &reqwest::Error) -> String {
    if error.is_timeout() {
        "Die Verbindung zu Kickbase hat zu lange gedauert.".to_string()
    } else if error.is_connect() {
        "Kickbase konnte nicht erreicht werden. Prüfe deine Internetverbindung.".to_string()
    } else {
        "Beim Verbinden mit Kickbase ist ein Netzwerkfehler aufgetreten.".to_string()
    }
}
