use super::*;

fn citation() -> CoordinatorCitation {
    CoordinatorCitation {
        concept_id: "reviewed/launch".into(),
        source_revision: "source-revision".into(),
        content_sha256: "a".repeat(64),
        char_start: 0,
        char_end: 8,
        text: "Approved".into(),
    }
}

fn valid_bundle() -> CoordinatorProposalBundle {
    let citations = vec![citation()];
    let item = CoordinatorProposalBundleItem {
        proposal_id: "b".repeat(64),
        proposal_type: "summary".into(),
        proposed_content: "Coordinate the reviewed launch.".into(),
        citation_sha256: citation_sha256(&citations).unwrap(),
        candidate_sha256: "9bf67ef0e058cf8badd3d9ade800cbd910669e38f3197509c9c5f547b56ed555".into(),
        citations,
    };
    let items = vec![item];
    let citation_sha256 = bundle_citation_sha256(&items).unwrap();
    let mut bundle = CoordinatorProposalBundle {
        schema_version: 1,
        generation_sha256: "d".repeat(64),
        evidence_sha256: "e".repeat(64),
        items,
        bundle_sha256: "0".repeat(64),
        citation_sha256,
        canonical: false,
        requires_review: true,
    };
    bundle.bundle_sha256 = bundle_sha256(&bundle).unwrap();
    bundle
}

#[test]
fn request_and_complete_bundle_are_strict_and_bound() {
    let request = CoordinatorRequest::new(
        "Coordinate the reviewed launch.".into(),
        3,
        Some("d".repeat(64)),
    )
    .unwrap();
    let bundle = valid_bundle();
    let view = CoordinatorBundleJobView {
        schema_version: 1,
        request_id: format!("coordinator-bundle-{}", "1".repeat(32)),
        status: CoordinatorBundleStatus::Complete,
        proposal_bundle: Some(bundle),
        reason: None,
    };

    assert!(view.is_valid());
    assert!(view.matches_request(&request));
    let bundle = view.proposal_bundle.as_ref().unwrap();
    assert_eq!(
        bundle.items[0].citation_sha256,
        "b02b27ce43c9226bc43eeaf135671ab9a888c41e1d48c2cc9abbc0e3436b5e1e"
    );
    assert_eq!(
        bundle.citation_sha256,
        "e7fd6e5b194c5554c9e5c663d7010f5783bd62a97363deacb0d6053e013ebf45"
    );
    assert_eq!(
        bundle.bundle_sha256,
        "e06a1fc71e63193edd90fc50e145492278c258725f651ac23da192125c24e93a"
    );
}

#[test]
fn tampered_bundle_hash_and_review_flags_fail_closed() {
    let mut bundle = valid_bundle();
    bundle.bundle_sha256 = "f".repeat(64);
    assert!(!bundle.is_valid());

    let mut bundle = valid_bundle();
    bundle.requires_review = false;
    assert!(!bundle.is_valid());
}

#[test]
fn request_and_identifier_bounds_are_exact() {
    assert!(matches!(
        CoordinatorRequest::new("   ".into(), 1, None),
        Err(CoordinatorClientError::InvalidRequest)
    ));
    assert!(matches!(
        CoordinatorRequest::new("Coordinate this.".into(), 6, None),
        Err(CoordinatorClientError::InvalidRequest)
    ));
    assert!(valid_product_request_id(&format!(
        "coordinator-bundle-{}",
        "a".repeat(32)
    )));
    assert!(!valid_product_request_id(&format!(
        "coordinator-bundle-{}",
        "g".repeat(32)
    )));
}
