use std::path::{Path, PathBuf};
use symphonia::core::{formats::probe::Hint, io::MediaSourceStream};

pub(super) fn write_damaged_mp3_fixture(destination: &Path) -> Vec<u8> {
    let fixture =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/tone-44k-stereo.mp3");
    let mut bytes = std::fs::read(&fixture).unwrap();
    let stream = MediaSourceStream::new(
        Box::new(std::fs::File::open(fixture).unwrap()),
        Default::default(),
    );
    let mut format = symphonia::default::get_probe()
        .probe(&Hint::new(), stream, Default::default(), Default::default())
        .unwrap();
    // Preserve valid framing/audio around damaged Layer III side information.
    // Skipping decoder errors still produces plausible, shortened audio.
    let mut packet = format.next_packet().unwrap().unwrap();
    for _ in 0..5 {
        packet = format.next_packet().unwrap().unwrap();
    }
    let start = bytes
        .windows(packet.data.len())
        .position(|value| value == packet.data.as_ref())
        .expect("packet belongs to fixture");
    assert_eq!(bytes[start + 1] & 1, 1, "fixture uses no CRC header");
    bytes[start + 4..start + 36].fill(0xff);
    std::fs::write(destination, &bytes).unwrap();
    bytes
}
