from __future__ import annotations

from datetime import datetime, timezone
import unittest

from yap_server.evaluation.european_parliament_speech_source import (
    parse_european_parliament_speech_index,
    select_post_freeze_speeches,
    validate_source_trim,
)


def _speech_block(
    *,
    item_id: str,
    language: str,
    date: str,
    start: str,
    end: str,
    duration: str,
    include_reference: bool = True,
    placeholder_reference: bool = False,
    marker_language: str | None = None,
) -> str:
    compact_date = date.replace("-", "")
    marker_language = marker_language or language
    if placeholder_reference:
        reference = '<a title="TEXT" href="#"></a>'
    elif include_reference:
        reference = (
            f'<a title="TEXT" href="https://www.europarl.europa.eu/sedcms/'
            f'speech/{compact_date}/{item_id}_01_{language}.docx"></a>'
        )
    else:
        reference = ""
    return f"""
      <div class="notice_debates first last">
        <div><a class="{marker_language} on default"></a></div>
        <div>
          <a title="MPG" href="https://www.europarl.europa.eu/sedcms/
speech/{compact_date}/{item_id}_01_{language}.mpg"></a>
          {reference}
        </div>
        <p>Date</p><time datetime="{date}"></time>
        <p>Length</p><p>{duration}</p>
        <p>Start</p><time datetime="{date}T{start}"></time>
        <p>End</p><time datetime="{date}T{end}"></time>
      </div>
    """


class EuropeanParliamentSpeechSourceTests(unittest.TestCase):
    def test_parser_returns_only_paired_original_language_artifacts(self) -> None:
        html = (
            "<html><body>"
            + _speech_block(
                item_id="2017087003930",
                language="en",
                date="2026-07-08",
                start="13:32:38",
                end="13:33:57",
                duration="00:01:19",
            )
            + _speech_block(
                item_id="2017087003931",
                language="de",
                date="2026-07-08",
                start="13:34:00",
                end="13:35:01",
                duration="00:01:01",
            )
            + _speech_block(
                item_id="2017087003932",
                language="fr",
                date="2026-07-08",
                start="13:36:00",
                end="13:37:00",
                duration="00:01:00",
                placeholder_reference=True,
            )
            + _speech_block(
                item_id="2017087003933",
                language="en",
                marker_language="xm",
                date="2026-07-08",
                start="13:38:00",
                end="13:39:00",
                duration="00:01:00",
            )
            + _speech_block(
                item_id="2017087003934",
                language="sv",
                date="2026-07-08",
                start="13:40:00",
                end="13:40:00",
                duration="00:00:00",
            )
            + "</body></html>"
        )

        items = parse_european_parliament_speech_index(html)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].item_id, "2017087003930")
        self.assertEqual(items[0].language_code, "en")
        self.assertEqual(items[0].duration_seconds, 79)
        self.assertEqual(items[1].language_code, "de")

    def test_parser_rejects_cross_language_or_cross_item_artifact_pair(self) -> None:
        html = _speech_block(
            item_id="2017087003930",
            language="en",
            date="2026-07-08",
            start="13:32:38",
            end="13:33:57",
            duration="00:01:19",
        ).replace("3930_01_en.docx", "3931_01_de.docx")

        with self.assertRaisesRegex(ValueError, "artifacts disagree"):
            parse_european_parliament_speech_index(html)

    def test_parser_rejects_published_duration_that_disagrees_with_times(self) -> None:
        html = _speech_block(
            item_id="2017087003930",
            language="en",
            date="2026-07-08",
            start="13:32:38",
            end="13:33:57",
            duration="00:01:18",
        )

        with self.assertRaisesRegex(ValueError, "duration disagrees"):
            parse_european_parliament_speech_index(html)

    def test_selection_is_strictly_post_freeze_and_deterministic_per_language(
        self,
    ) -> None:
        html = "".join(
            (
                _speech_block(
                    item_id="2017087003930",
                    language="en",
                    date="2026-07-08",
                    start="13:32:38",
                    end="13:33:57",
                    duration="00:01:19",
                ),
                _speech_block(
                    item_id="2017087003931",
                    language="en",
                    date="2026-07-09",
                    start="09:00:00",
                    end="09:01:30",
                    duration="00:01:30",
                ),
                _speech_block(
                    item_id="2017087003932",
                    language="de",
                    date="2026-07-08",
                    start="14:00:00",
                    end="14:01:01",
                    duration="00:01:01",
                ),
            )
        )
        items = parse_european_parliament_speech_index(html)

        selected = select_post_freeze_speeches(
            reversed(items),
            language_codes=("en", "de"),
            frozen_at_utc=datetime(2026, 7, 6, 13, 53, 14, tzinfo=timezone.utc),
            source_utc_offset_minutes=120,
            minimum_duration_seconds=60,
            maximum_duration_seconds=120,
        )

        self.assertEqual(
            [(item.language_code, item.item_id) for item in selected],
            [("en", "2017087003930"), ("de", "2017087003932")],
        )
        with self.assertRaisesRegex(ValueError, "missing languages: fr"):
            select_post_freeze_speeches(
                items,
                language_codes=("fr",),
                frozen_at_utc=datetime(2026, 7, 6, tzinfo=timezone.utc),
                source_utc_offset_minutes=120,
                minimum_duration_seconds=60,
                maximum_duration_seconds=120,
            )

    def test_trim_validation_excludes_the_frozen_adjacent_audio_envelope(self) -> None:
        trim = validate_source_trim(
            published_duration_seconds=79,
            decoded_source_duration_seconds=138.986667,
            leading_padding_seconds=30,
            trailing_padding_seconds=30,
        )

        self.assertEqual(trim.start_seconds, 30.0)
        self.assertEqual(trim.duration_seconds, 79.0)
        self.assertEqual(trim.end_seconds, 109.0)
        with self.assertRaisesRegex(ValueError, "differs from the frozen trim"):
            validate_source_trim(
                published_duration_seconds=79,
                decoded_source_duration_seconds=130,
                leading_padding_seconds=30,
                trailing_padding_seconds=30,
            )


if __name__ == "__main__":
    unittest.main()
