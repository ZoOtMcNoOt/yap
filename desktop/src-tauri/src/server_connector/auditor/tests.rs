use super::*;

fn citation(concept: &str, text: &str) -> AuditorCitation {
    AuditorCitation {
        concept_id: concept.into(),
        source_revision: "source-revision".into(),
        content_sha256: "a".repeat(64),
        char_start: 0,
        char_end: text.chars().count() as u64,
        text: text.into(),
    }
}

fn valid_report() -> AuditorReport {
    let citations = vec![
        citation("limits/helios-five", "Helios limit is five."),
        citation("limits/helios-ten", "Helios limit is ten."),
    ];
    let mut finding = AuditorFinding {
        kind: FINDING_KIND.into(),
        summary: FINDING_SUMMARY.into(),
        citations,
        finding_sha256: "0".repeat(64),
        requires_review: true,
    };
    finding.finding_sha256 = finding_sha256(&finding).unwrap();
    let findings = vec![finding];
    let citation_sha256 = report_citation_sha256(&findings).unwrap();
    let mut report = AuditorReport {
        schema_version: 1,
        generation_sha256: "d".repeat(64),
        source_admission_sha256: "c".repeat(64),
        evidence_sha256: "e".repeat(64),
        findings,
        citation_sha256,
        canonical: false,
        requires_review: true,
        report_sha256: "0".repeat(64),
    };
    report.report_sha256 = report_sha256(&report).unwrap();
    report
}

#[test]
fn request_and_complete_report_are_strict_and_bound() {
    let request =
        AuditorRequest::new("Helios release limit".into(), 3, Some("d".repeat(64))).unwrap();
    let report = valid_report();
    let view = AuditorReportJobView {
        schema_version: 1,
        request_id: format!("auditor-report-{}", "1".repeat(32)),
        status: AuditorReportStatus::Complete,
        report: Some(report),
        reason: None,
    };

    assert!(view.is_valid());
    assert!(view.matches_request(&request));
    let report = view.report.as_ref().unwrap();
    assert!(valid_sha256(&report.findings[0].finding_sha256));
    assert!(valid_sha256(&report.citation_sha256));
    assert!(valid_sha256(&report.report_sha256));
}

#[test]
fn tampered_report_hash_review_flags_and_finding_shape_fail_closed() {
    let mut report = valid_report();
    report.report_sha256 = "f".repeat(64);
    assert!(!report.is_valid());

    let mut report = valid_report();
    report.requires_review = false;
    assert!(!report.is_valid());

    let mut report = valid_report();
    report.findings[0].citations.pop();
    assert!(!report.is_valid());

    let mut report = valid_report();
    report.findings[0].summary = "Model-authored prose".into();
    assert!(!report.is_valid());
}

#[test]
fn request_and_identifier_bounds_are_exact() {
    assert!(matches!(
        AuditorRequest::new("   ".into(), 1, None),
        Err(AuditorClientError::InvalidRequest)
    ));
    assert!(matches!(
        AuditorRequest::new("Review this.".into(), 6, None),
        Err(AuditorClientError::InvalidRequest)
    ));
    assert!(valid_product_request_id(&format!(
        "auditor-report-{}",
        "a".repeat(32)
    )));
    assert!(!valid_product_request_id(&format!(
        "auditor-report-{}",
        "g".repeat(32)
    )));
}
