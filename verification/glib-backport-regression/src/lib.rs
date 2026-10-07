#[cfg(test)]
mod tests {
    use glib::prelude::*;

    #[test]
    fn a_allocating_iterator_control() {
        let variant = ["alpha", "βeta", "", "omega"].to_variant();
        let actual: Vec<String> = variant.iter().map(|item| item.get().unwrap()).collect();
        assert_eq!(actual, ["alpha", "βeta", "", "omega"]);
    }

    #[test]
    fn borrowed_string_iterators_preserve_all_directions() {
        let expected = ["alpha", "βeta", "", "omega"];
        let variant = expected.to_variant();
        assert_eq!(
            variant.array_iter_str().unwrap().collect::<Vec<_>>(),
            expected
        );
        assert_eq!(variant.array_iter_str().unwrap().nth(1), Some("βeta"));
        assert_eq!(variant.array_iter_str().unwrap().last(), Some("omega"));
        assert_eq!(
            variant.array_iter_str().unwrap().rev().collect::<Vec<_>>(),
            ["omega", "", "βeta", "alpha"]
        );
        assert_eq!(variant.array_iter_str().unwrap().nth_back(2), Some("βeta"));
        let mut mixed = variant.array_iter_str().unwrap();
        assert_eq!(mixed.next(), Some("alpha"));
        assert_eq!(mixed.next_back(), Some("omega"));
        assert_eq!(mixed.next(), Some("βeta"));
        assert_eq!(mixed.next_back(), Some(""));
        assert_eq!(mixed.next(), None);
        assert_eq!(mixed.next_back(), None);
        assert!(5u32.to_variant().array_iter_str().is_err());
        assert_eq!(
            Vec::<String>::new()
                .to_variant()
                .array_iter_str()
                .unwrap()
                .next(),
            None
        );
    }
}
