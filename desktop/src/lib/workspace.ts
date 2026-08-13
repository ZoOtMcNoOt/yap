const workspaceViews = ["home", "transcribe", "correct", "knowledge"] as const;

export type WorkspaceView = (typeof workspaceViews)[number];

export type RailAction = WorkspaceView | "details" | "help";

export const workspaceCopy: Record<WorkspaceView, { title: string; description: string }> = {
  home: {
    title: "Welcome back",
    description: "",
  },
  transcribe: {
    title: "Transcribe",
    description: "Add recordings to your organization's transcription queue.",
  },
  correct: {
    title: "Transcript correction",
    description: "Review source-bound corrections without changing raw ASR.",
  },
  knowledge: {
    title: "Knowledge",
    description: "Find permission-safe evidence in reviewed organization knowledge.",
  },
};

export function isWorkspaceView(value: unknown): value is WorkspaceView {
  return typeof value === "string" && (workspaceViews as readonly string[]).includes(value);
}
