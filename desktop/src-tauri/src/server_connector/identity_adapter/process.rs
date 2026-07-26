use std::{
    path::{Path, PathBuf},
    process::Stdio,
    time::Duration,
};

use tokio::io::AsyncReadExt;
use zeroize::{Zeroize, Zeroizing};

use super::{
    protocol::{
        IdentityAdapterProtocolError, IdentityAdapterRequest, IdentityAdapterResponse,
        IdentityOperation, MAX_IDENTITY_ADAPTER_REQUEST_BYTES, MAX_IDENTITY_ADAPTER_RESPONSE_BYTES,
    },
    IdentityAdapter, IdentityAdapterFuture,
};

const SILENT_OPERATION_TIMEOUT: Duration = Duration::from_secs(30);
const INTERACTIVE_OPERATION_TIMEOUT: Duration = Duration::from_secs(5 * 60);

pub(super) struct ProcessIdentityAdapter {
    executable: PathBuf,
}

impl ProcessIdentityAdapter {
    pub(super) fn discover() -> Result<Self, IdentityAdapterProtocolError> {
        let executable = identity_adapter_path()?;
        validate_executable(&executable)?;
        Ok(Self { executable })
    }

    async fn execute_process(
        &self,
        request: IdentityAdapterRequest,
    ) -> Result<IdentityAdapterResponse, IdentityAdapterProtocolError> {
        let mut encoded = serde_json::to_vec(&request)
            .map_err(|_| IdentityAdapterProtocolError::InvalidResponse)?;
        if encoded.len() > MAX_IDENTITY_ADAPTER_REQUEST_BYTES {
            encoded.zeroize();
            return Err(IdentityAdapterProtocolError::InvalidResponse);
        }

        let mut command = tokio::process::Command::new(&self.executable);
        command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true);
        #[cfg(windows)]
        {
            command.creation_flags(0x0800_0000);
        }
        let mut child = command
            .spawn()
            .map_err(|_| IdentityAdapterProtocolError::Unavailable)?;
        let mut stdin = child
            .stdin
            .take()
            .ok_or(IdentityAdapterProtocolError::Unavailable)?;
        tokio::io::AsyncWriteExt::write_all(&mut stdin, &encoded)
            .await
            .map_err(|_| IdentityAdapterProtocolError::Unavailable)?;
        encoded.zeroize();
        drop(stdin);

        let stdout = child
            .stdout
            .take()
            .ok_or(IdentityAdapterProtocolError::Unavailable)?;
        let operation_timeout = match request.operation {
            IdentityOperation::SignInInteractively => INTERACTIVE_OPERATION_TIMEOUT,
            _ => SILENT_OPERATION_TIMEOUT,
        };
        let read_output = async move {
            let mut bounded = stdout.take((MAX_IDENTITY_ADAPTER_RESPONSE_BYTES + 1) as u64);
            let mut bytes = Zeroizing::new(Vec::new());
            bounded
                .read_to_end(&mut bytes)
                .await
                .map_err(|_| IdentityAdapterProtocolError::Unavailable)?;
            Ok::<_, IdentityAdapterProtocolError>(bytes)
        };
        let completed = tokio::time::timeout(operation_timeout, async {
            tokio::join!(read_output, child.wait())
        })
        .await;
        let (output, status) = match completed {
            Ok((output, status)) => (
                output?,
                status.map_err(|_| IdentityAdapterProtocolError::Unavailable)?,
            ),
            Err(_) => {
                child.kill().await.ok();
                child.wait().await.ok();
                return Err(IdentityAdapterProtocolError::TimedOut);
            }
        };
        if !status.success() || output.len() > MAX_IDENTITY_ADAPTER_RESPONSE_BYTES {
            return Err(IdentityAdapterProtocolError::InvalidResponse);
        }
        let response: IdentityAdapterResponse = serde_json::from_slice(&output)
            .map_err(|_| IdentityAdapterProtocolError::InvalidResponse)?;
        response.validate_for(&request)?;
        Ok(response)
    }
}

impl IdentityAdapter for ProcessIdentityAdapter {
    fn execute(&self, request: IdentityAdapterRequest) -> IdentityAdapterFuture<'_> {
        Box::pin(self.execute_process(request))
    }
}

fn identity_adapter_path() -> Result<PathBuf, IdentityAdapterProtocolError> {
    #[cfg(debug_assertions)]
    if let Some(path) = std::env::var_os("YAP_IDENTITY_ADAPTER_PATH") {
        return Ok(PathBuf::from(path));
    }
    #[cfg(debug_assertions)]
    {
        let development_binary = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("binaries")
            .join("yap-identity-broker-x86_64-pc-windows-msvc.exe");
        if development_binary.is_file() {
            return Ok(development_binary);
        }
    }
    let executable =
        std::env::current_exe().map_err(|_| IdentityAdapterProtocolError::Unavailable)?;
    let directory = executable
        .parent()
        .ok_or(IdentityAdapterProtocolError::Unavailable)?;
    Ok(directory.join(identity_adapter_file_name()))
}

#[cfg(windows)]
fn identity_adapter_file_name() -> &'static str {
    "yap-identity-broker.exe"
}

#[cfg(not(windows))]
fn identity_adapter_file_name() -> &'static str {
    "yap-identity-broker"
}

fn validate_executable(path: &Path) -> Result<(), IdentityAdapterProtocolError> {
    let metadata =
        std::fs::symlink_metadata(path).map_err(|_| IdentityAdapterProtocolError::Unavailable)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(IdentityAdapterProtocolError::Unavailable);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::server_connector::config::MicrosoftEntraSettings;

    #[test]
    fn published_adapter_and_rust_protocol_agree_on_invalid_requests() {
        if std::env::var_os("YAP_IDENTITY_ADAPTER_PATH").is_none() {
            return;
        }
        let adapter = ProcessIdentityAdapter::discover().unwrap();
        let request = IdentityAdapterRequest::new(
            "rust-protocol-smoke".into(),
            IdentityOperation::GetStatus,
            &MicrosoftEntraSettings {
                tenant_id: "invalid".into(),
                client_id: "invalid".into(),
                api_scope: "invalid".into(),
            },
            None,
        );
        let response = tauri::async_runtime::block_on(adapter.execute_process(request)).unwrap();
        assert_eq!(
            response.outcome,
            super::super::protocol::IdentityOutcome::InvalidRequest
        );
        assert_eq!(response.error_code.as_deref(), Some("INVALID_REQUEST"));
    }
}
