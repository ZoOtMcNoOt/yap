use std::{
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};

use crate::{jobs::AsrCatalogBinding, runtime};

use super::{
    analyst, archivist, batch, client, config, curator, librarian,
    state::{self, ConnectorInner, SettingsDisposition},
    student, transcript_correction, AsrCapabilityCatalog, ServerConnectionSnapshot,
};

pub struct ServerConnector {
    pub(super) client: reqwest::Client,
    pub(super) authenticated: super::AuthenticatedRequestDispatcher,
    pub(super) access_tokens: Arc<super::native_access_token_provider::NativeAccessTokenManager>,
    pub(super) inner: Mutex<ConnectorInner>,
    pub(super) generation: Arc<AtomicU64>,
    asr_request_sequence: AtomicU64,
    latest_asr_commit: AtomicU64,
    latest_asr_catalog: Mutex<Option<CommittedAsrCatalog>>,
    settings_save_active: Arc<AtomicBool>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct CommittedAsrCatalog {
    generation: u64,
    base_url: String,
    request_sequence: u64,
    catalog_revision: String,
    lid_policy_revision: Option<String>,
}

#[derive(Debug)]
pub(super) struct SettingsSaveLease {
    active: Arc<AtomicBool>,
}

pub(crate) struct BatchConnectionLease {
    generation: u64,
    base_url: String,
    client: batch::BatchApiClient,
}

#[derive(Clone)]
pub(crate) struct TranscriptCorrectionConnectionLease {
    generation: u64,
    base_url: String,
    client: transcript_correction::TranscriptCorrectionApiClient,
}

#[derive(Clone)]
pub(crate) struct LibrarianConnectionLease {
    generation: u64,
    base_url: String,
    client: librarian::LibrarianApiClient,
}

#[derive(Clone)]
pub(crate) struct AnalystConnectionLease {
    generation: u64,
    base_url: String,
    client: analyst::AnalystApiClient,
}

#[derive(Clone)]
pub(crate) struct StudentConnectionLease {
    generation: u64,
    base_url: String,
    client: student::StudentApiClient,
}

#[derive(Clone)]
pub(crate) struct ArchivistConnectionLease {
    generation: u64,
    base_url: String,
    client: archivist::ArchivistApiClient,
}

#[derive(Clone)]
pub(crate) struct CuratorConnectionLease {
    generation: u64,
    base_url: String,
    client: curator::CuratorApiClient,
}

#[cfg(test)]
pub(crate) fn transcript_correction_connection_lease_for_test(
) -> TranscriptCorrectionConnectionLease {
    struct NoAccess;
    impl super::authorization::ServerAccessTokenSource for NoAccess {
        fn access(&self) -> super::authorization::AccessTokenFuture<'_> {
            Box::pin(async { Ok(None) })
        }
    }

    let authenticated = super::AuthenticatedRequestDispatcher::from_source(
        client::bounded_client().expect("bounded test client"),
        Arc::new(NoAccess),
        super::authorization::AuthenticatedSession::new(),
    );
    let client = transcript_correction::TranscriptCorrectionApiClient::new(
        authenticated,
        "http://127.0.0.1:1",
    )
    .expect("fixed test correction origin");
    TranscriptCorrectionConnectionLease {
        generation: 1,
        base_url: client.base_url_identity().to_owned(),
        client,
    }
}

#[cfg(test)]
pub(crate) fn librarian_connection_lease_for_test() -> LibrarianConnectionLease {
    struct NoAccess;
    impl super::authorization::ServerAccessTokenSource for NoAccess {
        fn access(&self) -> super::authorization::AccessTokenFuture<'_> {
            Box::pin(async { Ok(None) })
        }
    }

    let authenticated = super::AuthenticatedRequestDispatcher::from_source(
        client::bounded_client().expect("bounded test client"),
        Arc::new(NoAccess),
        super::authorization::AuthenticatedSession::new(),
    );
    let client = librarian::LibrarianApiClient::new(authenticated, "http://127.0.0.1:1")
        .expect("fixed test librarian origin");
    LibrarianConnectionLease {
        generation: 1,
        base_url: client.base_url_identity().to_owned(),
        client,
    }
}

#[cfg(test)]
pub(crate) fn analyst_connection_lease_for_test() -> AnalystConnectionLease {
    struct NoAccess;
    impl super::authorization::ServerAccessTokenSource for NoAccess {
        fn access(&self) -> super::authorization::AccessTokenFuture<'_> {
            Box::pin(async { Ok(None) })
        }
    }

    let authenticated = super::AuthenticatedRequestDispatcher::from_source(
        client::bounded_client().expect("bounded test client"),
        Arc::new(NoAccess),
        super::authorization::AuthenticatedSession::new(),
    );
    let client = analyst::AnalystApiClient::new(authenticated, "http://127.0.0.1:1")
        .expect("fixed test analyst origin");
    AnalystConnectionLease {
        generation: 1,
        base_url: client.base_url_identity().to_owned(),
        client,
    }
}

#[cfg(test)]
pub(crate) fn student_connection_lease_for_test() -> StudentConnectionLease {
    struct NoAccess;
    impl super::authorization::ServerAccessTokenSource for NoAccess {
        fn access(&self) -> super::authorization::AccessTokenFuture<'_> {
            Box::pin(async { Ok(None) })
        }
    }

    let authenticated = super::AuthenticatedRequestDispatcher::from_source(
        client::bounded_client().expect("bounded test client"),
        Arc::new(NoAccess),
        super::authorization::AuthenticatedSession::new(),
    );
    let client = student::StudentApiClient::new(authenticated, "http://127.0.0.1:1")
        .expect("fixed test student origin");
    StudentConnectionLease {
        generation: 1,
        base_url: client.base_url_identity().to_owned(),
        client,
    }
}

#[cfg(test)]
pub(crate) fn archivist_connection_lease_for_test() -> ArchivistConnectionLease {
    struct NoAccess;
    impl super::authorization::ServerAccessTokenSource for NoAccess {
        fn access(&self) -> super::authorization::AccessTokenFuture<'_> {
            Box::pin(async { Ok(None) })
        }
    }

    let authenticated = super::AuthenticatedRequestDispatcher::from_source(
        client::bounded_client().expect("bounded test client"),
        Arc::new(NoAccess),
        super::authorization::AuthenticatedSession::new(),
    );
    let client = archivist::ArchivistApiClient::new(authenticated, "http://127.0.0.1:1")
        .expect("fixed test archivist origin");
    ArchivistConnectionLease {
        generation: 1,
        base_url: client.base_url_identity().to_owned(),
        client,
    }
}

#[cfg(test)]
pub(crate) fn curator_connection_lease_for_test() -> CuratorConnectionLease {
    struct NoAccess;
    impl super::authorization::ServerAccessTokenSource for NoAccess {
        fn access(&self) -> super::authorization::AccessTokenFuture<'_> {
            Box::pin(async { Ok(None) })
        }
    }

    let authenticated = super::AuthenticatedRequestDispatcher::from_source(
        client::bounded_client().expect("bounded test client"),
        Arc::new(NoAccess),
        super::authorization::AuthenticatedSession::new(),
    );
    let client = curator::CuratorApiClient::new(authenticated, "http://127.0.0.1:1")
        .expect("fixed test curator origin");
    CuratorConnectionLease {
        generation: 1,
        base_url: client.base_url_identity().to_owned(),
        client,
    }
}

pub(crate) struct AsrCapabilityLease {
    generation: u64,
    base_url: String,
    request_sequence: u64,
    authenticated: super::AuthenticatedRequestDispatcher,
}

pub(crate) struct CurrentAsrCatalog<'a> {
    catalog: &'a AsrCapabilityCatalog,
    binding: AsrCatalogBinding,
    dispatch_proof: AsrCatalogDispatchProof,
}

#[derive(Debug, Clone)]
pub(crate) struct AsrCatalogDispatchProof {
    generation: u64,
    base_url: String,
    request_sequence: u64,
    catalog_revision: String,
}

#[derive(Debug, Clone)]
pub(crate) struct LidPreflightDispatchProof {
    generation: u64,
    base_url: String,
    request_sequence: u64,
    catalog_revision: String,
    policy_revision: String,
}

pub(crate) struct CurrentLidPreflight {
    dispatch_proof: LidPreflightDispatchProof,
}

impl CurrentAsrCatalog<'_> {
    pub(crate) fn catalog(&self) -> &AsrCapabilityCatalog {
        self.catalog
    }

    pub(crate) fn binding(&self) -> &AsrCatalogBinding {
        &self.binding
    }

    pub(crate) fn dispatch_proof(&self) -> AsrCatalogDispatchProof {
        self.dispatch_proof.clone()
    }

    pub(crate) fn lid_preflight_dispatch(&self) -> Option<CurrentLidPreflight> {
        let capability = self.catalog.lid_preflight()?;
        Some(CurrentLidPreflight {
            dispatch_proof: LidPreflightDispatchProof {
                generation: self.dispatch_proof.generation,
                base_url: self.dispatch_proof.base_url.clone(),
                request_sequence: self.dispatch_proof.request_sequence,
                catalog_revision: self.dispatch_proof.catalog_revision.clone(),
                policy_revision: capability.policy.revision.clone(),
            },
        })
    }
}

impl CurrentLidPreflight {
    pub(crate) fn dispatch_proof(&self) -> LidPreflightDispatchProof {
        self.dispatch_proof.clone()
    }
}

impl AsrCapabilityLease {
    pub(crate) fn base_url(&self) -> &str {
        &self.base_url
    }

    pub(crate) fn authenticated(&self) -> &super::AuthenticatedRequestDispatcher {
        &self.authenticated
    }
}

impl BatchConnectionLease {
    pub(crate) fn client(&self) -> &batch::BatchApiClient {
        &self.client
    }
}

impl TranscriptCorrectionConnectionLease {
    pub(crate) fn client(&self) -> &transcript_correction::TranscriptCorrectionApiClient {
        &self.client
    }
}

impl LibrarianConnectionLease {
    pub(crate) fn client(&self) -> &librarian::LibrarianApiClient {
        &self.client
    }
}

impl AnalystConnectionLease {
    pub(crate) fn client(&self) -> &analyst::AnalystApiClient {
        &self.client
    }
}

impl StudentConnectionLease {
    pub(crate) fn client(&self) -> &student::StudentApiClient {
        &self.client
    }
}

impl ArchivistConnectionLease {
    pub(crate) fn client(&self) -> &archivist::ArchivistApiClient {
        &self.client
    }
}

impl CuratorConnectionLease {
    pub(crate) fn client(&self) -> &curator::CuratorApiClient {
        &self.client
    }
}

impl Default for ServerConnector {
    fn default() -> Self {
        let access_tokens =
            super::native_access_token_provider::NativeAccessTokenManager::discover();
        Self::with_access_tokens(access_tokens)
    }
}

impl ServerConnector {
    fn with_access_tokens(
        access_tokens: Arc<super::native_access_token_provider::NativeAccessTokenManager>,
    ) -> Self {
        let client = client::bounded_client().expect("bounded server connector client must build");
        let generation = Arc::new(AtomicU64::new(0));
        let authenticated = super::AuthenticatedRequestDispatcher::from_source(
            client.clone(),
            access_tokens.clone(),
            access_tokens.session(),
        )
        .with_connector_generation(Arc::clone(&generation));
        Self {
            client,
            authenticated,
            access_tokens,
            inner: Mutex::new(ConnectorInner::default()),
            generation,
            asr_request_sequence: AtomicU64::new(0),
            latest_asr_commit: AtomicU64::new(0),
            latest_asr_catalog: Mutex::new(None),
            settings_save_active: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn new() -> Self {
        Self::default()
    }

    #[cfg(test)]
    pub(super) fn with_access_tokens_for_test(
        access_tokens: Arc<super::native_access_token_provider::NativeAccessTokenManager>,
    ) -> Self {
        Self::with_access_tokens(access_tokens)
    }

    pub(crate) fn batch_client_for_persisted_origin(
        &self,
        base_url: &str,
    ) -> Result<batch::BatchApiClient, batch::BatchClientError> {
        self.current_approved_batch_client(base_url).map_err(|_| {
            batch::BatchClientError::Authorization(
                super::authorization::RequestAuthorizationError::Unavailable,
            )
        })
    }

    pub(crate) async fn connect_authenticated_live_at_approved_origin(
        &self,
        approved_live_origin: &str,
    ) -> Result<super::AuthenticatedLiveConnection, super::AuthenticatedLiveError> {
        let origin = config::validate_base_url(approved_live_origin, false)
            .map_err(|_| super::AuthenticatedLiveError::InvalidOrigin)?;
        let generation = self.generation.load(Ordering::Acquire);
        let origin_is_current = {
            let inner = self.inner.lock().expect("server connector poisoned");
            inner.generation() == generation
                && inner.configured_base_url(generation).as_deref() == Some(origin.as_str())
        };
        if !origin_is_current
            || !config::origin_is_approved(&origin)
                .map_err(|_| super::AuthenticatedLiveError::ConfigurationUnavailable)?
        {
            return Err(super::AuthenticatedLiveError::OriginNotApproved);
        }
        let authenticated = self
            .authenticated
            .bind_current_transport(generation, &origin)
            .map_err(|_| super::AuthenticatedLiveError::ConfigurationUnavailable)?;
        let connection = authenticated.connect_approved_live(&origin).await?;
        let still_current = self
            .configured_batch_origin()
            .is_ok_and(|current| current.as_deref() == Some(origin.as_str()))
            && config::origin_is_approved(&origin).unwrap_or(false);
        if !still_current {
            drop(connection);
            return Err(super::AuthenticatedLiveError::ConfigurationUnavailable);
        }
        Ok(connection)
    }

    pub(super) fn begin_settings_save(&self) -> Result<SettingsSaveLease, String> {
        self.settings_save_active
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| "A server settings update is already active.".to_string())?;
        Ok(SettingsSaveLease {
            active: Arc::clone(&self.settings_save_active),
        })
    }

    #[cfg(test)]
    pub(crate) fn current(&self) -> u64 {
        self.generation.load(Ordering::Acquire)
    }

    #[cfg(test)]
    pub(crate) fn invalidate(&self) -> u64 {
        let mut inner = self.inner.lock().expect("server connector poisoned");
        self.invalidate_locked(&mut inner)
    }

    pub(super) fn invalidate_locked(&self, inner: &mut ConnectorInner) -> u64 {
        let generation = self.generation.fetch_add(1, Ordering::AcqRel) + 1;
        inner.apply_settings(generation, SettingsDisposition::NotSet);
        generation
    }

    pub(super) fn with_loaded_settings<T, Load, Apply>(
        &self,
        load: Load,
        apply: Apply,
    ) -> Result<T, config::ConfigError>
    where
        Load: FnOnce() -> Result<config::ServerSettings, config::ConfigError>,
        Apply: FnOnce(&mut ConnectorInner, config::ServerSettings) -> T,
    {
        let mut inner = self.inner.lock().expect("server connector poisoned");
        let settings = load()?;
        Ok(apply(&mut inner, settings))
    }

    pub(super) fn synchronize_settings_with<Project>(
        &self,
        settings: &config::ServerSettings,
        project: Project,
    ) -> ServerConnectionSnapshot
    where
        Project: Fn(&ServerConnectionSnapshot),
    {
        let mut inner = self.inner.lock().expect("server connector poisoned");
        self.synchronize_settings_locked(&mut inner, settings, project)
    }

    pub(super) fn synchronize_settings_locked<Project>(
        &self,
        inner: &mut ConnectorInner,
        settings: &config::ServerSettings,
        project: Project,
    ) -> ServerConnectionSnapshot
    where
        Project: Fn(&ServerConnectionSnapshot),
    {
        let mut generation = self.generation.load(Ordering::Acquire);
        if !inner.configuration_matches(generation, settings.enabled, settings.base_url.as_deref())
        {
            if inner.generation() == generation && inner.current_configuration_initialized() {
                generation = self.generation.fetch_add(1, Ordering::AcqRel) + 1;
            }
            inner.apply_server_settings(generation, settings.enabled, settings.base_url.clone());
            project(&inner.snapshot());
        }
        inner.snapshot()
    }

    pub(super) fn snapshot(&self) -> ServerConnectionSnapshot {
        self.inner
            .lock()
            .expect("server connector poisoned")
            .snapshot()
    }

    pub(crate) fn batch_connection_lease(&self) -> Result<Option<BatchConnectionLease>, String> {
        let generation = self.generation.load(Ordering::Acquire);
        let inner = self.inner.lock().expect("server connector poisoned");
        let snapshot = inner.snapshot();
        if inner.generation() != generation
            || snapshot.state != runtime::state::ServerConnectorState::Ready
            || !snapshot.capabilities.batch_jobs
            || !snapshot.capabilities.job_status
        {
            return Ok(None);
        }
        let Some(base_url) = inner.configured_base_url(generation) else {
            return Ok(None);
        };
        let authenticated = self
            .authenticated
            .bind_current_transport(generation, &base_url)
            .map_err(|_| "The server connection changed before batch dispatch.".to_string())?;
        let client = batch::BatchApiClient::new_authorized(authenticated, &base_url)
            .map_err(|error| error.to_string())?;
        let base_url = client.base_url_identity().to_owned();
        Ok(Some(BatchConnectionLease {
            generation,
            base_url,
            client,
        }))
    }

    pub(crate) fn transcript_correction_connection_lease(
        &self,
    ) -> Result<Option<TranscriptCorrectionConnectionLease>, String> {
        let generation = self.generation.load(Ordering::Acquire);
        let inner = self.inner.lock().expect("server connector poisoned");
        let snapshot = inner.snapshot();
        if inner.generation() != generation
            || snapshot.state != runtime::state::ServerConnectorState::Ready
            || !snapshot.capabilities.transcript_correction
        {
            return Ok(None);
        }
        let Some(base_url) = inner.configured_base_url(generation) else {
            return Ok(None);
        };
        let authenticated = self
            .authenticated
            .bind_current_transport(generation, &base_url)
            .map_err(|_| {
                "The server connection changed before transcript correction dispatch.".to_string()
            })?;
        let client =
            transcript_correction::TranscriptCorrectionApiClient::new(authenticated, &base_url)
                .map_err(|_| "The transcript correction server origin is invalid.".to_string())?;
        let base_url = client.base_url_identity().to_owned();
        Ok(Some(TranscriptCorrectionConnectionLease {
            generation,
            base_url,
            client,
        }))
    }

    pub(crate) fn librarian_connection_lease(
        &self,
    ) -> Result<Option<LibrarianConnectionLease>, String> {
        let generation = self.generation.load(Ordering::Acquire);
        let inner = self.inner.lock().expect("server connector poisoned");
        let snapshot = inner.snapshot();
        if inner.generation() != generation
            || snapshot.state != runtime::state::ServerConnectorState::Ready
            || !snapshot.capabilities.librarian_queries
        {
            return Ok(None);
        }
        let Some(base_url) = inner.configured_base_url(generation) else {
            return Ok(None);
        };
        let authenticated = self
            .authenticated
            .bind_current_transport(generation, &base_url)
            .map_err(|_| {
                "The server connection changed before knowledge query dispatch.".to_string()
            })?;
        let client = librarian::LibrarianApiClient::new(authenticated, &base_url)
            .map_err(|_| "The knowledge query server origin is invalid.".to_string())?;
        let base_url = client.base_url_identity().to_owned();
        Ok(Some(LibrarianConnectionLease {
            generation,
            base_url,
            client,
        }))
    }

    pub(crate) fn analyst_connection_lease(
        &self,
    ) -> Result<Option<AnalystConnectionLease>, String> {
        let generation = self.generation.load(Ordering::Acquire);
        let inner = self.inner.lock().expect("server connector poisoned");
        let snapshot = inner.snapshot();
        if inner.generation() != generation
            || snapshot.state != runtime::state::ServerConnectorState::Ready
            || !snapshot.capabilities.analyst_answers
        {
            return Ok(None);
        }
        let Some(base_url) = inner.configured_base_url(generation) else {
            return Ok(None);
        };
        let authenticated = self
            .authenticated
            .bind_current_transport(generation, &base_url)
            .map_err(|_| {
                "The server connection changed before cited-answer dispatch.".to_string()
            })?;
        let client = analyst::AnalystApiClient::new(authenticated, &base_url)
            .map_err(|_| "The cited-answer server origin is invalid.".to_string())?;
        let base_url = client.base_url_identity().to_owned();
        Ok(Some(AnalystConnectionLease {
            generation,
            base_url,
            client,
        }))
    }

    pub(crate) fn student_connection_lease(
        &self,
    ) -> Result<Option<StudentConnectionLease>, String> {
        let generation = self.generation.load(Ordering::Acquire);
        let inner = self.inner.lock().expect("server connector poisoned");
        let snapshot = inner.snapshot();
        if inner.generation() != generation
            || snapshot.state != runtime::state::ServerConnectorState::Ready
            || !snapshot.capabilities.student_questions
        {
            return Ok(None);
        }
        let Some(base_url) = inner.configured_base_url(generation) else {
            return Ok(None);
        };
        let authenticated = self
            .authenticated
            .bind_current_transport(generation, &base_url)
            .map_err(|_| {
                "The server connection changed before learning-question dispatch.".to_string()
            })?;
        let client = student::StudentApiClient::new(authenticated, &base_url)
            .map_err(|_| "The learning-question server origin is invalid.".to_string())?;
        let base_url = client.base_url_identity().to_owned();
        Ok(Some(StudentConnectionLease {
            generation,
            base_url,
            client,
        }))
    }

    pub(crate) fn archivist_connection_lease(
        &self,
    ) -> Result<Option<ArchivistConnectionLease>, String> {
        let generation = self.generation.load(Ordering::Acquire);
        let inner = self.inner.lock().expect("server connector poisoned");
        let snapshot = inner.snapshot();
        if inner.generation() != generation
            || snapshot.state != runtime::state::ServerConnectorState::Ready
            || !snapshot.capabilities.archivist_ingestions
        {
            return Ok(None);
        }
        let Some(base_url) = inner.configured_base_url(generation) else {
            return Ok(None);
        };
        let authenticated = self
            .authenticated
            .bind_current_transport(generation, &base_url)
            .map_err(|_| {
                "The server connection changed before knowledge staging dispatch.".to_string()
            })?;
        let client = archivist::ArchivistApiClient::new(authenticated, &base_url)
            .map_err(|_| "The knowledge staging server origin is invalid.".to_string())?;
        let base_url = client.base_url_identity().to_owned();
        Ok(Some(ArchivistConnectionLease {
            generation,
            base_url,
            client,
        }))
    }

    pub(crate) fn curator_connection_lease(
        &self,
    ) -> Result<Option<CuratorConnectionLease>, String> {
        let generation = self.generation.load(Ordering::Acquire);
        let inner = self.inner.lock().expect("server connector poisoned");
        let snapshot = inner.snapshot();
        if inner.generation() != generation
            || snapshot.state != runtime::state::ServerConnectorState::Ready
            || !snapshot.capabilities.curator_proposals
        {
            return Ok(None);
        }
        let Some(base_url) = inner.configured_base_url(generation) else {
            return Ok(None);
        };
        let authenticated = self
            .authenticated
            .bind_current_transport(generation, &base_url)
            .map_err(|_| {
                "The server connection changed before knowledge-proposal dispatch.".to_string()
            })?;
        let client = curator::CuratorApiClient::new(authenticated, &base_url)
            .map_err(|_| "The knowledge-proposal server origin is invalid.".to_string())?;
        let base_url = client.base_url_identity().to_owned();
        Ok(Some(CuratorConnectionLease {
            generation,
            base_url,
            client,
        }))
    }

    pub(crate) fn asr_capability_lease(&self) -> Option<AsrCapabilityLease> {
        let generation = self.generation.load(Ordering::Acquire);
        let inner = self.inner.lock().expect("server connector poisoned");
        let snapshot = inner.snapshot();
        if inner.generation() != generation
            || snapshot.state != runtime::state::ServerConnectorState::Ready
        {
            return None;
        }
        let base_url = inner.configured_base_url(generation)?;
        let request_sequence = self
            .asr_request_sequence
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |current| {
                current.checked_add(1)
            })
            .ok()?
            .checked_add(1)?;
        let authenticated = self
            .authenticated
            .bind_current_transport(generation, &base_url)
            .ok()?;
        Some(AsrCapabilityLease {
            generation,
            base_url,
            request_sequence,
            authenticated,
        })
    }

    pub(crate) fn persisted_cleanup_client(
        &self,
        base_url: &str,
    ) -> Result<batch::BatchApiClient, String> {
        self.current_approved_batch_client(base_url)
    }

    fn current_approved_batch_client(
        &self,
        base_url: &str,
    ) -> Result<batch::BatchApiClient, String> {
        let origin = config::validate_base_url(base_url, super::allow_insecure_private_server())
            .map_err(|error| error.to_string())?;
        let generation = self.generation.load(Ordering::Acquire);
        let origin_is_current = {
            let inner = self.inner.lock().expect("server connector poisoned");
            inner.generation() == generation
                && inner.configured_base_url(generation).as_deref() == Some(origin.as_str())
        };
        if !origin_is_current {
            return Err(
                "Persisted remote cleanup is blocked because its origin is not the current configured server."
                    .into(),
            );
        }
        if !config::origin_is_approved(&origin).map_err(|error| error.to_string())? {
            return Err(
                "Persisted remote cleanup is blocked because its origin is not currently approved."
                    .into(),
            );
        }
        let authenticated = self
            .authenticated
            .bind_current_transport(generation, &origin)
            .map_err(|_| {
                "Persisted remote cleanup is blocked because the authenticated session changed."
                    .to_string()
            })?;
        batch::BatchApiClient::new_authorized(authenticated, &origin)
            .map_err(|error| error.to_string())
    }

    pub(crate) fn configured_batch_origin(&self) -> Result<Option<String>, String> {
        let generation = self.generation.load(Ordering::Acquire);
        let inner = self.inner.lock().expect("server connector poisoned");
        if inner.generation() != generation || !inner.current_configuration_initialized() {
            return Err("Server settings are not initialized for remote cleanup.".into());
        }
        Ok(inner.configured_base_url(generation))
    }

    pub(crate) fn with_current_batch_lease<T>(
        &self,
        lease: &BatchConnectionLease,
        commit: impl FnOnce() -> T,
    ) -> Result<T, String> {
        let inner = self.inner.lock().expect("server connector poisoned");
        let snapshot = inner.snapshot();
        let current = self.generation.load(Ordering::Acquire) == lease.generation
            && inner.generation() == lease.generation
            && inner.configured_base_url(lease.generation).as_deref()
                == Some(lease.base_url.as_str())
            && snapshot.state == runtime::state::ServerConnectorState::Ready
            && snapshot.capabilities.batch_jobs
            && snapshot.capabilities.job_status;
        if !current {
            return Err("Server connection changed before the batch response could commit.".into());
        }
        Ok(commit())
    }

    pub(crate) fn with_current_transcript_correction_lease<T>(
        &self,
        lease: &TranscriptCorrectionConnectionLease,
        commit: impl FnOnce() -> T,
    ) -> Result<T, String> {
        let inner = self.inner.lock().expect("server connector poisoned");
        let snapshot = inner.snapshot();
        let current = self.generation.load(Ordering::Acquire) == lease.generation
            && inner.generation() == lease.generation
            && inner.configured_base_url(lease.generation).as_deref()
                == Some(lease.base_url.as_str())
            && snapshot.state == runtime::state::ServerConnectorState::Ready
            && snapshot.capabilities.transcript_correction;
        if !current {
            return Err(
                "Server connection changed before transcript correction could commit.".into(),
            );
        }
        Ok(commit())
    }

    pub(crate) fn with_current_librarian_lease<T>(
        &self,
        lease: &LibrarianConnectionLease,
        commit: impl FnOnce() -> T,
    ) -> Result<T, String> {
        let inner = self.inner.lock().expect("server connector poisoned");
        let snapshot = inner.snapshot();
        let current = self.generation.load(Ordering::Acquire) == lease.generation
            && inner.generation() == lease.generation
            && inner.configured_base_url(lease.generation).as_deref()
                == Some(lease.base_url.as_str())
            && snapshot.state == runtime::state::ServerConnectorState::Ready
            && snapshot.capabilities.librarian_queries;
        if !current {
            return Err("Server connection changed before knowledge query could commit.".into());
        }
        Ok(commit())
    }

    pub(crate) fn with_current_analyst_lease<T>(
        &self,
        lease: &AnalystConnectionLease,
        commit: impl FnOnce() -> T,
    ) -> Result<T, String> {
        let inner = self.inner.lock().expect("server connector poisoned");
        let snapshot = inner.snapshot();
        let current = self.generation.load(Ordering::Acquire) == lease.generation
            && inner.generation() == lease.generation
            && inner.configured_base_url(lease.generation).as_deref()
                == Some(lease.base_url.as_str())
            && snapshot.state == runtime::state::ServerConnectorState::Ready
            && snapshot.capabilities.analyst_answers;
        if !current {
            return Err("Server connection changed before cited answer could commit.".into());
        }
        Ok(commit())
    }

    pub(crate) fn with_current_student_lease<T>(
        &self,
        lease: &StudentConnectionLease,
        commit: impl FnOnce() -> T,
    ) -> Result<T, String> {
        let inner = self.inner.lock().expect("server connector poisoned");
        let snapshot = inner.snapshot();
        let current = self.generation.load(Ordering::Acquire) == lease.generation
            && inner.generation() == lease.generation
            && inner.configured_base_url(lease.generation).as_deref()
                == Some(lease.base_url.as_str())
            && snapshot.state == runtime::state::ServerConnectorState::Ready
            && snapshot.capabilities.student_questions;
        if !current {
            return Err("Server connection changed before learning questions could commit.".into());
        }
        Ok(commit())
    }

    pub(crate) fn with_current_archivist_lease<T>(
        &self,
        lease: &ArchivistConnectionLease,
        commit: impl FnOnce() -> T,
    ) -> Result<T, String> {
        let inner = self.inner.lock().expect("server connector poisoned");
        let snapshot = inner.snapshot();
        let current = self.generation.load(Ordering::Acquire) == lease.generation
            && inner.generation() == lease.generation
            && inner.configured_base_url(lease.generation).as_deref()
                == Some(lease.base_url.as_str())
            && snapshot.state == runtime::state::ServerConnectorState::Ready
            && snapshot.capabilities.archivist_ingestions;
        if !current {
            return Err("Server connection changed before knowledge staging could commit.".into());
        }
        Ok(commit())
    }

    pub(crate) fn with_current_curator_lease<T>(
        &self,
        lease: &CuratorConnectionLease,
        commit: impl FnOnce() -> T,
    ) -> Result<T, String> {
        let inner = self.inner.lock().expect("server connector poisoned");
        let snapshot = inner.snapshot();
        let current = self.generation.load(Ordering::Acquire) == lease.generation
            && inner.generation() == lease.generation
            && inner.configured_base_url(lease.generation).as_deref()
                == Some(lease.base_url.as_str())
            && snapshot.state == runtime::state::ServerConnectorState::Ready
            && snapshot.capabilities.curator_proposals;
        if !current {
            return Err("Server connection changed before knowledge proposal could commit.".into());
        }
        Ok(commit())
    }

    pub(crate) fn with_current_batch_catalog_proof<T>(
        &self,
        lease: &BatchConnectionLease,
        proof: &AsrCatalogDispatchProof,
        binding: &AsrCatalogBinding,
        commit: impl FnOnce() -> T,
    ) -> Result<T, String> {
        let inner = self.inner.lock().expect("server connector poisoned");
        let snapshot = inner.snapshot();
        let latest_sequence = self.latest_asr_commit.load(Ordering::Acquire);
        let catalog_is_current = latest_sequence == proof.request_sequence
            || (latest_sequence > proof.request_sequence
                && self
                    .latest_asr_catalog
                    .lock()
                    .expect("ASR catalog identity poisoned")
                    .as_ref()
                    .is_some_and(|latest| {
                        latest.generation == proof.generation
                            && latest.base_url == proof.base_url
                            && latest.request_sequence == latest_sequence
                            && latest.catalog_revision == proof.catalog_revision
                    }));
        let current = lease.generation == proof.generation
            && lease.base_url == proof.base_url
            && proof.base_url == binding.origin()
            && proof.catalog_revision == binding.catalog_revision()
            && self.generation.load(Ordering::Acquire) == lease.generation
            && inner.generation() == lease.generation
            && inner.configured_base_url(lease.generation).as_deref()
                == Some(lease.base_url.as_str())
            && snapshot.state == runtime::state::ServerConnectorState::Ready
            && snapshot.capabilities.batch_jobs
            && snapshot.capabilities.job_status
            && catalog_is_current;
        if !current {
            return Err("Server connection or ASR catalog changed before batch dispatch.".into());
        }
        Ok(commit())
    }

    pub(crate) fn with_current_lid_preflight_proof<T>(
        &self,
        lease: &BatchConnectionLease,
        proof: &LidPreflightDispatchProof,
        commit: impl FnOnce() -> T,
    ) -> Result<T, String> {
        let inner = self.inner.lock().expect("server connector poisoned");
        let snapshot = inner.snapshot();
        let latest_sequence = self.latest_asr_commit.load(Ordering::Acquire);
        let lid_contract_is_current = latest_sequence == proof.request_sequence
            || (latest_sequence > proof.request_sequence
                && self
                    .latest_asr_catalog
                    .lock()
                    .expect("ASR catalog identity poisoned")
                    .as_ref()
                    .is_some_and(|latest| {
                        latest.generation == proof.generation
                            && latest.base_url == proof.base_url
                            && latest.request_sequence == latest_sequence
                            && latest.catalog_revision == proof.catalog_revision
                            && latest.lid_policy_revision.as_deref()
                                == Some(proof.policy_revision.as_str())
                    }));
        let current = lease.generation == proof.generation
            && lease.base_url == proof.base_url
            && self.generation.load(Ordering::Acquire) == lease.generation
            && inner.generation() == lease.generation
            && inner.configured_base_url(lease.generation).as_deref()
                == Some(lease.base_url.as_str())
            && snapshot.state == runtime::state::ServerConnectorState::Ready
            && snapshot.capabilities.batch_jobs
            && snapshot.capabilities.job_status
            && lid_contract_is_current;
        if !current {
            return Err(
                "Server connection or language-preflight contract changed before dispatch.".into(),
            );
        }
        Ok(commit())
    }

    fn with_current_asr_capability_lease<T>(
        &self,
        lease: &AsrCapabilityLease,
        catalog_revision: &str,
        lid_policy_revision: Option<&str>,
        commit: impl FnOnce() -> T,
    ) -> Result<T, String> {
        let inner = self.inner.lock().expect("server connector poisoned");
        let snapshot = inner.snapshot();
        let current = self.generation.load(Ordering::Acquire) == lease.generation
            && inner.generation() == lease.generation
            && inner.configured_base_url(lease.generation).as_deref()
                == Some(lease.base_url.as_str())
            && snapshot.state == runtime::state::ServerConnectorState::Ready
            && lease.request_sequence > self.latest_asr_commit.load(Ordering::Acquire);
        if !current {
            return Err("Server connection or ASR catalog freshness changed before commit.".into());
        }
        let committed = commit();
        *self
            .latest_asr_catalog
            .lock()
            .expect("ASR catalog identity poisoned") = Some(CommittedAsrCatalog {
            generation: lease.generation,
            base_url: lease.base_url.clone(),
            request_sequence: lease.request_sequence,
            catalog_revision: catalog_revision.to_owned(),
            lid_policy_revision: lid_policy_revision.map(str::to_owned),
        });
        self.latest_asr_commit
            .store(lease.request_sequence, Ordering::Release);
        Ok(committed)
    }

    pub(crate) fn commit_current_asr_capability_catalog<T>(
        &self,
        lease: &AsrCapabilityLease,
        catalog: AsrCapabilityCatalog,
        commit: impl FnOnce(CurrentAsrCatalog<'_>) -> T,
    ) -> Result<T, String> {
        let catalog_revision = catalog.catalog_revision.clone();
        let lid_policy_revision = catalog
            .lid_preflight()
            .map(|capability| capability.policy.revision.clone());
        self.with_current_asr_capability_lease(
            lease,
            &catalog_revision,
            lid_policy_revision.as_deref(),
            || {
                if super::capability_snapshot::save(lease.base_url(), &catalog).is_err() {
                    crate::diagnostics::log(
                        "verified ASR capability snapshot could not be updated",
                    );
                }
                let binding = AsrCatalogBinding::try_new(
                    lease.base_url.clone(),
                    catalog.catalog_revision.clone(),
                )
                .expect("verified ASR catalog lease has a valid durable identity");
                let dispatch_proof = AsrCatalogDispatchProof {
                    generation: lease.generation,
                    base_url: lease.base_url.clone(),
                    request_sequence: lease.request_sequence,
                    catalog_revision: catalog.catalog_revision.clone(),
                };
                commit(CurrentAsrCatalog {
                    catalog: &catalog,
                    binding,
                    dispatch_proof,
                })
            },
        )
    }

    #[cfg(test)]
    pub(super) fn commit_current_asr_capability_catalog_with<T>(
        &self,
        lease: &AsrCapabilityLease,
        catalog: AsrCapabilityCatalog,
        publish: impl FnOnce(&str, &AsrCapabilityCatalog),
        commit: impl FnOnce(&AsrCapabilityCatalog) -> T,
    ) -> Result<T, String> {
        let catalog_revision = catalog.catalog_revision.clone();
        let lid_policy_revision = catalog
            .lid_preflight()
            .map(|capability| capability.policy.revision.clone());
        self.with_current_asr_capability_lease(
            lease,
            &catalog_revision,
            lid_policy_revision.as_deref(),
            || {
                publish(lease.base_url(), &catalog);
                commit(&catalog)
            },
        )
    }

    #[cfg(test)]
    pub(super) fn commit_current_asr_capability_catalog_for_test<T>(
        &self,
        lease: &AsrCapabilityLease,
        catalog: AsrCapabilityCatalog,
        commit: impl FnOnce(CurrentAsrCatalog<'_>) -> T,
    ) -> Result<T, String> {
        let catalog_revision = catalog.catalog_revision.clone();
        let lid_policy_revision = catalog
            .lid_preflight()
            .map(|capability| capability.policy.revision.clone());
        self.with_current_asr_capability_lease(
            lease,
            &catalog_revision,
            lid_policy_revision.as_deref(),
            || {
                let binding = AsrCatalogBinding::try_new(
                    lease.base_url.clone(),
                    catalog.catalog_revision.clone(),
                )
                .expect("verified test catalog lease has a valid durable identity");
                let dispatch_proof = AsrCatalogDispatchProof {
                    generation: lease.generation,
                    base_url: lease.base_url.clone(),
                    request_sequence: lease.request_sequence,
                    catalog_revision: catalog.catalog_revision.clone(),
                };
                commit(CurrentAsrCatalog {
                    catalog: &catalog,
                    binding,
                    dispatch_proof,
                })
            },
        )
    }

    pub(super) fn begin_health_request_with<Project>(
        &self,
        project: Project,
    ) -> Option<(u64, String)>
    where
        Project: Fn(&ServerConnectionSnapshot),
    {
        let generation = self.generation.load(Ordering::Acquire);
        let mut inner = self.inner.lock().expect("server connector poisoned");
        let base_url = inner.configured_base_url(generation)?;
        if !inner.begin_health_request(generation, now_ms()) {
            return None;
        }
        project(&inner.snapshot());
        Some((generation, base_url))
    }

    pub(super) fn accept_health_result_with<Project, SpawnRetry>(
        &self,
        generation: u64,
        result: client::HealthCheckResult,
        project: Project,
        spawn_retry_task: SpawnRetry,
    ) -> ServerConnectionSnapshot
    where
        Project: Fn(&ServerConnectionSnapshot),
        SpawnRetry: FnOnce(u64, u64, Duration) -> tauri::async_runtime::JoinHandle<()>,
    {
        {
            let mut inner = self.inner.lock().expect("server connector poisoned");
            if self.generation.load(Ordering::Acquire) != generation {
                return inner.snapshot();
            }
            let Some(transition) =
                inner.finish_health_request(generation, result, now_ms(), state::production_jitter)
            else {
                return inner.snapshot();
            };
            project(&inner.snapshot());

            if let Some(delay) = transition.retry_after {
                let retry_at_ms = now_ms().saturating_add(duration_ms(delay));
                if inner.arm_retry(generation, retry_at_ms) {
                    let snapshot = inner.snapshot();
                    project(&snapshot);
                    let retry_token = inner.retry_token();
                    let task = spawn_retry_task(generation, retry_token, delay);
                    inner.install_retry_task(task);
                }
            }
        }

        self.snapshot()
    }

    pub(super) fn begin_scheduled_retry_with<Project>(
        &self,
        generation: u64,
        retry_token: u64,
        project: Project,
    ) -> Option<String>
    where
        Project: Fn(&ServerConnectionSnapshot),
    {
        let mut inner = self.inner.lock().expect("server connector poisoned");
        if self.generation.load(Ordering::Acquire) != generation
            || !inner.begin_scheduled_retry(generation, retry_token)
        {
            return None;
        }
        let base_url = inner.configured_base_url(generation)?;
        project(&inner.snapshot());
        Some(base_url)
    }
}

impl Drop for SettingsSaveLease {
    fn drop(&mut self) {
        self.active.store(false, Ordering::Release);
    }
}

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(u128::from(u64::MAX)) as u64
}

fn duration_ms(duration: Duration) -> u64 {
    duration.as_millis().min(u128::from(u64::MAX)) as u64
}
