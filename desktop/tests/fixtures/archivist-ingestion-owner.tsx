import { useArchivistIngestion } from "@/components/archivist/use-archivist-ingestion";
import { TranscriptPanel } from "@/components/panels/transcript-panel";
import type { RecordingJobView } from "@/lib/recording-job";
import { createRoot } from "react-dom/client";

import "../../src/styles.css";

const item: RecordingJobView = {
  id: "recording-local-1",
  name: "Reviewed meeting",
  outputPath: "C:/Yap/remote-jobs/job-1/result-1/transcript.txt",
  pipeline: {
    alignment: "done",
    diarization: "done",
    intake: "done",
    postprocessing: "done",
    preprocessing: "done",
    transcription: "done",
  },
  route: "serverBatch",
  sessionMode: "meeting",
  sessionOrigin: "importedFile",
  status: "complete",
};

function ArchivistIngestionOwnerFixture() {
  const archivist = useArchivistIngestion({
    available: true,
    recordingId: item.id,
  });
  return (
    <TranscriptPanel
      elapsedSeconds={0}
      item={item}
      knowledgeStaging={{
        active: archivist.active,
        canStage: archivist.canStage,
        error: archivist.error,
        onStage: () => void archivist.stage(),
        staged: archivist.view?.status === "staged",
        statusLine: archivist.statusLine,
      }}
      onCopy={() => undefined}
      onOpen={() => undefined}
      onRetry={() => undefined}
      onReveal={() => undefined}
      running={false}
      text="The reviewed launch decision was approved."
    />
  );
}

createRoot(document.getElementById("root")!).render(<ArchivistIngestionOwnerFixture />);
