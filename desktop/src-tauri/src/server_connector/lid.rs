mod client;
mod envelope;
mod error;
mod response;
mod selection;

pub(in crate::server_connector) use client::{cancel_preflight, submit_preflight};
pub(crate) use envelope::{LidPreflightRequest, LidPreflightSourceIdentity};
pub(crate) use error::LidPreflightError;
pub(crate) use response::LidPreflightResult;
#[cfg(test)]
pub(crate) use response::LidPreflightStatus;
pub(crate) use selection::{
    select_lid_probe_windows, LidManualReason, LidProbeSelection, LidProbeWindow,
};

#[cfg(test)]
mod tests;
