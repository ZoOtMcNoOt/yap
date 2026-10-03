//! Bounded presentation timing for a single AAC track. Symphonia owns demuxing
//! and decoding; its ISO-MP4 reader currently does not apply edit lists.
use std::{
    collections::BTreeMap,
    fs::File,
    io::{Read, Seek, SeekFrom},
};

const MAX_MOVIE_BYTES: u64 = 16 * 1024 * 1024;
const MAX_BOXES: usize = 4096;
const MAX_TRACKS: usize = 64;

#[derive(Clone, Copy)]
struct Edit {
    duration: u64,
    start: u64,
}
struct TrackTiming {
    duration: u64,
    edit: Option<Edit>,
}
pub(super) struct MovieTiming {
    timescale: u32,
    tracks: BTreeMap<u32, TrackTiming>,
}
#[derive(Clone, Copy)]
pub(super) struct ContentRange {
    pub start: u64,
    pub end: u64,
}
fn invalid() -> String {
    "M4A/MP4 recording has unsupported or inconsistent timing metadata".into()
}

impl MovieTiming {
    pub(super) fn read(
        source: &mut File,
        active: &mut impl FnMut() -> Result<(), String>,
    ) -> Result<Self, String> {
        let length = source.metadata().map_err(|_| invalid())?.len();
        let mut offset = 0u64;
        let mut movie = None;
        let mut count = 0usize;
        while offset < length {
            active()?;
            count += 1;
            if count > MAX_BOXES || length - offset < 8 {
                return Err(invalid());
            }
            source
                .seek(SeekFrom::Start(offset))
                .map_err(|_| invalid())?;
            let mut header = [0u8; 16];
            source.read_exact(&mut header[..8]).map_err(|_| invalid())?;
            let short = u32::from_be_bytes(header[..4].try_into().unwrap());
            let (size, header_size) = match short {
                0 => (length - offset, 8),
                1 => {
                    source.read_exact(&mut header[8..]).map_err(|_| invalid())?;
                    (u64::from_be_bytes(header[8..].try_into().unwrap()), 16)
                }
                size => (u64::from(size), 8),
            };
            if size < header_size || size > length - offset {
                return Err(invalid());
            }
            match &header[4..8] {
                b"moof" => {
                    return Err(
                        "Fragmented MP4 recordings are not supported; select a complete recording"
                            .into(),
                    )
                }
                b"moov" => {
                    if movie.is_some() || size - header_size > MAX_MOVIE_BYTES {
                        return Err(invalid());
                    }
                    let mut bytes = vec![0u8; (size - header_size) as usize];
                    source.read_exact(&mut bytes).map_err(|_| invalid())?;
                    movie = Some(Self::parse(&bytes, &mut count, active)?);
                }
                _ => {}
            }
            offset = offset.checked_add(size).ok_or_else(invalid)?;
        }
        source.seek(SeekFrom::Start(0)).map_err(|_| invalid())?;
        movie.ok_or_else(invalid)
    }
    fn parse(
        bytes: &[u8],
        count: &mut usize,
        active: &mut impl FnMut() -> Result<(), String>,
    ) -> Result<Self, String> {
        let mut timescale = None;
        let mut tracks = BTreeMap::new();
        for (kind, body) in boxes(bytes, count)? {
            active()?;
            match kind {
                b"mvex" | b"cmov" => return Err(invalid()),
                b"mvhd" => {
                    if timescale.is_some() {
                        return Err(invalid());
                    }
                    let at = version_offset(body, 12, 20)?;
                    let scale = u32_at(body, at)?;
                    if scale == 0 {
                        return Err(invalid());
                    }
                    timescale = Some(scale);
                }
                b"trak" => {
                    if tracks.len() >= MAX_TRACKS {
                        return Err(invalid());
                    }
                    let mut id = None;
                    let mut duration = None;
                    let mut edit = None;
                    let mut seen_edits = false;
                    for (kind, body) in boxes(body, count)? {
                        match kind {
                            b"tkhd" => {
                                if id.is_some() {
                                    return Err(invalid());
                                }
                                let at = version_offset(body, 12, 20)?;
                                id = Some(u32_at(body, at)?);
                                duration = Some(if body[0] == 0 {
                                    u64::from(u32_at(body, 20)?)
                                } else {
                                    u64_at(body, 28)?
                                });
                            }
                            b"edts" => {
                                if seen_edits {
                                    return Err(invalid());
                                }
                                seen_edits = true;
                                let entries = boxes(body, count)?;
                                if entries.len() != 1 || entries[0].0 != b"elst" {
                                    return Err(invalid());
                                }
                                edit = Some(parse_edit(entries[0].1)?);
                            }
                            _ => {}
                        }
                    }
                    let id = id.filter(|id| *id != 0).ok_or_else(invalid)?;
                    if tracks
                        .insert(
                            id,
                            TrackTiming {
                                duration: duration.ok_or_else(invalid)?,
                                edit,
                            },
                        )
                        .is_some()
                    {
                        return Err(invalid());
                    }
                }
                _ => {}
            }
        }
        Ok(Self {
            timescale: timescale.ok_or_else(invalid)?,
            tracks,
        })
    }
    pub(super) fn content(
        &self,
        track: u32,
        rate: u32,
        media_frames: u64,
    ) -> Result<ContentRange, String> {
        let track = self.tracks.get(&track).ok_or_else(invalid)?;
        let Some(edit) = track.edit else {
            return Ok(ContentRange {
                start: 0,
                end: media_frames,
            });
        };
        // Encoders can round the track header up and its edit list down.
        if track.duration.abs_diff(edit.duration) > u64::from(self.timescale) / 1000 {
            return Err(invalid());
        }
        // Keep each sample whose beginning is inside the presentation segment.
        // Movie-time rounding can exceed available audio by one tick, capped at
        // one millisecond; never invent silence or discard the final sample.
        let frames = edit
            .duration
            .checked_mul(u64::from(rate))
            .ok_or_else(invalid)?
            .div_ceil(u64::from(self.timescale));
        let end = edit.start.checked_add(frames).ok_or_else(invalid)?;
        let tick = u64::from(rate)
            .div_ceil(u64::from(self.timescale))
            .min(u64::from(rate).div_ceil(1000));
        if frames == 0 || edit.start >= media_frames || end.saturating_sub(media_frames) > tick {
            return Err(invalid());
        }
        let end = end.min(media_frames);
        if edit.start >= end {
            return Err(invalid());
        }
        Ok(ContentRange {
            start: edit.start,
            end,
        })
    }
}

type Atom<'a> = (&'a [u8], &'a [u8]);

fn boxes<'a>(bytes: &'a [u8], count: &mut usize) -> Result<Vec<Atom<'a>>, String> {
    let mut offset = 0usize;
    let mut result = Vec::new();
    while offset < bytes.len() {
        *count += 1;
        if *count > MAX_BOXES || bytes.len() - offset < 8 {
            return Err(invalid());
        }
        let short = u32_at(bytes, offset)?;
        let (size, header) = match short {
            0 => (bytes.len() - offset, 8),
            1 => (
                usize::try_from(u64_at(bytes, offset + 8)?).map_err(|_| invalid())?,
                16,
            ),
            size => (size as usize, 8),
        };
        if size < header || size > bytes.len() - offset {
            return Err(invalid());
        }
        result.push((
            &bytes[offset + 4..offset + 8],
            &bytes[offset + header..offset + size],
        ));
        offset += size;
    }
    Ok(result)
}
fn version_offset(bytes: &[u8], version0: usize, version1: usize) -> Result<usize, String> {
    match bytes.first() {
        Some(0) => Ok(version0),
        Some(1) => Ok(version1),
        _ => Err(invalid()),
    }
}
fn u32_at(bytes: &[u8], offset: usize) -> Result<u32, String> {
    Ok(u32::from_be_bytes(
        bytes
            .get(offset..offset + 4)
            .ok_or_else(invalid)?
            .try_into()
            .unwrap(),
    ))
}
fn u64_at(bytes: &[u8], offset: usize) -> Result<u64, String> {
    Ok(u64::from_be_bytes(
        bytes
            .get(offset..offset + 8)
            .ok_or_else(invalid)?
            .try_into()
            .unwrap(),
    ))
}
fn parse_edit(bytes: &[u8]) -> Result<Edit, String> {
    if bytes.get(1..4) != Some(&[0, 0, 0]) || u32_at(bytes, 4)? != 1 {
        return Err(invalid());
    }
    let (duration, start, rate_at) = match bytes.first() {
        Some(0) if bytes.len() == 20 => (
            u64::from(u32_at(bytes, 8)?),
            i64::from(u32_at(bytes, 12)? as i32),
            16,
        ),
        Some(1) if bytes.len() == 28 => (u64_at(bytes, 8)?, u64_at(bytes, 16)? as i64, 24),
        _ => return Err(invalid()),
    };
    if duration == 0 || start < 0 || u32_at(bytes, rate_at)? != 0x00010000 {
        return Err(invalid());
    }
    Ok(Edit {
        duration,
        start: start as u64,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    fn atom(kind: &[u8; 4], body: &[u8]) -> Vec<u8> {
        let mut bytes = ((body.len() + 8) as u32).to_be_bytes().to_vec();
        bytes.extend(kind);
        bytes.extend(body);
        bytes
    }
    fn movie(version: u8) -> Vec<u8> {
        let mut header = vec![0; 20];
        header[12..16].copy_from_slice(&1000u32.to_be_bytes());
        let mut track = vec![0; if version == 0 { 24 } else { 36 }];
        track[0] = version;
        let id_at = if version == 0 { 12 } else { 20 };
        track[id_at..id_at + 4].copy_from_slice(&7u32.to_be_bytes());
        let duration_at = if version == 0 { 20 } else { 28 };
        if version == 0 {
            track[duration_at..].copy_from_slice(&1000u32.to_be_bytes())
        } else {
            track[duration_at..].copy_from_slice(&1000u64.to_be_bytes())
        }
        let mut edit = vec![0; if version == 0 { 20 } else { 28 }];
        edit[0] = version;
        edit[4..8].copy_from_slice(&1u32.to_be_bytes());
        if version == 0 {
            edit[8..12].copy_from_slice(&1000u32.to_be_bytes());
            edit[12..16].copy_from_slice(&1024i32.to_be_bytes());
        } else {
            edit[8..16].copy_from_slice(&1000u64.to_be_bytes());
            edit[16..24].copy_from_slice(&1024i64.to_be_bytes());
        }
        let size = edit.len();
        edit[size - 4..].copy_from_slice(&0x0001_0000u32.to_be_bytes());
        let mut parts = atom(b"tkhd", &track);
        parts.extend(atom(b"edts", &atom(b"elst", &edit)));
        let mut bytes = atom(b"mvhd", &header);
        bytes.extend(atom(b"trak", &parts));
        bytes
    }
    #[test]
    fn mpeg4_versioned_timing_requires_exact_track_binding() {
        for version in [0, 1] {
            let timing = MovieTiming::parse(&movie(version), &mut 0, &mut || Ok(())).unwrap();
            let range = timing.content(7, 44_100, 45_124).unwrap();
            assert_eq!((range.start, range.end), (1024, 45_124));
            assert!(timing.content(8, 44_100, 45_124).is_err());
        }
    }
    #[test]
    fn mpeg4_malformed_duplicate_and_excessive_boxes_are_refused() {
        let valid = movie(0);
        for keep in [0, 7, 19, valid.len() - 1] {
            assert!(MovieTiming::parse(&valid[..keep], &mut 0, &mut || Ok(())).is_err());
        }
        let mut duplicate = valid.clone();
        duplicate.extend(&valid);
        assert!(MovieTiming::parse(&duplicate, &mut 0, &mut || Ok(())).is_err());
        let mut too_many = valid.clone();
        for _ in 0..MAX_BOXES {
            too_many.extend(atom(b"free", &[]));
        }
        assert!(MovieTiming::parse(&too_many, &mut 0, &mut || Ok(())).is_err());
        let mut extended = vec![0, 0, 0, 1];
        extended.extend(b"free");
        extended.extend(u64::MAX.to_be_bytes());
        assert!(MovieTiming::parse(&extended, &mut 0, &mut || Ok(())).is_err());
    }
    #[test]
    fn mpeg4_metadata_ceiling_refuses_before_allocating_movie_body() {
        let root = std::env::temp_dir().join(format!("yap-movie-ceiling-{}", std::process::id()));
        let mut file = std::fs::OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&root)
            .unwrap();
        use std::io::Write;
        let length = MAX_MOVIE_BYTES + 9;
        file.write_all(&(length as u32).to_be_bytes()).unwrap();
        file.write_all(b"moov").unwrap();
        file.set_len(length).unwrap();
        assert!(MovieTiming::read(&mut file, &mut || Ok(())).is_err());
        assert_eq!(file.metadata().unwrap().len(), length);
        drop(file);
        std::fs::remove_file(root).unwrap();
    }
    #[test]
    fn mpeg4_presentation_rounding_never_invents_coarse_silence() {
        let timing = MovieTiming {
            timescale: 1000,
            tracks: BTreeMap::from([(
                7,
                TrackTiming {
                    duration: 998,
                    edit: Some(Edit {
                        duration: 997,
                        start: 1024,
                    }),
                },
            )]),
        };
        let range = timing.content(7, 44_100, 44_992).unwrap();
        assert_eq!((range.start, range.end), (1024, 44_992));
        let coarse = MovieTiming {
            timescale: 1,
            tracks: BTreeMap::from([(
                7,
                TrackTiming {
                    duration: 1,
                    edit: Some(Edit {
                        duration: 1,
                        start: 1024,
                    }),
                },
            )]),
        };
        assert!(coarse.content(7, 44_100, 12_049).is_err());
    }
}
