use std::{
    fs::{self, File},
    io::{Read, Write},
    net::TcpListener,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Mutex,
    },
    thread,
    time::{Duration, UNIX_EPOCH},
};

use crate::{
    audio::session::OwnerNamespace,
    jobs::{
        ClientStageName, ClientStageState, JobLedger, NewClientPreflightArtifact, NewRecordingJob,
        RecordingJobResources, RecordingJobStatus, RecordingRoute, SessionMode, SessionOrigin,
        SourceOwnership,
    },
    server_connector::{
        batch::{
            ApiError, BatchApiClient, CreateRecordingJobRequest, NormalizationEvidence,
            PreprocessingEvidence, SourceVadInterval, VadComponentEvidence, VadEvidence,
        },
        config::ServerSettings,
        ServerConnector, ServerConnectorBoundary,
    },
};

use super::{
    advance_persisted_cancellation_once, advance_processing_job_once_guarded_for_test,
    advance_processing_once, advance_processing_once_guarded,
    advance_upload_job_once_guarded_for_test, advance_upload_once, advance_upload_once_guarded,
    attach_prepared_remote_job_or_cleanup, claim_preprocessing_for_catalog,
    prepare_next_queued_job, remote_retry_plan, validate_result_revision, BatchCommitGuard,
    DrainStepError, RemoteJobDrain,
};

#[path = "tests/support.rs"]
mod support;

use support::*;

#[path = "tests/cancellation.rs"]
mod cancellation;
#[path = "tests/preparation.rs"]
mod preparation;
#[path = "tests/processing.rs"]
mod processing;
#[path = "tests/processing_stage_retry.rs"]
mod processing_stage_retry;
#[path = "tests/processing_stage_retry_ambiguity.rs"]
mod processing_stage_retry_ambiguity;
#[path = "tests/reconfiguration.rs"]
mod reconfiguration;
#[path = "tests/scheduler.rs"]
mod scheduler;
#[path = "tests/upload.rs"]
mod upload;

static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);
