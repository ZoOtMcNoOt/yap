export const acceptedFormats =
  "WAV, MP3, FLAC, Ogg Vorbis and M4A/MP4 (AAC-LC)";

export const audioExtensions = [
  "mp3",
  "m4a",
  "wav",
  "mp4",
  "flac",
  "ogg",
  "webm",
];
export const audioExts = new Set(audioExtensions.map((format) => `.${format}`));

export function basename(path: string) {
  return path.split(/[\\/]/).pop() ?? path;
}

export function extension(path: string) {
  const name = basename(path);
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}
