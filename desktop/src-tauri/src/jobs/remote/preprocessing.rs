use crate::server_connector::batch::{validate_vad_intervals, VadEvidence, MAX_VAD_INTERVALS};
pub(super) use crate::server_connector::batch::{
    NormalizationEvidence as ImportedNormalizationEvidence,
    PreprocessingEvidence as ImportedPreprocessingEvidence, SourceVadInterval,
    VadComponentEvidence,
};

pub(super) const CAPTURE_MANIFEST_SCHEMA_VERSION: u16 = 2;
pub(super) const MAX_CAPTURE_MANIFEST_BYTES: usize = 1024 * 1024;

pub(super) trait AdvisoryVadEngine {
    fn component(&self) -> VadComponentEvidence;
    fn accept_pcm16(
        &mut self,
        pcm: &[u8],
        ensure_active: &mut dyn FnMut() -> Result<(), String>,
    ) -> Result<(), AdvisoryVadRuntimeError>;
    fn finish(
        &mut self,
        emit: &mut dyn FnMut(SourceVadInterval) -> Result<(), &'static str>,
        ensure_active: &mut dyn FnMut() -> Result<(), String>,
    ) -> Result<(), AdvisoryVadRuntimeError>;
}

pub(super) enum AdvisoryVadRuntimeError {
    Cancelled(String),
    Engine(&'static str),
}

impl AdvisoryVadEngine for crate::stt::silero_vad::SileroVadDetector {
    fn component(&self) -> VadComponentEvidence {
        VadComponentEvidence::pinned_silero()
    }

    fn accept_pcm16(
        &mut self,
        pcm: &[u8],
        ensure_active: &mut dyn FnMut() -> Result<(), String>,
    ) -> Result<(), AdvisoryVadRuntimeError> {
        self.accept_pcm16_with_cancellation(pcm, ensure_active)
            .map_err(map_silero_runtime_error)
    }

    fn finish(
        &mut self,
        emit: &mut dyn FnMut(SourceVadInterval) -> Result<(), &'static str>,
        ensure_active: &mut dyn FnMut() -> Result<(), String>,
    ) -> Result<(), AdvisoryVadRuntimeError> {
        let intervals = self
            .finish_with_cancellation(ensure_active)
            .map_err(map_silero_runtime_error)?;
        for (start, end) in intervals {
            let interval = SourceVadInterval::from_samples(start, end)
                .map_err(AdvisoryVadRuntimeError::Engine)?;
            emit(interval).map_err(AdvisoryVadRuntimeError::Engine)?;
        }
        Ok(())
    }
}

fn map_silero_runtime_error(
    error: crate::stt::silero_vad::SileroVadRuntimeError,
) -> AdvisoryVadRuntimeError {
    match error {
        crate::stt::silero_vad::SileroVadRuntimeError::Cancelled(message) => {
            AdvisoryVadRuntimeError::Cancelled(message)
        }
        crate::stt::silero_vad::SileroVadRuntimeError::Engine(code) => {
            AdvisoryVadRuntimeError::Engine(code)
        }
    }
}

enum AdvisoryVadState<'a> {
    Running(&'a mut dyn AdvisoryVadEngine),
    Failed {
        component: VadComponentEvidence,
        error_code: &'static str,
    },
}

pub(super) struct AdvisoryVadSession<'a> {
    state: AdvisoryVadState<'a>,
}

impl<'a> AdvisoryVadSession<'a> {
    pub(super) fn running(engine: &'a mut dyn AdvisoryVadEngine) -> Self {
        Self {
            state: AdvisoryVadState::Running(engine),
        }
    }

    pub(super) fn unavailable(error_code: &'static str) -> Self {
        Self {
            state: AdvisoryVadState::Failed {
                component: VadComponentEvidence::pinned_silero(),
                error_code,
            },
        }
    }

    pub(super) fn accept_pcm16(
        &mut self,
        pcm: &[u8],
        ensure_active: &mut dyn FnMut() -> Result<(), String>,
    ) -> Result<(), String> {
        let AdvisoryVadState::Running(engine) = &mut self.state else {
            return Ok(());
        };
        match engine.accept_pcm16(pcm, ensure_active) {
            Ok(()) => Ok(()),
            Err(AdvisoryVadRuntimeError::Cancelled(message)) => Err(message),
            Err(AdvisoryVadRuntimeError::Engine(error_code)) => {
                let component = engine.component();
                self.state = AdvisoryVadState::Failed {
                    component,
                    error_code,
                };
                Ok(())
            }
        }
    }

    pub(super) fn is_running(&self) -> bool {
        matches!(self.state, AdvisoryVadState::Running(_))
    }

    pub(super) fn finish(
        mut self,
        source_sample_count: u64,
        ensure_active: &mut dyn FnMut() -> Result<(), String>,
    ) -> Result<VadEvidence, String> {
        ensure_active()?;
        let state = std::mem::replace(
            &mut self.state,
            AdvisoryVadState::Failed {
                component: VadComponentEvidence::pinned_silero(),
                error_code: "internal_state_error",
            },
        );
        match state {
            AdvisoryVadState::Failed {
                component,
                error_code,
            } => Ok(VadEvidence::error(
                component,
                source_sample_count,
                error_code,
            )),
            AdvisoryVadState::Running(engine) => {
                let component = engine.component();
                let mut intervals = Vec::new();
                let mut limit_exceeded = false;
                let finish_result = {
                    let mut emit = |interval| {
                        if intervals.len() >= MAX_VAD_INTERVALS {
                            limit_exceeded = true;
                            return Err("segment_limit_exceeded");
                        }
                        intervals.push(interval);
                        Ok(())
                    };
                    engine.finish(&mut emit, ensure_active)
                };
                ensure_active()?;
                if limit_exceeded {
                    Ok(VadEvidence::error(
                        component,
                        source_sample_count,
                        "segment_limit_exceeded",
                    ))
                } else {
                    match finish_result {
                        Ok(()) => match validate_vad_intervals(&intervals, source_sample_count) {
                            Ok(()) => Ok(VadEvidence::complete(
                                component,
                                source_sample_count,
                                intervals,
                            )),
                            Err(error_code) => Ok(VadEvidence::error(
                                component,
                                source_sample_count,
                                error_code,
                            )),
                        },
                        Err(AdvisoryVadRuntimeError::Cancelled(message)) => Err(message),
                        Err(AdvisoryVadRuntimeError::Engine(error_code)) => Ok(VadEvidence::error(
                            component,
                            source_sample_count,
                            error_code,
                        )),
                    }
                }
            }
        }
    }
}
