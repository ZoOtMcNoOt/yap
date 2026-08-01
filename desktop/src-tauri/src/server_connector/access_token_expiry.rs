//! Reading an access token's own lifetime.
//!
//! Kept apart from any one provider because it is neither Windows-specific nor
//! broker-specific: every adapter behind the token seam has to answer "when
//! does this expire", and the answer is always the token's `exp` claim. Living
//! here also means these tests run on any host, which matters for a
//! hand-written parser.

/// The token's own `exp` claim, which is authoritative and always present on
/// an Entra access token. WAM also exposes an `expiresOn` response property,
/// but it is optional and provider-specific, so trusting it would make caching
/// depend on a detail we cannot verify without a live tenant. The claim can be
/// checked offline.
///
/// Zero on failure. The connector caches only while
/// `expires_at_unix_seconds > now + margin`, so zero means "re-acquire every
/// time": slow and safe, rather than serving a token whose lifetime is unknown.
pub(super) fn expiry_from_token(token: &str) -> u64 {
    let Some(payload) = token.split('.').nth(1) else {
        return 0;
    };
    let Some(decoded) = decode_base64url(payload) else {
        return 0;
    };
    serde_json::from_slice::<serde_json::Value>(&decoded)
        .ok()
        .and_then(|claims| claims.get("exp").and_then(serde_json::Value::as_u64))
        .unwrap_or(0)
}

/// JWT payloads are base64url without padding. Hand-rolled rather than adding a
/// dependency for twenty lines, which would also mean regenerating the
/// byte-compared shipped dependency inventory.
fn decode_base64url(value: &str) -> Option<Vec<u8>> {
    let mut out = Vec::with_capacity(value.len() * 3 / 4);
    let mut accumulator: u32 = 0;
    let mut bits: u32 = 0;
    for byte in value.bytes() {
        let sextet = match byte {
            b'A'..=b'Z' => byte - b'A',
            b'a'..=b'z' => byte - b'a' + 26,
            b'0'..=b'9' => byte - b'0' + 52,
            b'-' => 62,
            b'_' => 63,
            b'=' => break,
            _ => return None,
        } as u32;
        accumulator = (accumulator << 6) | sextet;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push((accumulator >> bits) as u8);
        }
    }
    // Leftover bits must be zero padding; anything else is a malformed payload
    // rather than a short one.
    if bits > 0 && (accumulator & ((1 << bits) - 1)) != 0 {
        return None;
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    // Real Entra shape: three dot-separated parts, unpadded base64url payload.
    const SAMPLE_TOKEN: &str =
        "eyJhbGciOiJSUzI1NiJ9.eyJleHAiOjE3ODU1NTE4NDAsImF1ZCI6ImFwaTovL3lhcCIsInRpZCI6InQifQ.c2ln";

    #[test]
    fn the_expiry_comes_from_the_token_claim() {
        assert_eq!(expiry_from_token(SAMPLE_TOKEN), 1_785_551_840);
    }

    // Every one of these must yield zero rather than a wrong lifetime: the
    // connector caches while expiry is in the future, so a fabricated value
    // would keep serving a token nobody can vouch for.
    #[test]
    fn an_unreadable_token_reports_no_lifetime_rather_than_guessing() {
        assert_eq!(expiry_from_token(""), 0);
        assert_eq!(expiry_from_token("notajwt"), 0);
        assert_eq!(expiry_from_token("header.!!!invalid!!!.sig"), 0);
        assert_eq!(
            expiry_from_token("header.eyJhIjoxfQ.sig"),
            0,
            "no exp claim"
        );
        assert_eq!(
            expiry_from_token("header.eyJleHAiOiJub3QtYS1udW1iZXIifQ.sig"),
            0,
            "exp present but not a number"
        );
    }

    #[test]
    fn base64url_decodes_the_unpadded_url_alphabet() {
        assert_eq!(decode_base64url("").unwrap(), b"");
        assert_eq!(decode_base64url("QQ").unwrap(), b"A");
        assert_eq!(decode_base64url("QUI").unwrap(), b"AB");
        assert_eq!(decode_base64url("QUJD").unwrap(), b"ABC");
        // 0xFB 0xFF exercises the two characters standard base64 spells + and /
        assert_eq!(decode_base64url("-_8").unwrap(), vec![0xfb, 0xff]);
        assert!(decode_base64url("has space").is_none());
        assert!(decode_base64url("plus+slash/").is_none());
    }
}
