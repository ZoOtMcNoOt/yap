use std::cell::RefCell;

use super::super::quit::{run_quit_with, QuitClaim, QuitCoordinator, QuitRunError};

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
