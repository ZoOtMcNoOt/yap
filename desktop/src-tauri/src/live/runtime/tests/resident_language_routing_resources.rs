use super::*;
use crate::{
    audio::coordinator::{bounded_sink, SinkKind, LOCAL_ASR_QUEUE_CAPACITY},
    language::live_catalog::{available_automatic_alternates, base_language, LocalLanguageCatalog},
    live::{
        language_pipeline::load_resident_language_pipeline,
        language_router::LanguageAudioAction,
        stream::{self, LiveStreamEngine, StreamLanguageTransition},
    },
    private_evidence::publish_private_json,
};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    io::Read,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    thread,
    time::{Duration, Instant},
};

const SAMPLE_RATE_HZ: u32 = 16_000;
const PROFILE_PRIMARY_LANGUAGE_BCP47: &str = "en-US";
const MINIMUM_PROFILE_AUDIO_SECONDS: u64 = 30;
const MAXIMUM_PROFILE_AUDIO_SECONDS: u64 = 120;
const MAXIMUM_PROFILE_AUDIO_BYTES: u64 = 4 * 1_024 * 1_024;
const PACED_FRAME_SAMPLES: usize = 160;
const RESPONSIVENESS_TICK: Duration = Duration::from_millis(10);
const MAXIMUM_RESPONSIVENESS_P95_DELAY_US: u128 = 50_000;
const MAXIMUM_RESPONSIVENESS_DELAY_US: u128 = 250_000;
const MAXIMUM_PACED_DRAIN_MS: u128 = 6_000;
const MAXIMUM_PACED_SESSION_CYCLES: usize = 32;
const MAXIMUM_SUSTAINED_PRIVATE_BYTE_GROWTH: i64 = 64 * 1_024 * 1_024;

#[derive(Debug, Clone, Copy, Serialize)]
#[serde(rename_all = "camelCase")]
struct ProcessResourceSnapshot {
    working_set_bytes: u64,
    peak_working_set_bytes: u64,
    private_bytes: u64,
    process_cpu_ms: u64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ResidentLanguageRoutingProfile {
    schema_version: u8,
    component_revision: String,
    audio_fixture_sha256: String,
    audio_fixture_byte_length: u64,
    logical_processor_budget: usize,
    local_asr_threads: i32,
    audio_ms: u64,
    source_samples: usize,
    enabled_locales: usize,
    nemotron_load_ms: u128,
    language_pipeline_load_ms: u128,
    baseline_asr_wall_ms: u128,
    resident_asr_wall_ms: u128,
    combined_routing_wall_ms: u128,
    baseline_asr_rtf: f64,
    resident_asr_rtf: f64,
    combined_routing_rtf: f64,
    combined_real_time_gate_passed: bool,
    resident_to_baseline_wall_ratio: f64,
    combined_to_baseline_wall_ratio: f64,
    combined_to_resident_wall_ratio: f64,
    baseline_asr_cpu_ms: u64,
    language_pipeline_load_cpu_ms: u64,
    resident_asr_cpu_ms: u64,
    combined_routing_cpu_ms: u64,
    baseline_asr_average_cpu_cores: f64,
    resident_asr_average_cpu_cores: f64,
    combined_routing_average_cpu_cores: f64,
    combined_cpu_budget_fraction: f64,
    language_observation_windows: usize,
    pipeline_push_p50_us: u128,
    pipeline_push_p95_us: u128,
    pipeline_push_maximum_us: u128,
    language_pipeline_incremental_private_bytes: i64,
    language_pipeline_teardown_residual_private_bytes: i64,
    language_switches: usize,
    routed_samples: usize,
    paced: PacedResidentLanguageRoutingProfile,
    sustained: SustainedResidentLanguageRoutingProfile,
    after_nemotron_warmup: ProcessResourceSnapshot,
    after_baseline_asr: ProcessResourceSnapshot,
    after_language_pipeline: ProcessResourceSnapshot,
    after_resident_asr: ProcessResourceSnapshot,
    after_combined_routing: ProcessResourceSnapshot,
    after_paced_routing: ProcessResourceSnapshot,
    after_sustained_routing: ProcessResourceSnapshot,
    after_pipeline_drop: ProcessResourceSnapshot,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SustainedResidentLanguageRoutingProfile {
    requested_cycles: usize,
    completed_cycles: usize,
    all_cycles_passed: bool,
    maximum_queue_high_water_mark: usize,
    maximum_drain_wall_ms: u128,
    maximum_responsiveness_p95_delay_us: u128,
    maximum_responsiveness_delay_us: u128,
    private_byte_growth: i64,
    maximum_cycle_end_private_byte_growth: i64,
    private_byte_growth_limit: i64,
    memory_plateau_gate_passed: bool,
    sustained_gate_passed: bool,
    cycles: Vec<PacedResidentLanguageRoutingProfile>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct PacedResidentLanguageRoutingProfile {
    frame_samples: usize,
    expected_frames: u64,
    accepted_frames: u64,
    dropped_frames: u64,
    queue_capacity: usize,
    queue_high_water_mark: usize,
    source_wall_ms: u128,
    source_overrun_ms: u128,
    completion_wall_ms: u128,
    drain_wall_ms: u128,
    process_cpu_ms: u64,
    average_cpu_cores: f64,
    cpu_budget_fraction: f64,
    routed_samples: usize,
    language_observation_windows: usize,
    language_switches: usize,
    text_seen: bool,
    processing_succeeded: bool,
    responsiveness_tick_ms: u128,
    responsiveness_sample_count: usize,
    responsiveness_p50_delay_us: u128,
    responsiveness_p95_delay_us: u128,
    responsiveness_p99_delay_us: u128,
    responsiveness_maximum_delay_us: u128,
    zero_audio_loss_gate_passed: bool,
    interactive_scheduler_gate_passed: bool,
    bounded_drain_gate_passed: bool,
    paced_gate_passed: bool,
}

struct PacedWorkerResult {
    routed_samples: usize,
    language_observation_windows: usize,
    language_switches: usize,
    text_seen: bool,
}

/// Runs the exact resident desktop path against private, hash-controlled model
/// staging. The test emits aggregate resource evidence only; it never prints
/// the fixture path or transcript.
#[test]
#[ignore = "requires a private YAP_MODELS_DIR containing pinned Nemotron, Silero, and AmberNet artifacts plus YAP_TEST_LOCAL_ROUTING_AUDIO"]
fn resident_language_routing_profiles_nemotron_interference_and_teardown() {
    let fixture = required_path("YAP_TEST_LOCAL_ROUTING_AUDIO");
    let expected_fixture_sha256 = required_sha256("YAP_TEST_LOCAL_ROUTING_AUDIO_SHA256");
    let fixture_metadata = fixture
        .metadata()
        .expect("profile fixture metadata must be readable");
    assert!(fixture_metadata.is_file(), "profile fixture must be a file");
    assert!(
        fixture_metadata.len() <= MAXIMUM_PROFILE_AUDIO_BYTES,
        "profile fixture exceeds the bounded WAV size"
    );
    let fixture_sha256 = sha256_file(&fixture);
    assert_eq!(
        fixture_sha256, expected_fixture_sha256,
        "profile fixture SHA-256 differs from the frozen identity"
    );
    let repeat = std::env::var("YAP_TEST_LOCAL_ROUTING_AUDIO_REPEAT")
        .ok()
        .map(|value| value.parse::<usize>().expect("repeat must be an integer"))
        .unwrap_or(1);
    assert!((1..=32).contains(&repeat));
    let wave = sherpa_onnx::Wave::read(fixture.to_str().expect("fixture path must be UTF-8"))
        .expect("profile fixture must be a readable WAV");
    assert_eq!(
        sha256_file(&fixture),
        fixture_sha256,
        "profile fixture changed while it was being decoded"
    );
    assert_eq!(wave.sample_rate(), SAMPLE_RATE_HZ as i32);
    assert!(!wave.samples().is_empty());
    let mut samples = Vec::with_capacity(wave.samples().len() * repeat);
    for _ in 0..repeat {
        samples.extend_from_slice(wave.samples());
    }
    let audio_seconds = samples.len() as u64 / SAMPLE_RATE_HZ as u64;
    assert!(
        (MINIMUM_PROFILE_AUDIO_SECONDS..=MAXIMUM_PROFILE_AUDIO_SECONDS).contains(&audio_seconds),
        "resource fixture must provide 30 to 120 seconds after repetition"
    );
    let audio_ms = samples.len() as u64 * 1_000 / SAMPLE_RATE_HZ as u64;
    let local_asr_threads = std::env::var("YAP_TEST_LOCAL_ASR_THREADS")
        .ok()
        .map(|value| {
            value
                .parse::<i32>()
                .expect("local ASR threads must be an integer")
        })
        .unwrap_or(crate::stt::nemotron::INFERENCE_THREADS);
    assert!(
        (1..=crate::stt::nemotron::INFERENCE_THREADS).contains(&local_asr_threads),
        "local ASR threads must stay within the supported profile range"
    );
    let paced_session_cycles = std::env::var("YAP_TEST_LOCAL_ROUTING_SESSION_CYCLES")
        .ok()
        .map(|value| {
            value
                .parse::<usize>()
                .expect("paced session cycles must be an integer")
        })
        .unwrap_or(1);
    assert!(
        (1..=MAXIMUM_PACED_SESSION_CYCLES).contains(&paced_session_cycles),
        "paced session cycles must stay within the bounded profile range"
    );

    let nemotron_load_started = Instant::now();
    let mut engine = LiveStreamEngine::new_for_language_with_test_thread_budget(
        PROFILE_PRIMARY_LANGUAGE_BCP47,
        local_asr_threads,
    )
    .expect("the pinned local Nemotron model must load");
    let nemotron_load_ms = nemotron_load_started.elapsed().as_millis();

    let (_warmup_wall_ms, warmup_text_seen) = transcribe_samples(&mut engine, &samples);
    assert!(warmup_text_seen, "Nemotron warmup emitted no text");
    reset_engine_to_profile_primary(&mut engine);
    let after_nemotron_warmup = process_resource_snapshot();

    let (baseline_asr_wall_ms, baseline_text_seen) = transcribe_samples(&mut engine, &samples);
    assert!(baseline_text_seen, "baseline Nemotron emitted no text");
    let after_baseline_asr = process_resource_snapshot();
    reset_engine_to_profile_primary(&mut engine);

    let alternates = available_automatic_alternates(PROFILE_PRIMARY_LANGUAGE_BCP47)
        .into_iter()
        .fold(BTreeMap::new(), |mut by_base, locale| {
            by_base.entry(base_language(locale)).or_insert(locale);
            by_base
        });
    let catalog = LocalLanguageCatalog::nemotron_with_explicit_alternates(
        PROFILE_PRIMARY_LANGUAGE_BCP47,
        alternates.values().copied(),
    )
    .expect("the frozen automatic-language catalog must be valid");
    let enabled_locales = catalog.enabled_locales().count();
    let language_pipeline_load_started = Instant::now();
    let mut pipeline = load_resident_language_pipeline(catalog)
        .expect("the pinned AmberNet and Silero models must load");
    let language_pipeline_load_ms = language_pipeline_load_started.elapsed().as_millis();
    let component_revision = pipeline.component_revision().to_owned();
    let after_language_pipeline = process_resource_snapshot();

    let (resident_asr_wall_ms, resident_text_seen) = transcribe_samples(&mut engine, &samples);
    assert!(
        resident_text_seen,
        "Nemotron emitted no text while the language pipeline was resident"
    );
    let after_resident_asr = process_resource_snapshot();
    reset_engine_to_profile_primary(&mut engine);

    let combined_started = Instant::now();
    let mut routed_samples = 0;
    let mut language_switches = 0;
    let mut combined_text_seen = false;
    let mut language_observation_windows = 0;
    let mut pipeline_push_us = Vec::new();
    let mut asr_input = ProfileAsrInputBuffer::default();
    for (sequence, chunk) in samples.chunks(SAMPLE_RATE_HZ as usize).enumerate() {
        let push_started = Instant::now();
        let batch = pipeline
            .push(profile_frame(sequence as u64, chunk))
            .expect("the resident language pipeline must accept ordered source audio");
        pipeline_push_us.push(push_started.elapsed().as_micros());
        language_observation_windows += batch.decisions.len();
        apply_actions(
            &mut engine,
            batch.actions,
            &mut routed_samples,
            &mut language_switches,
            &mut combined_text_seen,
            &mut asr_input,
        );
    }
    let finish = pipeline
        .finish()
        .expect("the resident language pipeline must finish");
    language_observation_windows += finish.batch.decisions.len();
    apply_actions(
        &mut engine,
        finish.batch.actions,
        &mut routed_samples,
        &mut language_switches,
        &mut combined_text_seen,
        &mut asr_input,
    );
    apply_actions(
        &mut engine,
        finish.routing.actions,
        &mut routed_samples,
        &mut language_switches,
        &mut combined_text_seen,
        &mut asr_input,
    );
    asr_input.drain(&mut engine, true, &mut combined_text_seen);
    combined_text_seen |= engine.finish().is_some();
    let combined_routing_wall_ms = combined_started.elapsed().as_millis();
    assert!(combined_text_seen, "combined resident path emitted no text");
    assert_eq!(routed_samples, samples.len());
    let after_combined_routing = process_resource_snapshot();

    reset_engine_to_profile_primary(&mut engine);
    pipeline
        .reset_session()
        .expect("the resident language pipeline must reset before paced input");
    let before_paced_routing = process_resource_snapshot();
    let paced = run_paced_resident_path(
        &mut engine,
        &mut pipeline,
        &samples,
        audio_ms,
        process_logical_processor_budget(),
        before_paced_routing,
    );
    let after_paced_routing = process_resource_snapshot();

    let mut sustained_cycles = Vec::with_capacity(paced_session_cycles);
    let mut sustained_cycle_ends = Vec::with_capacity(paced_session_cycles);
    sustained_cycles.push(paced.clone());
    sustained_cycle_ends.push(after_paced_routing);
    for _ in 1..paced_session_cycles {
        reset_engine_to_profile_primary(&mut engine);
        pipeline
            .reset_session()
            .expect("the resident language pipeline must reset between paced sessions");
        let before_cycle = process_resource_snapshot();
        sustained_cycles.push(run_paced_resident_path(
            &mut engine,
            &mut pipeline,
            &samples,
            audio_ms,
            process_logical_processor_budget(),
            before_cycle,
        ));
        sustained_cycle_ends.push(process_resource_snapshot());
    }
    let after_sustained_routing = sustained_cycle_ends
        .last()
        .copied()
        .unwrap_or(after_paced_routing);
    let sustained_private_byte_growth = signed_byte_delta(
        after_sustained_routing.private_bytes,
        after_paced_routing.private_bytes,
    );
    let maximum_cycle_end_private_byte_growth = sustained_cycle_ends
        .iter()
        .map(|snapshot| {
            signed_byte_delta(snapshot.private_bytes, after_paced_routing.private_bytes)
        })
        .max()
        .unwrap_or(0);
    let all_cycles_passed = sustained_cycles.iter().all(|cycle| cycle.paced_gate_passed);
    let sustained = SustainedResidentLanguageRoutingProfile {
        requested_cycles: paced_session_cycles,
        completed_cycles: sustained_cycles.len(),
        all_cycles_passed,
        maximum_queue_high_water_mark: sustained_cycles
            .iter()
            .map(|cycle| cycle.queue_high_water_mark)
            .max()
            .unwrap_or(0),
        maximum_drain_wall_ms: sustained_cycles
            .iter()
            .map(|cycle| cycle.drain_wall_ms)
            .max()
            .unwrap_or(0),
        maximum_responsiveness_p95_delay_us: sustained_cycles
            .iter()
            .map(|cycle| cycle.responsiveness_p95_delay_us)
            .max()
            .unwrap_or(0),
        maximum_responsiveness_delay_us: sustained_cycles
            .iter()
            .map(|cycle| cycle.responsiveness_maximum_delay_us)
            .max()
            .unwrap_or(0),
        private_byte_growth: sustained_private_byte_growth,
        maximum_cycle_end_private_byte_growth,
        private_byte_growth_limit: MAXIMUM_SUSTAINED_PRIVATE_BYTE_GROWTH,
        memory_plateau_gate_passed: sustained_private_byte_growth
            <= MAXIMUM_SUSTAINED_PRIVATE_BYTE_GROWTH
            && maximum_cycle_end_private_byte_growth <= MAXIMUM_SUSTAINED_PRIVATE_BYTE_GROWTH,
        sustained_gate_passed: all_cycles_passed
            && sustained_private_byte_growth <= MAXIMUM_SUSTAINED_PRIVATE_BYTE_GROWTH
            && maximum_cycle_end_private_byte_growth <= MAXIMUM_SUSTAINED_PRIVATE_BYTE_GROWTH,
        cycles: sustained_cycles,
    };

    drop(pipeline);
    let after_pipeline_drop = process_resource_snapshot();
    let baseline_asr_rtf = baseline_asr_wall_ms as f64 / audio_ms as f64;
    let resident_asr_rtf = resident_asr_wall_ms as f64 / audio_ms as f64;
    let combined_routing_rtf = combined_routing_wall_ms as f64 / audio_ms as f64;
    let combined_real_time_gate_passed = combined_routing_rtf < 1.0;
    let logical_processor_budget = process_logical_processor_budget();
    let baseline_asr_cpu_ms = process_cpu_delta_ms(after_baseline_asr, after_nemotron_warmup);
    let language_pipeline_load_cpu_ms =
        process_cpu_delta_ms(after_language_pipeline, after_baseline_asr);
    let resident_asr_cpu_ms = process_cpu_delta_ms(after_resident_asr, after_language_pipeline);
    let combined_routing_cpu_ms = process_cpu_delta_ms(after_combined_routing, after_resident_asr);
    let baseline_asr_average_cpu_cores =
        average_cpu_cores(baseline_asr_cpu_ms, baseline_asr_wall_ms);
    let resident_asr_average_cpu_cores =
        average_cpu_cores(resident_asr_cpu_ms, resident_asr_wall_ms);
    let combined_routing_average_cpu_cores =
        average_cpu_cores(combined_routing_cpu_ms, combined_routing_wall_ms);
    pipeline_push_us.sort_unstable();
    let profile = ResidentLanguageRoutingProfile {
        schema_version: 5,
        component_revision,
        audio_fixture_sha256: fixture_sha256,
        audio_fixture_byte_length: fixture_metadata.len(),
        logical_processor_budget,
        local_asr_threads,
        audio_ms,
        source_samples: samples.len(),
        enabled_locales,
        nemotron_load_ms,
        language_pipeline_load_ms,
        baseline_asr_wall_ms,
        resident_asr_wall_ms,
        combined_routing_wall_ms,
        baseline_asr_rtf,
        resident_asr_rtf,
        combined_routing_rtf,
        combined_real_time_gate_passed,
        resident_to_baseline_wall_ratio: resident_asr_wall_ms as f64
            / baseline_asr_wall_ms.max(1) as f64,
        combined_to_baseline_wall_ratio: combined_routing_wall_ms as f64
            / baseline_asr_wall_ms.max(1) as f64,
        combined_to_resident_wall_ratio: combined_routing_wall_ms as f64
            / resident_asr_wall_ms.max(1) as f64,
        baseline_asr_cpu_ms,
        language_pipeline_load_cpu_ms,
        resident_asr_cpu_ms,
        combined_routing_cpu_ms,
        baseline_asr_average_cpu_cores,
        resident_asr_average_cpu_cores,
        combined_routing_average_cpu_cores,
        combined_cpu_budget_fraction: combined_routing_average_cpu_cores
            / logical_processor_budget as f64,
        language_observation_windows,
        pipeline_push_p50_us: nearest_rank(&pipeline_push_us, 50),
        pipeline_push_p95_us: nearest_rank(&pipeline_push_us, 95),
        pipeline_push_maximum_us: pipeline_push_us.last().copied().unwrap_or(0),
        language_pipeline_incremental_private_bytes: signed_byte_delta(
            after_language_pipeline.private_bytes,
            after_baseline_asr.private_bytes,
        ),
        language_pipeline_teardown_residual_private_bytes: signed_byte_delta(
            after_pipeline_drop.private_bytes,
            after_baseline_asr.private_bytes,
        ),
        language_switches,
        routed_samples,
        paced,
        sustained,
        after_nemotron_warmup,
        after_baseline_asr,
        after_language_pipeline,
        after_resident_asr,
        after_combined_routing,
        after_paced_routing,
        after_sustained_routing,
        after_pipeline_drop,
    };
    persist_private_profile_if_requested(&profile);
    eprintln!(
        "resident_language_routing_profile={}",
        serde_json::to_string(&profile).unwrap()
    );
    assert!(
        profile.combined_real_time_gate_passed,
        "combined local path fell behind real time"
    );
    assert!(
        profile.paced.paced_gate_passed,
        "paced local path lost audio, exceeded the scheduler budget, or failed to drain"
    );
    assert!(
        profile.sustained.sustained_gate_passed,
        "sustained local path lost audio, exceeded a responsiveness/drain budget, or failed to reach a memory plateau"
    );
}

fn run_paced_resident_path<D>(
    engine: &mut LiveStreamEngine,
    pipeline: &mut crate::live::language_pipeline::LiveLanguagePipeline<D>,
    samples: &[f32],
    audio_ms: u64,
    logical_processor_budget: usize,
    before: ProcessResourceSnapshot,
) -> PacedResidentLanguageRoutingProfile
where
    D: crate::live::language_pipeline::LanguageWindowDetector + Send,
{
    let (frames, receiver) = bounded_sink(SinkKind::LocalAsr, LOCAL_ASR_QUEUE_CAPACITY);
    let responsiveness_done = Arc::new(AtomicBool::new(false));
    let started = Instant::now();
    let (source_wall_ms, worker_result, mut responsiveness_delays_us) = thread::scope(|scope| {
        let worker = scope.spawn(move || -> Result<PacedWorkerResult, String> {
            let mut routed_samples = 0;
            let mut language_switches = 0;
            let mut text_seen = false;
            let mut language_observation_windows = 0;
            let mut asr_input = ProfileAsrInputBuffer::default();
            loop {
                let frame = match receiver.recv_timeout(Duration::from_millis(100)) {
                    Ok(frame) => frame,
                    Err(std::sync::mpsc::RecvTimeoutError::Timeout) => continue,
                    Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
                };
                let batch = pipeline
                    .push(frame)
                    .map_err(|_| "paced language routing rejected source audio".to_string())?;
                language_observation_windows += batch.decisions.len();
                apply_actions(
                    engine,
                    batch.actions,
                    &mut routed_samples,
                    &mut language_switches,
                    &mut text_seen,
                    &mut asr_input,
                );
            }
            let finish = pipeline
                .finish()
                .map_err(|_| "paced language routing could not finish".to_string())?;
            language_observation_windows += finish.batch.decisions.len();
            apply_actions(
                engine,
                finish.batch.actions,
                &mut routed_samples,
                &mut language_switches,
                &mut text_seen,
                &mut asr_input,
            );
            apply_actions(
                engine,
                finish.routing.actions,
                &mut routed_samples,
                &mut language_switches,
                &mut text_seen,
                &mut asr_input,
            );
            asr_input.drain(engine, true, &mut text_seen);
            text_seen |= engine.finish().is_some();
            Ok(PacedWorkerResult {
                routed_samples,
                language_observation_windows,
                language_switches,
                text_seen,
            })
        });
        let heartbeat_done = Arc::clone(&responsiveness_done);
        let heartbeat = scope.spawn(move || responsiveness_delays(heartbeat_done));

        let source_started = Instant::now();
        let mut source_samples = 0_usize;
        for (sequence, chunk) in samples.chunks(PACED_FRAME_SAMPLES).enumerate() {
            source_samples += chunk.len();
            sleep_until(source_started + source_duration(source_samples));
            let start_sample = source_samples - chunk.len();
            let _ = frames.try_send(profile_frame_at(
                sequence as u64,
                start_sample as u64,
                chunk,
            ));
        }
        let source_wall_ms = source_started.elapsed().as_millis();
        frames.close();
        let worker_result = worker.join();
        responsiveness_done.store(true, Ordering::Release);
        let responsiveness_delays = heartbeat
            .join()
            .expect("responsiveness sampler must not panic");
        let worker_result = worker_result.expect("paced local inference worker must not panic");
        (source_wall_ms, worker_result, responsiveness_delays)
    });
    let completion_wall_ms = started.elapsed().as_millis();
    let after = process_resource_snapshot();
    let outcome = frames.outcome();
    let expected_frames = samples.len().div_ceil(PACED_FRAME_SAMPLES) as u64;
    let source_overrun_ms = source_wall_ms.saturating_sub(u128::from(audio_ms));
    let drain_wall_ms = completion_wall_ms.saturating_sub(source_wall_ms);
    let process_cpu_ms = process_cpu_delta_ms(after, before);
    let average_cpu_cores = average_cpu_cores(process_cpu_ms, completion_wall_ms);
    responsiveness_delays_us.sort_unstable();
    let (
        processing_succeeded,
        routed_samples,
        language_observation_windows,
        language_switches,
        text_seen,
    ) = match worker_result {
        Ok(result) => (
            true,
            result.routed_samples,
            result.language_observation_windows,
            result.language_switches,
            result.text_seen,
        ),
        Err(_) => (false, 0, 0, 0, false),
    };
    let responsiveness_p95_delay_us = nearest_rank(&responsiveness_delays_us, 95);
    let responsiveness_maximum_delay_us = responsiveness_delays_us
        .last()
        .copied()
        .unwrap_or(u128::MAX);
    let zero_audio_loss_gate_passed = processing_succeeded
        && outcome.dropped_frames == 0
        && outcome.accepted_frames == expected_frames
        && routed_samples == samples.len();
    let interactive_scheduler_gate_passed = responsiveness_p95_delay_us
        <= MAXIMUM_RESPONSIVENESS_P95_DELAY_US
        && responsiveness_maximum_delay_us <= MAXIMUM_RESPONSIVENESS_DELAY_US;
    let bounded_drain_gate_passed = drain_wall_ms <= MAXIMUM_PACED_DRAIN_MS;
    PacedResidentLanguageRoutingProfile {
        frame_samples: PACED_FRAME_SAMPLES,
        expected_frames,
        accepted_frames: outcome.accepted_frames,
        dropped_frames: outcome.dropped_frames,
        queue_capacity: LOCAL_ASR_QUEUE_CAPACITY,
        queue_high_water_mark: frames.high_water_mark(),
        source_wall_ms,
        source_overrun_ms,
        completion_wall_ms,
        drain_wall_ms,
        process_cpu_ms,
        average_cpu_cores,
        cpu_budget_fraction: average_cpu_cores / logical_processor_budget as f64,
        routed_samples,
        language_observation_windows,
        language_switches,
        text_seen,
        processing_succeeded,
        responsiveness_tick_ms: RESPONSIVENESS_TICK.as_millis(),
        responsiveness_sample_count: responsiveness_delays_us.len(),
        responsiveness_p50_delay_us: nearest_rank(&responsiveness_delays_us, 50),
        responsiveness_p95_delay_us,
        responsiveness_p99_delay_us: nearest_rank(&responsiveness_delays_us, 99),
        responsiveness_maximum_delay_us,
        zero_audio_loss_gate_passed,
        interactive_scheduler_gate_passed,
        bounded_drain_gate_passed,
        paced_gate_passed: zero_audio_loss_gate_passed
            && interactive_scheduler_gate_passed
            && bounded_drain_gate_passed,
    }
}

fn responsiveness_delays(done: Arc<AtomicBool>) -> Vec<u128> {
    let mut delays = Vec::new();
    let mut previous = Instant::now();
    while !done.load(Ordering::Acquire) {
        thread::sleep(RESPONSIVENESS_TICK);
        let now = Instant::now();
        delays.push(
            now.duration_since(previous)
                .saturating_sub(RESPONSIVENESS_TICK)
                .as_micros(),
        );
        previous = now;
    }
    delays
}

fn source_duration(samples: usize) -> Duration {
    Duration::from_nanos(
        u64::try_from(samples)
            .expect("profile sample count must fit in u64")
            .saturating_mul(1_000_000_000)
            / u64::from(SAMPLE_RATE_HZ),
    )
}

fn reset_engine_to_profile_primary(engine: &mut LiveStreamEngine) {
    engine
        .reset_for_language(PROFILE_PRIMARY_LANGUAGE_BCP47)
        .expect("the resource profile must reset Nemotron to its primary language");
}

fn sleep_until(deadline: Instant) {
    if let Some(remaining) = deadline.checked_duration_since(Instant::now()) {
        thread::sleep(remaining);
    }
}

fn transcribe_samples(engine: &mut LiveStreamEngine, samples: &[f32]) -> (u128, bool) {
    let started = Instant::now();
    let mut text_seen = false;
    for chunk in samples.chunks(stream::chunk_samples()) {
        text_seen |= engine.accept_samples(chunk).is_some();
    }
    text_seen |= engine.finish().is_some();
    (started.elapsed().as_millis(), text_seen)
}

fn process_cpu_delta_ms(after: ProcessResourceSnapshot, before: ProcessResourceSnapshot) -> u64 {
    after.process_cpu_ms.saturating_sub(before.process_cpu_ms)
}

fn average_cpu_cores(cpu_ms: u64, wall_ms: u128) -> f64 {
    cpu_ms as f64 / wall_ms.max(1) as f64
}

fn signed_byte_delta(after: u64, before: u64) -> i64 {
    i128::from(after)
        .saturating_sub(i128::from(before))
        .clamp(i128::from(i64::MIN), i128::from(i64::MAX)) as i64
}

fn nearest_rank(sorted: &[u128], percentile: usize) -> u128 {
    assert!((1..=100).contains(&percentile));
    if sorted.is_empty() {
        return 0;
    }
    let rank = sorted.len().saturating_mul(percentile).saturating_add(99) / 100;
    sorted[rank.saturating_sub(1)]
}

#[test]
fn resource_profile_percentiles_use_nearest_rank() {
    let samples = [10, 20, 30, 40, 50];
    assert_eq!(nearest_rank(&samples, 50), 30);
    assert_eq!(nearest_rank(&samples, 95), 50);
}

#[test]
fn resource_profile_cpu_cores_are_derived_from_cpu_and_wall_time() {
    assert_eq!(average_cpu_cores(3_000, 1_000), 3.0);
    assert_eq!(average_cpu_cores(0, 0), 0.0);
}

#[test]
fn paced_source_duration_uses_exact_sample_time() {
    assert_eq!(source_duration(160), Duration::from_millis(10));
    assert_eq!(source_duration(16_000), Duration::from_secs(1));
}

#[cfg(windows)]
fn process_logical_processor_budget() -> usize {
    use windows::Win32::System::Threading::{GetCurrentProcess, GetProcessAffinityMask};

    let process = unsafe { GetCurrentProcess() };
    let mut process_mask = 0_usize;
    let mut system_mask = 0_usize;
    unsafe { GetProcessAffinityMask(process, &mut process_mask, &mut system_mask) }
        .expect("process affinity mask was unavailable");
    let budget = process_mask.count_ones() as usize;
    assert!(budget > 0, "process affinity mask contained no processors");
    budget
}

#[cfg(not(windows))]
fn process_logical_processor_budget() -> usize {
    std::thread::available_parallelism()
        .expect("logical processor budget must be available")
        .get()
}

fn persist_private_profile_if_requested(profile: &ResidentLanguageRoutingProfile) {
    let Ok(raw_destination) = std::env::var("YAP_TEST_LOCAL_ROUTING_EVIDENCE") else {
        return;
    };
    let destination = PathBuf::from(raw_destination);
    publish_private_json(&destination, profile)
        .unwrap_or_else(|error| panic!("failed to publish private resource evidence: {error}"));
}

fn apply_actions(
    engine: &mut LiveStreamEngine,
    actions: Vec<LanguageAudioAction>,
    routed_samples: &mut usize,
    language_switches: &mut usize,
    text_seen: &mut bool,
    asr_input: &mut ProfileAsrInputBuffer,
) {
    for action in actions {
        match action {
            LanguageAudioAction::Feed {
                language_bcp47,
                audio,
            } => {
                assert_eq!(engine.language_bcp47(), language_bcp47);
                *routed_samples += audio.samples.len();
                asr_input.samples.extend_from_slice(&audio.samples);
                asr_input.drain(engine, false, text_seen);
            }
            LanguageAudioAction::Switch(transition) => {
                assert_eq!(engine.language_bcp47(), transition.from_language_bcp47);
                asr_input.drain(engine, true, text_seen);
                if let StreamLanguageTransition::Switched { finalized_text } = engine
                    .transition_language(&transition.to_language_bcp47)
                    .expect("an accepted language transition must be supported")
                {
                    *language_switches += 1;
                    *text_seen |= finalized_text.is_some();
                }
            }
        }
    }
}

#[derive(Default)]
struct ProfileAsrInputBuffer {
    samples: Vec<f32>,
    start: usize,
}

impl ProfileAsrInputBuffer {
    /// Mirrors `StreamWorker::drain_buffer`: LID releases audio every 500 ms,
    /// but the pinned Nemotron path must still receive 1120 ms chunks.
    fn drain(&mut self, engine: &mut LiveStreamEngine, flush_all: bool, text_seen: &mut bool) {
        let chunk = stream::chunk_samples();
        while self.samples.len().saturating_sub(self.start) >= chunk
            || (flush_all && self.start < self.samples.len())
        {
            let available = self.samples.len() - self.start;
            let take = available.min(chunk);
            let end = self.start + take;
            *text_seen |= engine
                .accept_samples(&self.samples[self.start..end])
                .is_some();
            self.start = end;
        }
        if self.start == self.samples.len() {
            self.samples.clear();
            self.start = 0;
        } else if self.start >= chunk * 4 && self.start * 2 >= self.samples.len() {
            self.samples.drain(..self.start);
            self.start = 0;
        }
    }
}

fn profile_frame(sequence: u64, samples: &[f32]) -> PreparedFrame {
    profile_frame_at(sequence, sequence * SAMPLE_RATE_HZ as u64, samples)
}

fn profile_frame_at(sequence: u64, start_sample: u64, samples: &[f32]) -> PreparedFrame {
    PreparedFrame {
        metadata: AudioFrame {
            session_id: SessionId::new("resident-language-resource-profile").unwrap(),
            track_id: TrackId::new("microphone").unwrap(),
            sequence,
            sample_rate_hz: SAMPLE_RATE_HZ,
            channels: 1,
            start_ms: start_sample * 1_000 / SAMPLE_RATE_HZ as u64,
            duration_ms: u32::try_from(samples.len() as u64 * 1_000 / SAMPLE_RATE_HZ as u64)
                .unwrap(),
            sample_count: samples.len(),
        },
        samples: Arc::from(samples.to_vec()),
    }
}

fn required_path(environment: &str) -> PathBuf {
    PathBuf::from(
        std::env::var(environment).unwrap_or_else(|_| panic!("{environment} is required")),
    )
}

fn required_sha256(environment: &str) -> String {
    let value = std::env::var(environment).unwrap_or_else(|_| panic!("{environment} is required"));
    assert!(
        value.len() == 64
            && value
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)),
        "{environment} must be a lowercase SHA-256"
    );
    value
}

fn sha256_file(path: &Path) -> String {
    let mut input = std::fs::File::open(path).expect("profile fixture must open for hashing");
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 64 * 1_024];
    loop {
        let read = input
            .read(&mut buffer)
            .expect("profile fixture hashing must complete");
        if read == 0 {
            break;
        }
        digest.update(&buffer[..read]);
    }
    digest
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

#[cfg(windows)]
fn process_resource_snapshot() -> ProcessResourceSnapshot {
    use windows::Win32::{
        Foundation::FILETIME,
        System::{
            ProcessStatus::{
                K32GetProcessMemoryInfo, PROCESS_MEMORY_COUNTERS, PROCESS_MEMORY_COUNTERS_EX,
            },
            Threading::{GetCurrentProcess, GetProcessTimes},
        },
    };

    let process = unsafe { GetCurrentProcess() };
    let mut counters = PROCESS_MEMORY_COUNTERS_EX {
        cb: std::mem::size_of::<PROCESS_MEMORY_COUNTERS_EX>() as u32,
        ..Default::default()
    };
    let memory_ok = unsafe {
        K32GetProcessMemoryInfo(
            process,
            (&mut counters as *mut PROCESS_MEMORY_COUNTERS_EX).cast::<PROCESS_MEMORY_COUNTERS>(),
            counters.cb,
        )
    };
    assert!(
        memory_ok.as_bool(),
        "process memory counters were unavailable"
    );

    let mut creation = FILETIME::default();
    let mut exit = FILETIME::default();
    let mut kernel = FILETIME::default();
    let mut user = FILETIME::default();
    unsafe { GetProcessTimes(process, &mut creation, &mut exit, &mut kernel, &mut user) }
        .expect("process CPU counters were unavailable");

    ProcessResourceSnapshot {
        working_set_bytes: counters.WorkingSetSize as u64,
        peak_working_set_bytes: counters.PeakWorkingSetSize as u64,
        private_bytes: counters.PrivateUsage as u64,
        process_cpu_ms: (filetime_ticks(kernel) + filetime_ticks(user)) / 10_000,
    }
}

#[cfg(windows)]
fn filetime_ticks(value: windows::Win32::Foundation::FILETIME) -> u64 {
    (u64::from(value.dwHighDateTime) << 32) | u64::from(value.dwLowDateTime)
}

#[cfg(not(windows))]
fn process_resource_snapshot() -> ProcessResourceSnapshot {
    let status = std::fs::read_to_string("/proc/self/status")
        .expect("/proc process memory counters were unavailable");
    let kib = |name: &str| {
        status
            .lines()
            .find_map(|line| line.strip_prefix(name))
            .and_then(|value| value.split_whitespace().next())
            .and_then(|value| value.parse::<u64>().ok())
            .expect("/proc memory counter was invalid")
            * 1_024
    };
    ProcessResourceSnapshot {
        working_set_bytes: kib("VmRSS:"),
        peak_working_set_bytes: kib("VmHWM:"),
        private_bytes: kib("VmData:"),
        process_cpu_ms: 0,
    }
}
