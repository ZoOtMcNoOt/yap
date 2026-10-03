import type { RecordingJobStatus } from "@/lib/recording-job";

export function recordingActivityLabel(status: RecordingJobStatus) {
  switch (status) {
    case "preflighting":
      return "Checking recording";
    case "preprocessing":
      return "Preparing audio";
    case "local_transcribing":
      return "Transcribing on this device";
    case "uploading":
      return "Uploading";
    case "server_processing":
      return "Processing on server";
    case "diarization_running":
      return "Finding speakers";
    case "saving":
      return "Saving";
    default:
      return "Working";
  }
}

export function recordingActivityDescription(status: RecordingJobStatus) {
  switch (status) {
    case "preflighting":
    case "preprocessing":
      return "Yap is checking and preparing your recording on this device.";
    case "uploading":
      return "Sending the prepared recording to your organization server.";
    case "server_processing":
      return "Your organization server is transcribing this recording. You can cancel it from the queue.";
    case "local_transcribing":
      return "Transcribing on this device. The finished text will appear here.";
    case "diarization_running":
      return "Finding speakers in the recording.";
    case "saving":
      return "Saving the verified transcript. It will appear in History when complete.";
    default:
      return "Your recording is being processed.";
  }
}
