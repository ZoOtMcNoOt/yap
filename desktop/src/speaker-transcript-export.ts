import { invoke } from "@tauri-apps/api/core";

export type SpeakerTranscriptExportIdentity = {
  outputPath: string;
  sessionId: string;
  sourceResultSha256: string;
};

export async function exportSpeakerTranscript(
  identity: SpeakerTranscriptExportIdentity,
) {
  const result = await invoke<
    | { status: "cancelled" }
    | {
        status: "saved";
        path: string;
        sessionId: string;
        sourceResultSha256: string;
      }
  >("export_speaker_transcript", identity);
  if (
    !result ||
    (result.status !== "cancelled" &&
      (result.status !== "saved" ||
        typeof result.path !== "string" ||
        !result.path.trim() ||
        result.sessionId !== identity.sessionId ||
        result.sourceResultSha256 !== identity.sourceResultSha256))
  ) {
    throw new Error(
      "The export receipt did not match the timed speaker transcript. Check the selected destination before trying again; the file may already have been saved.",
    );
  }
  return result;
}
