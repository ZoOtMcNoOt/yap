use super::super::language::SUPPORTED_LIVE_LOCALES;
use super::super::supports_live_language;

#[test]
fn pinned_live_catalog_contains_exactly_the_out_of_box_locales() {
    assert_eq!(SUPPORTED_LIVE_LOCALES.len(), 32);
    assert_eq!(
        SUPPORTED_LIVE_LOCALES
            .iter()
            .copied()
            .collect::<std::collections::HashSet<_>>()
            .len(),
        SUPPORTED_LIVE_LOCALES.len()
    );
    assert!(SUPPORTED_LIVE_LOCALES
        .iter()
        .all(|locale| crate::language::valid_bcp47(locale)));
    assert!(supports_live_language("en-US"));
    assert!(supports_live_language("et-EE"));
}

#[test]
fn adaptation_ready_and_unrelated_locales_are_not_live_capabilities() {
    for locale in [
        "el-GR", "lt-LT", "lv-LV", "mt-MT", "sl-SI", "he-IL", "th-TH", "nn-NO", "es-MX",
    ] {
        assert!(
            !supports_live_language(locale),
            "unexpected support: {locale}"
        );
    }
}
