use super::error::CommandError;

pub fn api_id(value: &str, label: &str) -> Result<String, CommandError> {
    let value = value.trim();
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
    {
        return Err(CommandError::http(400, format!("{label} ist ungültig.")));
    }
    Ok(value.to_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_common_ids_and_rejects_path_fragments() {
        assert_eq!(
            api_id(" abc-123_def ", "ID").expect("valid id"),
            "abc-123_def"
        );
        assert!(api_id("../players?all=true", "ID").is_err());
        assert!(api_id("", "ID").is_err());
    }
}
