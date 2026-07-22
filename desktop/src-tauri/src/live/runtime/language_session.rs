use crate::{
    audio::frame::PreparedFrame,
    language::{
        live_diarization::{LanguageDecisionOutcome, LanguageSpan, LanguageSpanDisposition},
        live_evidence::{
            LiveLanguageDegradation, LiveLanguageEvidence, LiveLanguageMode, LiveLanguageStatus,
        },
    },
};

use super::super::{
    language_pipeline::{LanguagePipelineBatch, LanguagePipelineError, ResidentLanguagePipeline},
    language_router::{LanguageAudioAction, LanguageRoutingError},
    source_audio::{observed_frame_range, SourceAudioError},
};

pub(super) struct LanguageFramePlan {
    pub(super) actions: Vec<LanguageAudioAction>,
    pub(super) direct_primary_frame: Option<PreparedFrame>,
    pub(super) return_to_primary: bool,
    pub(super) degradation_started: bool,
}

pub(super) struct LanguageFinishPlan {
    pub(super) actions: Vec<LanguageAudioAction>,
    pub(super) evidence: Option<LiveLanguageEvidence>,
}

/// Session-scoped policy state around one resident detector instance.
pub(super) struct LiveLanguageSession {
    pipeline: Option<ResidentLanguagePipeline>,
    primary_language_bcp47: String,
    mode: LiveLanguageMode,
    initial_degradation: Option<LiveLanguageDegradation>,
    active: bool,
    degradation: Option<LiveLanguageDegradation>,
    spans: Vec<LanguageSpan>,
    source_end_sample: Option<u64>,
}

impl LiveLanguageSession {
    pub(super) fn new(
        pipeline: Option<ResidentLanguagePipeline>,
        primary_language_bcp47: String,
        initial_degradation: Option<LiveLanguageDegradation>,
        mode: LiveLanguageMode,
    ) -> Self {
        Self {
            active: pipeline.is_some() && initial_degradation.is_none(),
            pipeline,
            primary_language_bcp47,
            mode,
            initial_degradation,
            degradation: None,
            spans: Vec::new(),
            source_end_sample: None,
        }
    }

    pub(super) fn begin_session(&mut self) -> bool {
        self.spans.clear();
        self.source_end_sample = None;
        self.degradation = self.initial_degradation;
        self.active = self.pipeline.is_some() && self.degradation.is_none();
        if self.active {
            if let Some(pipeline) = self.pipeline.as_mut() {
                if pipeline.reset_session().is_err() {
                    self.active = false;
                    self.degradation = Some(LiveLanguageDegradation::RoutingFailed);
                }
            }
        }
        self.degradation.is_some()
    }

    pub(super) fn push(&mut self, frame: PreparedFrame) -> Result<LanguageFramePlan, String> {
        let observed = match observed_frame_range(&frame) {
            Ok(range) => range,
            Err(_) => {
                let degradation_started =
                    self.begin_degradation(LiveLanguageDegradation::RoutingFailed);
                return Ok(LanguageFramePlan {
                    actions: Vec::new(),
                    direct_primary_frame: Some(frame),
                    return_to_primary: true,
                    degradation_started,
                });
            }
        };
        self.source_end_sample = Some(observed.end_sample);
        if !self.active {
            return Ok(LanguageFramePlan {
                actions: Vec::new(),
                direct_primary_frame: Some(frame),
                return_to_primary: false,
                degradation_started: false,
            });
        }

        let fallback_frame = frame.clone();
        let result = self
            .pipeline
            .as_mut()
            .expect("an active language session owns a resident pipeline")
            .push(frame);
        match result {
            Ok(batch) => {
                self.source_end_sample = self
                    .pipeline
                    .as_ref()
                    .and_then(ResidentLanguagePipeline::source_end_sample);
                let actions = self.commit_batch(batch)?;
                Ok(LanguageFramePlan {
                    actions,
                    direct_primary_frame: None,
                    return_to_primary: false,
                    degradation_started: false,
                })
            }
            Err(failure) => {
                if failure.frame_admitted {
                    self.source_end_sample = self
                        .pipeline
                        .as_ref()
                        .and_then(ResidentLanguagePipeline::source_end_sample);
                }
                let mut actions = self.commit_batch(failure.committed_batch)?;
                let degradation = classify_pipeline_error(&failure.error);
                let routing = self
                    .pipeline
                    .as_mut()
                    .expect("an active language session owns a resident pipeline")
                    .abandon_detection();
                let mut return_to_primary = false;
                match routing {
                    Ok(routing) => {
                        if let Some(span) = routing.final_span {
                            return_to_primary = span.language_bcp47 != self.primary_language_bcp47;
                            self.append_span(span)?;
                        }
                        actions.extend(routing.actions);
                    }
                    Err(LanguagePipelineError::Routing(
                        LanguageRoutingError::SessionHasNoAudio,
                    )) if !failure.frame_admitted => {}
                    Err(error) => {
                        crate::stt::log_yap(&format!(
                            "live language fallback drain failed code={}",
                            pipeline_error_code(&error)
                        ));
                    }
                }
                let degradation_started = self.begin_degradation(degradation);
                Ok(LanguageFramePlan {
                    actions,
                    direct_primary_frame: (!failure.frame_admitted).then_some(fallback_frame),
                    return_to_primary,
                    degradation_started,
                })
            }
        }
    }

    pub(super) fn finish(&mut self) -> Result<LanguageFinishPlan, String> {
        let mut actions = Vec::new();
        if self.active && self.source_end_sample.is_some() {
            let result = self
                .pipeline
                .as_mut()
                .expect("an active language session owns a resident pipeline")
                .finish();
            match result {
                Ok(finish) => {
                    actions.extend(self.commit_batch(finish.batch)?);
                    if let Some(span) = finish.routing.final_span {
                        self.source_end_sample = Some(span.end_sample);
                        self.append_span(span)?;
                    }
                    actions.extend(finish.routing.actions);
                }
                Err(failure) => {
                    actions.extend(self.commit_batch(failure.committed_batch)?);
                    self.begin_degradation(classify_pipeline_error(&failure.error));
                    match self
                        .pipeline
                        .as_mut()
                        .expect("an active language session owns a resident pipeline")
                        .abandon_detection()
                    {
                        Ok(routing) => {
                            if let Some(span) = routing.final_span {
                                self.source_end_sample = Some(span.end_sample);
                                self.append_span(span)?;
                            }
                            actions.extend(routing.actions);
                        }
                        Err(error) => crate::stt::log_yap(&format!(
                            "live language finish fallback failed code={}",
                            pipeline_error_code(&error)
                        )),
                    }
                }
            }
        }
        self.active = false;
        let evidence = self.complete_evidence()?;
        Ok(LanguageFinishPlan { actions, evidence })
    }

    pub(super) fn primary_language_bcp47(&self) -> &str {
        &self.primary_language_bcp47
    }

    fn commit_batch(
        &mut self,
        batch: LanguagePipelineBatch,
    ) -> Result<Vec<LanguageAudioAction>, String> {
        for decision in batch.decisions {
            if let LanguageDecisionOutcome::Switched(transition) = decision {
                let transition = *transition;
                if let Some(span) = transition.completed_span {
                    self.append_span(span)?;
                }
            }
        }
        Ok(batch.actions)
    }

    fn append_span(&mut self, span: LanguageSpan) -> Result<(), String> {
        let expected_start = self.spans.last().map_or(0, |previous| previous.end_sample);
        let expected_revision = self.spans.len() as u64 + 1;
        if span.start_sample != expected_start
            || span.end_sample <= span.start_sample
            || span.decision_revision != expected_revision
        {
            return Err("live language span sequence became inconsistent".into());
        }
        self.spans.push(span);
        Ok(())
    }

    fn begin_degradation(&mut self, degradation: LiveLanguageDegradation) -> bool {
        let started = self.degradation.is_none();
        self.degradation.get_or_insert(degradation);
        self.active = false;
        started
    }

    fn complete_evidence(&mut self) -> Result<Option<LiveLanguageEvidence>, String> {
        let Some(source_end_sample) = self.source_end_sample.filter(|end| *end > 0) else {
            return Ok(None);
        };
        match self.spans.last().map(|last| {
            (
                last.end_sample,
                last.language_bcp47 == self.primary_language_bcp47,
                last.decision_revision,
            )
        }) {
            None => self.spans.push(LanguageSpan {
                start_sample: 0,
                end_sample: source_end_sample,
                language_bcp47: self.primary_language_bcp47.clone(),
                decision_revision: 1,
                disposition: LanguageSpanDisposition::ConfirmedPrimary,
                component_revision: None,
                decision_evidence: None,
            }),
            Some((last_end_sample, is_primary, last_revision))
                if last_end_sample < source_end_sample =>
            {
                if is_primary {
                    self.spans
                        .last_mut()
                        .expect("the final language span was just observed")
                        .end_sample = source_end_sample;
                } else {
                    self.spans.push(LanguageSpan {
                        start_sample: last_end_sample,
                        end_sample: source_end_sample,
                        language_bcp47: self.primary_language_bcp47.clone(),
                        decision_revision: last_revision + 1,
                        disposition: LanguageSpanDisposition::FallbackPrimary,
                        component_revision: None,
                        decision_evidence: None,
                    });
                }
            }
            Some((last_end_sample, _, _)) if last_end_sample > source_end_sample => {
                return Err("live language evidence exceeds captured source time".into())
            }
            Some(_) => {}
        }
        let status = if self.degradation.is_some() {
            LiveLanguageStatus::Degraded
        } else {
            LiveLanguageStatus::Complete
        };
        LiveLanguageEvidence::try_new(
            source_end_sample,
            self.primary_language_bcp47.clone(),
            self.mode,
            status,
            self.degradation,
            self.pipeline
                .as_ref()
                .map(|pipeline| pipeline.component_revision().to_owned()),
            std::mem::take(&mut self.spans),
        )
        .map(Some)
        .map_err(|error| error.to_string())
    }
}

fn classify_pipeline_error(error: &LanguagePipelineError) -> LiveLanguageDegradation {
    match error {
        LanguagePipelineError::Detector(_) => LiveLanguageDegradation::DetectorFailed,
        LanguagePipelineError::Routing(LanguageRoutingError::SourceAudio(
            SourceAudioError::Discontinuity { .. },
        )) => LiveLanguageDegradation::SourceDiscontinuity,
        LanguagePipelineError::Routing(LanguageRoutingError::SourceAudio(
            SourceAudioError::CapacityExceeded,
        )) => LiveLanguageDegradation::HoldbackCapacityExceeded,
        LanguagePipelineError::InvalidWindowConfiguration
        | LanguagePipelineError::SourceRangeDiverged
        | LanguagePipelineError::Routing(_) => LiveLanguageDegradation::RoutingFailed,
    }
}

fn pipeline_error_code(error: &LanguagePipelineError) -> &'static str {
    match classify_pipeline_error(error) {
        LiveLanguageDegradation::ArtifactsUnavailable => "artifacts_unavailable",
        LiveLanguageDegradation::DetectorFailed => "detector_failed",
        LiveLanguageDegradation::RoutingFailed => "routing_failed",
        LiveLanguageDegradation::SourceDiscontinuity => "source_discontinuity",
        LiveLanguageDegradation::HoldbackCapacityExceeded => "holdback_capacity_exceeded",
    }
}
