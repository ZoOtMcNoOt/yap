//! Signs the desktop in as a demo user against the loopback demo identity
//! provider in `demo/`.
//!
//! This exists so the client can be driven as Alice and as Bob before IT issues
//! an app registration. It talks to a synthetic issuer over plain loopback HTTP
//! and holds a client secret that is published in this repository, so it must
//! never exist in a shipped binary.
//!
//! That is enforced by construction rather than by configuration: the whole
//! module is behind `debug_assertions`, so release builds do not contain it. An
//! environment variable would not be enough — a variable can be set on a
//! binary someone already has, and this one would mint tokens for anybody who
//! could reach the issuer.

use std::time::Duration;

use super::access_token_expiry::expiry_from_token;
use super::config::MicrosoftEntraSettings;
use super::native_access_token_provider::{
    NativeAccessTokenGrant, NativeAccessTokenProvider, NativeAccessTokenProviderError,
    NativeAccessTokenSession, NativeProviderFuture,
};

/// Must match `demo/run-demo-identity-provider.py`. The duplication is real but
/// unavoidable: these sit on opposite sides of an HTTP boundary, and the demo
/// provider has to keep working when this binary is not present.
const ISSUER_ID: &str = "yap-phase7";
const CLIENT_ID: &str = "00000000-0000-4000-8000-000000000074";
const CLIENT_SECRET: &str = "synthetic-client-secret";
const REDIRECT_URI: &str = "http://127.0.0.1/yap-demo-callback";
const DEFAULT_PROVIDER_BASE_URL: &str = "http://127.0.0.1:18790";
const REQUEST_TIMEOUT: Duration = Duration::from_secs(5);

pub(super) struct DemoAccessTokenProvider {
    identity: String,
    base_url: String,
}

impl DemoAccessTokenProvider {
    /// `None` unless an operator names an identity, so an ordinary debug build
    /// still behaves like production and finds no provider.
    pub(super) fn from_environment() -> Option<Self> {
        let identity = std::env::var("YAP_DEMO_TOKEN_PROVIDER").ok()?;
        if identity.is_empty() {
            return None;
        }
        let base_url = std::env::var("YAP_DEMO_IDENTITY_PROVIDER_URL")
            .unwrap_or_else(|_| DEFAULT_PROVIDER_BASE_URL.to_string());
        // Loopback only. A demo adapter pointed at a routable host would accept
        // tokens minted by whoever owns that host.
        if !is_loopback_origin(&base_url) {
            return None;
        }
        Some(Self {
            identity,
            base_url: base_url.trim_end_matches('/').to_string(),
        })
    }

    async fn acquire(&self) -> Result<NativeAccessTokenGrant, NativeAccessTokenProviderError> {
        let client = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(REQUEST_TIMEOUT)
            .build()
            .map_err(|_| NativeAccessTokenProviderError::UNAVAILABLE)?;

        let code = self.authorization_code(&client).await?;
        let token = self.exchange(&client, &code).await?;
        let expires_at_unix_seconds = expiry_from_token(&token);
        Ok(NativeAccessTokenGrant {
            access_token: zeroize::Zeroizing::new(token),
            expires_at_unix_seconds,
            account_id: self.identity.clone(),
        })
    }

    /// The code arrives in a redirect that must not be followed; the client is
    /// built with redirects disabled so the `Location` header survives.
    async fn authorization_code(
        &self,
        client: &reqwest::Client,
    ) -> Result<String, NativeAccessTokenProviderError> {
        let url = format!(
            "{}/{ISSUER_ID}/authorize?client_id={CLIENT_ID}&response_type=code\
             &redirect_uri={REDIRECT_URI}&scope=openid+access_as_user&state=yap-demo",
            self.base_url
        );
        let response = client
            .get(&url)
            .send()
            .await
            .map_err(|_| NativeAccessTokenProviderError::NETWORK)?;
        let location = response
            .headers()
            .get(reqwest::header::LOCATION)
            .and_then(|value| value.to_str().ok())
            .ok_or(NativeAccessTokenProviderError::CONFIGURATION)?;
        code_from_redirect(location).ok_or(NativeAccessTokenProviderError::CONFIGURATION)
    }

    async fn exchange(
        &self,
        client: &reqwest::Client,
        code: &str,
    ) -> Result<String, NativeAccessTokenProviderError> {
        let response = client
            .post(format!("{}/{ISSUER_ID}/token", self.base_url))
            .header(
                reqwest::header::CONTENT_TYPE,
                "application/x-www-form-urlencoded",
            )
            // reqwest's `form` helper needs a feature this build does not
            // enable, so the body is encoded through Url rather than by
            // widening the dependency for one request.
            .body(encoded_form(&[
                ("grant_type", "authorization_code"),
                ("client_id", CLIENT_ID),
                ("client_secret", CLIENT_SECRET),
                ("redirect_uri", REDIRECT_URI),
                ("code", code),
                // Selects which demo user the provider mints for.
                ("fixture", self.identity.as_str()),
            ]))
            .send()
            .await
            .map_err(|_| NativeAccessTokenProviderError::NETWORK)?;
        if !response.status().is_success() {
            // An unknown identity is a configuration mistake, not a transient
            // failure, so it must not be retried.
            return Err(NativeAccessTokenProviderError::CONFIGURATION);
        }
        // `json()` is behind another disabled reqwest feature; parsing the text
        // keeps the dependency surface where it is.
        let text = response
            .text()
            .await
            .map_err(|_| NativeAccessTokenProviderError::INVALID_SESSION)?;
        let body: serde_json::Value = serde_json::from_str(&text)
            .map_err(|_| NativeAccessTokenProviderError::INVALID_SESSION)?;
        body.get("access_token")
            .and_then(serde_json::Value::as_str)
            .filter(|token| !token.is_empty())
            .map(str::to_string)
            .ok_or(NativeAccessTokenProviderError::INVALID_SESSION)
    }
}

fn encoded_form(pairs: &[(&str, &str)]) -> String {
    let mut url = reqwest::Url::parse("http://form.invalid/").expect("static base parses");
    url.query_pairs_mut().extend_pairs(pairs.iter().copied());
    url.query().unwrap_or_default().to_string()
}

fn is_loopback_origin(base_url: &str) -> bool {
    let Ok(url) = reqwest::Url::parse(base_url) else {
        return false;
    };
    url.scheme() == "http"
        && matches!(
            url.host_str(),
            Some("127.0.0.1") | Some("localhost") | Some("[::1]")
        )
}

fn code_from_redirect(location: &str) -> Option<String> {
    // The redirect target is not a URL this process resolves, so parse against
    // a base rather than requiring it to be absolute.
    let base = reqwest::Url::parse("http://127.0.0.1/").ok()?;
    let parsed = base.join(location).ok()?;
    parsed
        .query_pairs()
        .find(|(key, _)| key == "code")
        .map(|(_, value)| value.into_owned())
        .filter(|code| !code.is_empty())
}

impl NativeAccessTokenProvider for DemoAccessTokenProvider {
    fn acquire_silent<'a>(
        &'a self,
        _settings: &'a MicrosoftEntraSettings,
    ) -> NativeProviderFuture<'a, NativeAccessTokenGrant> {
        // The demo issuer needs no prior interaction, so silent acquisition is
        // the whole flow. Sign-in is the same call.
        Box::pin(self.acquire())
    }

    fn sign_in_interactively<'a>(
        &'a self,
        _settings: &'a MicrosoftEntraSettings,
        _parent_window_handle: Option<u64>,
    ) -> NativeProviderFuture<'a, NativeAccessTokenGrant> {
        Box::pin(self.acquire())
    }

    fn session_status<'a>(
        &'a self,
        _settings: &'a MicrosoftEntraSettings,
    ) -> NativeProviderFuture<'a, NativeAccessTokenSession> {
        let identity = self.identity.clone();
        Box::pin(async move {
            Ok(NativeAccessTokenSession {
                account_id: Some(identity),
            })
        })
    }

    fn sign_out<'a>(
        &'a self,
        _settings: &'a MicrosoftEntraSettings,
    ) -> NativeProviderFuture<'a, ()> {
        Box::pin(async move { Ok(()) })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // The guard that keeps this from becoming a token oracle. A routable issuer
    // would let whoever owns that host mint identities for this client.
    #[test]
    fn only_loopback_origins_are_accepted() {
        assert!(is_loopback_origin("http://127.0.0.1:18790"));
        assert!(is_loopback_origin("http://localhost:18790"));
        assert!(!is_loopback_origin("http://192.168.50.1:18790"));
        assert!(!is_loopback_origin("http://example.test"));
        assert!(
            !is_loopback_origin("https://127.0.0.1:18790"),
            "tls is not the demo shape"
        );
        assert!(!is_loopback_origin("not a url"));
    }

    // The redirect_uri contains characters that must survive encoding, which
    // is the whole reason this is not string concatenation.
    #[test]
    fn the_form_body_percent_encodes_its_values() {
        let body = encoded_form(&[("redirect_uri", REDIRECT_URI), ("fixture", "alice")]);
        assert!(
            body.contains("redirect_uri=http%3A%2F%2F127.0.0.1%2Fyap-demo-callback"),
            "{body}"
        );
        assert!(body.contains("fixture=alice"), "{body}");
        assert!(!body.contains("://"), "unencoded separator leaked: {body}");
    }

    #[test]
    fn the_code_is_read_from_a_relative_or_absolute_redirect() {
        assert_eq!(
            code_from_redirect("http://127.0.0.1/yap-demo-callback?code=abc&state=yap-demo")
                .as_deref(),
            Some("abc")
        );
        assert_eq!(
            code_from_redirect("/yap-demo-callback?state=yap-demo&code=xyz").as_deref(),
            Some("xyz")
        );
    }

    // A redirect that carries an error instead of a code must not yield an
    // empty string that later reads as a valid-but-blank code.
    #[test]
    fn a_redirect_without_a_code_yields_nothing() {
        assert_eq!(code_from_redirect("/cb?error=access_denied"), None);
        assert_eq!(code_from_redirect("/cb?code="), None);
        assert_eq!(code_from_redirect(""), None);
    }
}
