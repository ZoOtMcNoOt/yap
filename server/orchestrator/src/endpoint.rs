use std::net::{IpAddr, SocketAddr};

use crate::error::OrchestratorError;

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub struct NumericLoopbackEndpoint {
    socket_addr: SocketAddr,
}

impl NumericLoopbackEndpoint {
    pub fn parse(value: &str) -> Result<Self, OrchestratorError> {
        let authority = value
            .strip_prefix("http://")
            .ok_or_else(|| OrchestratorError::new("provider endpoint must use HTTP"))?;
        if authority.is_empty()
            || authority.contains(['/', '?', '#', '@'])
            || authority.chars().any(char::is_whitespace)
        {
            return Err(OrchestratorError::new(
                "provider endpoint must contain only one numeric authority",
            ));
        }
        let socket_addr = authority
            .parse::<SocketAddr>()
            .map_err(|_| OrchestratorError::new("provider endpoint authority is invalid"))?;
        if socket_addr.port() == 0 || !socket_addr.ip().is_loopback() {
            return Err(OrchestratorError::new(
                "provider endpoint must use a nonzero numeric loopback address",
            ));
        }
        if authority != socket_addr.to_string() {
            return Err(OrchestratorError::new(
                "provider endpoint authority is not canonical",
            ));
        }
        Ok(Self { socket_addr })
    }

    pub fn socket_addr(&self) -> SocketAddr {
        self.socket_addr
    }

    pub fn authority(&self) -> String {
        self.socket_addr.to_string()
    }

    pub fn ip(&self) -> IpAddr {
        self.socket_addr.ip()
    }
}
