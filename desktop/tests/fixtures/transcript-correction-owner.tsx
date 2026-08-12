import { useState } from "react";
import { createRoot } from "react-dom/client";

import { TranscriptCorrectionPanel } from "@/components/panels/transcript-correction-panel";
import { createInitialPipelineState, type RecordingJobView } from "@/lib/recording-job";

function item(id: string): RecordingJobView {
  return {
    id,
    name: `${id}.wav`,
    outputPath: `C:/${id}.txt`,
    sourcePath: `C:/${id}.wav`,
    pipeline: createInitialPipelineState(),
    route: "serverBatch",
    sessionMode: "meeting",
    sessionOrigin: "importedFile",
    status: "complete",
  };
}

function TranscriptCorrectionOwnerFixture() {
  const [selected, setSelected] = useState("meeting-one");
  return (
    <>
      <button onClick={() => setSelected("meeting-two")} type="button">
        Switch transcript
      </button>
      <TranscriptCorrectionPanel
        available
        item={item(selected)}
        originalText={selected === "meeting-one" ? "Dose is twenty five mg." : "Second source."}
      />
    </>
  );
}

createRoot(document.getElementById("root")!).render(<TranscriptCorrectionOwnerFixture />);
