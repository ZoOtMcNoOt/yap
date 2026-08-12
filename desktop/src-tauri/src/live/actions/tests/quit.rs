use std::cell::RefCell;

use super::super::quit::{
    cancel_transcript_corrections_before_quit, run_quit_with, QuitClaim, QuitCoordinator,
    QuitRunError,
};

#[test]
fn transcript_correction_shutdown_enters_the_async_runtime_on_its_worker_thread() {
    let owner = crate::transcript_correction::TranscriptCorrectionOwner::new();
    let cancelled = std::thread::spawn(move || cancel_transcript_corrections_before_quit(&owner))
        .join()
        .expect("transcript correction shutdown worker panicked")
        .expect("empty transcript correction owner failed shutdown");

    assert_eq!(cancelled, 0);
}

#[test]
fn quit_does_not_exit_when_finalization_fails() {
    let events = RefCell::new(Vec::new());

    let result = run_quit_with(
        || {
            events.borrow_mut().push("finalize");
            Err("save failed".to_string())
        },
        || {
            events.borrow_mut().push("exit");
        },
        || {
            events.borrow_mut().push("reopen");
            Ok(())
        },
    );

    assert_eq!(
        result,
        Err(QuitRunError::Finalization("save failed".into()))
    );
    assert_eq!(events.into_inner(), vec!["finalize", "reopen"]);
}

#[test]
fn quit_exits_only_after_successful_finalization() {
    let events = RefCell::new(Vec::new());

    let result = run_quit_with(
        || {
            events.borrow_mut().push("finalize");
            Ok(())
        },
        || {
            events.borrow_mut().push("exit");
        },
        || {
            events.borrow_mut().push("reopen");
            Ok(())
        },
    );

    assert_eq!(result, Ok(()));
    assert_eq!(events.into_inner(), vec!["finalize", "exit"]);
}

#[test]
fn repeated_quit_coalesces_and_cannot_bypass_an_unacknowledged_save_failure() {
    let quit = QuitCoordinator::new();

    assert_eq!(quit.claim(), QuitClaim::BeginShutdown);
    assert_eq!(quit.claim(), QuitClaim::Coalesced);
    quit.begin_finalizing(|| Ok(()), || Ok(())).unwrap();
    quit.finish(Err("save failed".into()));

    assert_eq!(quit.claim(), QuitClaim::Blocked("save failed".to_string()));
    assert!(!quit.exit_authorized());
}

#[test]
fn successful_quit_authorizes_only_the_semantic_exit_it_started() {
    let quit = QuitCoordinator::new();

    assert_eq!(quit.claim(), QuitClaim::BeginShutdown);
    quit.begin_finalizing(|| Ok(()), || Ok(())).unwrap();
    quit.finish(Ok(()));

    assert!(quit.exit_authorized());
    assert_eq!(quit.claim(), QuitClaim::ExitAuthorized);
}

#[test]
fn quit_cannot_become_finalizing_before_shutdown_publication() {
    let quit = QuitCoordinator::new();
    let events = RefCell::new(Vec::new());

    assert_eq!(quit.claim(), QuitClaim::BeginShutdown);
    assert!(!quit.finalization_started());
    quit.begin_finalizing(
        || {
            assert!(
                !quit.finalization_started(),
                "Finalizing became observable before shutdown publication"
            );
            events.borrow_mut().push("shutdown-published");
            Ok(())
        },
        || panic!("successful publication tried to reopen activation"),
    )
    .unwrap();
    events.borrow_mut().push("finalizing-observed");

    assert!(quit.finalization_started());
    assert_eq!(
        events.into_inner(),
        vec!["shutdown-published", "finalizing-observed"]
    );
    assert_eq!(quit.claim(), QuitClaim::Coalesced);
}

#[test]
fn shutdown_publication_failure_reopens_the_quit_claim() {
    let quit = QuitCoordinator::new();

    assert_eq!(quit.claim(), QuitClaim::BeginShutdown);
    assert_eq!(
        quit.begin_finalizing(|| Err("shutdown publication failed".into()), || Ok(())),
        Err("shutdown publication failed".into())
    );
    assert_eq!(quit.claim(), QuitClaim::BeginShutdown);
}

#[test]
fn shutdown_publication_rollback_failure_blocks_reentry() {
    let quit = QuitCoordinator::new();
    let expected = "shutdown publication failed; could not reopen activation after the failed shutdown transition: marker removal failed";

    assert_eq!(quit.claim(), QuitClaim::BeginShutdown);
    assert_eq!(
        quit.begin_finalizing(
            || Err("shutdown publication failed".into()),
            || Err("marker removal failed".into())
        ),
        Err(expected.into())
    );
    assert_eq!(quit.claim(), QuitClaim::Blocked(expected.into()));
}

#[test]
fn finalization_rollback_failure_is_reported_as_unsafe_shutdown() {
    let result = run_quit_with(
        || Err("save failed".to_string()),
        || panic!("exit preparation ran after finalization failed"),
        || Err("marker removal failed".to_string()),
    );

    assert_eq!(
        result,
        Err(QuitRunError::Shutdown(
            "save failed; could not reopen activation after the abandoned quit: marker removal failed"
                .into()
        ))
    );
}

// The acknowledgement the `Failed` state was always named for. `claim()` blocks
// on an *unacknowledged* failure; nothing in the crate ever said what
// acknowledging was, so the first failed shutdown wedged Quit for the rest of
// the process and every later click resurrected the island instead.
#[test]
fn acknowledging_a_failed_shutdown_lets_quit_be_attempted_again() {
    let quit = QuitCoordinator::new();

    assert_eq!(quit.claim(), QuitClaim::BeginShutdown);
    quit.begin_finalizing(|| Ok(()), || Ok(())).unwrap();
    quit.finish(Err("save failed".into()));
    assert_eq!(quit.claim(), QuitClaim::Blocked("save failed".to_string()));

    assert_eq!(
        quit.begin_acknowledgement(),
        Some("save failed".to_string())
    );
    assert!(quit.finish_acknowledgement());

    // A fresh shutdown, not an authorized exit: the next quit re-runs
    // finalization and so re-attempts the save it failed to complete.
    assert_eq!(quit.claim(), QuitClaim::BeginShutdown);
    assert!(!quit.exit_authorized());
}

// While the failure is on screen the app is neither blocked nor free to start a
// second shutdown behind the dialog. A run of tray clicks must coalesce onto
// the one already asking.
#[test]
fn a_failure_being_acknowledged_coalesces_further_quits_instead_of_stacking_them() {
    let quit = QuitCoordinator::new();

    assert_eq!(quit.claim(), QuitClaim::BeginShutdown);
    quit.begin_finalizing(|| Ok(()), || Ok(())).unwrap();
    quit.finish(Err("save failed".into()));

    assert_eq!(
        quit.begin_acknowledgement(),
        Some("save failed".to_string())
    );
    assert_eq!(quit.claim(), QuitClaim::Coalesced);
    assert_eq!(quit.claim(), QuitClaim::Coalesced);
    // A second presenter cannot take a failure the first one is already holding.
    assert_eq!(quit.begin_acknowledgement(), None);
    assert!(!quit.exit_authorized());
}

// Acknowledging is not a way to reach the exit, and it is not a way to reset a
// shutdown that is still running.
#[test]
fn acknowledgement_cannot_authorize_an_exit_or_reset_a_live_shutdown() {
    let authorized = QuitCoordinator::new();
    assert_eq!(authorized.claim(), QuitClaim::BeginShutdown);
    authorized.begin_finalizing(|| Ok(()), || Ok(())).unwrap();
    authorized.finish(Ok(()));
    assert_eq!(authorized.begin_acknowledgement(), None);
    assert!(!authorized.finish_acknowledgement());
    assert_eq!(authorized.claim(), QuitClaim::ExitAuthorized);

    let publishing = QuitCoordinator::new();
    assert_eq!(publishing.claim(), QuitClaim::BeginShutdown);
    assert_eq!(publishing.begin_acknowledgement(), None);
    assert!(!publishing.finish_acknowledgement());
    assert_eq!(publishing.claim(), QuitClaim::Coalesced);

    let finalizing = QuitCoordinator::new();
    assert_eq!(finalizing.claim(), QuitClaim::BeginShutdown);
    finalizing.begin_finalizing(|| Ok(()), || Ok(())).unwrap();
    assert_eq!(finalizing.begin_acknowledgement(), None);
    assert!(!finalizing.finish_acknowledgement());
    assert_eq!(finalizing.claim(), QuitClaim::Coalesced);

    let ready = QuitCoordinator::new();
    assert_eq!(ready.begin_acknowledgement(), None);
    assert!(!ready.finish_acknowledgement());
    assert_eq!(ready.claim(), QuitClaim::BeginShutdown);
}

// A presenter that dies without dismissing must not leave the app parked in a
// state with no exit -- that is the same defect in a new place.
#[test]
fn a_dropped_acknowledgement_returns_the_app_to_ready() {
    let quit = QuitCoordinator::new();
    assert_eq!(quit.claim(), QuitClaim::BeginShutdown);
    quit.begin_finalizing(|| Ok(()), || Ok(())).unwrap();
    quit.finish(Err("save failed".into()));

    assert_eq!(
        quit.begin_acknowledgement(),
        Some("save failed".to_string())
    );
    assert!(quit.finish_acknowledgement());
    // Idempotent: the guard's drop after an explicit dismissal is a no-op.
    assert!(!quit.finish_acknowledgement());
    assert_eq!(quit.claim(), QuitClaim::BeginShutdown);
}
