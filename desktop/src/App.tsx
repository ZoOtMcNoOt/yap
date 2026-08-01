import { isTauri } from "@tauri-apps/api/core";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { AppChrome } from "@/components/app/app-chrome";
import { AppOverlays } from "@/components/app/app-overlays";
import { AppSidebar } from "@/components/app/app-sidebar";
import { DropHero } from "@/components/panels/drop-hero";
import { HistoryPanel } from "@/components/panels/history-panel";
import { PolishPanel } from "@/components/panels/polish-panel";
import { QueuePanel } from "@/components/panels/queue-panel";
import { TranscriptPanel } from "@/components/panels/transcript-panel";
import { WorkspaceHeader } from "@/components/panels/workspace-header";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { useHistoryActions } from "@/hooks/use-history-actions";
import { useRecordingJobs } from "@/hooks/use-imported-recording-queue";
import { useHistoryCatalogSync } from "@/hooks/use-history-catalog-sync";
import { useRecordingSelection } from "@/hooks/use-recording-selection";
import { useRecordingDrop } from "@/hooks/use-recording-drop";
import { useSettingsControl } from "@/hooks/use-settings-control";
import { useTranscriptFileActions } from "@/hooks/use-transcript-file-actions";
import { useTranscriptPreview } from "@/hooks/use-transcript-preview";
import { useTranscriptText } from "@/hooks/use-transcript-text";
import { useTranscriptHistory } from "@/hooks/use-transcript-history";
import { useWorkspaceNavigation } from "@/hooks/use-workspace-navigation";
import { type TranscriptHistoryEntry } from "@/history-model";
import { isRecordingFinished } from "@/lib/recording-job";
import { workspaceCopy } from "@/lib/workspace";
import { fireAndReport } from "@/lib/fire-and-report";
import { cn } from "@/lib/utils";
import {
  fixedBatchLanguageOptions,
  recordingImportLanguageOptions,
} from "@/language-preference";

function reportRecordingAction(action: () => unknown, message: string) {
  fireAndReport(action, (error) => toast.error(`${message}: ${error.message}`));
}

export default function App() {
  const [status, setStatus] = useState("Starting");
  const [recordingLanguageOptionId, setRecordingLanguageOptionId] = useState<string | null>(null);
  const settingsRefreshRef = useRef<() => Promise<void>>(async () => undefined);
  const {
    clearTranscriptText,
    forgetTranscriptText,
    loadTranscriptPreviewText,
    loadTranscriptText,
    polishedText,
    rememberPolishedText,
    transcriptText,
  } = useTranscriptText();
  const {
    addRecordings: pickImportedRecordings,
    clearQueue,
    confirmLanguage,
    discardLegacyQueue,
    legacyDiscardAllowed,
    migrationError,
    migrationState,
    queue,
    removeItem,
    retryItem,
    retryMigration,
  } = useRecordingJobs(clearTranscriptText);
  const {
    copyTranscript,
    openAppPath,
    revealPath,
    savePolishedTranscript,
  } = useTranscriptFileActions(loadTranscriptText);
  const {
    captureNativeHistoryReconciliation,
    forgetHistoryEntry,
    history,
    reconcileHiddenHistory,
    recordVisibleHistoryEntries,
    rememberHiddenHistoryEntry,
  } = useTranscriptHistory();
  const {
    clearHistorySelectionIf,
    closeHistoryReview,
    historyJob,
    reviewMorphOrigin,
    selectHistoryEntry,
    selectQueueItem,
    selectedHistoryItem,
    selectedHistoryEntry,
    selectedHistoryOutput,
    selectedId,
    selectedItem,
  } = useRecordingSelection({ history, queue });
  const {
    activeRail,
    closeDetails,
    detailsOpen,
    helpOpen,
    onDetailsOpenChange,
    onHelpOpenChange,
    openWorkspace,
    railCollapsed,
    setRailCollapsed,
    showDetails,
    workspaceView,
  } = useWorkspaceNavigation({
    onOpenDetails: () => void settingsRefreshRef.current(),
    onOpenPolish: () => {
      setStatus(isRecordingFinished(selectedItem?.status) ? "Transcript ready" : "Select a finished transcript first");
    },
  });
  const recordingDrop = useRecordingDrop();
  const onNativeTranscriptSaved = useCallback((entry: TranscriptHistoryEntry) => {
    selectHistoryEntry(entry);
    openWorkspace("home");
    setStatus("Ready");
    void loadTranscriptText(entry.outputPath).catch(() => undefined);
    if (entry.warning) {
      toast.warning(entry.warning);
    } else {
      toast.success(entry.origin === "remote" ? "Server transcript saved" : "Live transcript saved");
    }
  }, [loadTranscriptText, openWorkspace, selectHistoryEntry]);
  useHistoryCatalogSync({
    captureNativeHistoryReconciliation,
    onSaved: onNativeTranscriptSaved,
    reconcileHiddenHistory,
  });
  const historyActions = useHistoryActions({
    clearHistorySelectionIf,
    forgetHistoryEntry,
    forgetTranscriptText,
    recordVisibleHistoryEntries,
    rememberHiddenHistoryEntry,
    selectHistoryEntry,
  });
  const settings = useSettingsControl({
    onStatusChange: setStatus,
  });
  const languageCatalog = settings.language.status?.capabilityCatalog;
  const languageOptions = useMemo(
    () => fixedBatchLanguageOptions(languageCatalog),
    [languageCatalog],
  );
  const importLanguageOptions = useMemo(
    () => recordingImportLanguageOptions(languageCatalog),
    [languageCatalog],
  );
  const primaryLanguageBcp47 = settings.language.status?.confirmedLanguageBcp47 ?? null;
  useEffect(() => {
    setRecordingLanguageOptionId((current) => {
      if (current && importLanguageOptions.some((option) => option.id === current)) {
        return current;
      }
      const primaryId = primaryLanguageBcp47 ? `fixed:${primaryLanguageBcp47}` : null;
      return importLanguageOptions.some((option) => option.id === primaryId)
        ? primaryId
        : null;
    });
  }, [importLanguageOptions, primaryLanguageBcp47]);
  const addRecordings = useCallback(async () => {
    const catalogRevision = languageCatalog?.catalogRevision;
    const option = importLanguageOptions.find(({ id }) => id === recordingLanguageOptionId);
    if (!option || !catalogRevision) {
      throw new Error("Confirm a currently supported recording language in Settings first.");
    }
    const selectedQueueId = await pickImportedRecordings(option.mode === "dynamic"
      ? { mode: "dynamic", catalogRevision }
      : { mode: "fixed", languageBcp47: option.languageBcp47, catalogRevision });
    if (selectedQueueId === undefined) return;
    openWorkspace("transcribe");
    selectQueueItem(selectedQueueId);
  }, [
    languageCatalog?.catalogRevision,
    openWorkspace,
    pickImportedRecordings,
    importLanguageOptions,
    recordingLanguageOptionId,
    selectQueueItem,
  ]);
  const confirmQueuedLanguage = useCallback(async (jobId: string, languageBcp47: string) => {
    const catalogRevision = languageCatalog?.catalogRevision;
    if (!catalogRevision) {
      throw new Error("Current server language capabilities are unavailable.");
    }
    await confirmLanguage(jobId, languageBcp47, catalogRevision);
  }, [confirmLanguage, languageCatalog?.catalogRevision]);
  settingsRefreshRef.current = settings.refresh;
  const workspace = workspaceCopy[workspaceView];
  const showQueue = workspaceView === "transcribe";
  const showHistory = workspaceView === "home";
  const showTranscript = workspaceView === "transcribe" || workspaceView === "polish";
  const showPolish = workspaceView === "polish";

  useEffect(() => {
    if (settings.setupPromptRequest) showDetails();
  }, [settings.setupPromptRequest, showDetails]);

  useEffect(() => {
    if (!isTauri()) return;
    if (migrationError) setStatus(migrationError);
    else if (migrationState === "pending") setStatus("Restoring queued recordings");
  }, [migrationError, migrationState]);

  useEffect(() => {
    if (selectedItem?.outputPath && !Object.prototype.hasOwnProperty.call(transcriptText, selectedItem.outputPath)) {
      void loadTranscriptText(selectedItem.outputPath).catch(() => toast.error("Preview unavailable"));
    }
  }, [loadTranscriptText, selectedItem?.outputPath, transcriptText]);

  function goToTranscribe() {
    openWorkspace("transcribe");
  }

  async function pickFiles() {
    goToTranscribe();

    if (!isTauri()) {
      toast.info("Preview only");
      return;
    }

    try {
      await addRecordings();
    } catch (error) {
      toast.error(`Picker failed: ${String(error)}`);
    }
  }

  const loadHistoryPreviewText = useCallback(
    (entry: TranscriptHistoryEntry) => loadTranscriptPreviewText(entry.outputPath),
    [loadTranscriptPreviewText],
  );
  const {
    closeTranscriptPreview,
    previewEntry,
    previewHistoryEntry,
    previewText,
  } = useTranscriptPreview(loadHistoryPreviewText);

  function openHistoryEntry(entry: TranscriptHistoryEntry, origin?: DOMRect) {
    selectHistoryEntry(entry, origin);
    openWorkspace("home");
  }

  const workspaceLeftPane = (
    <>
      {showQueue ? (
        <QueuePanel
          legacyDiscardAllowed={legacyDiscardAllowed}
          onClear={() => reportRecordingAction(clearQueue, "Could not clear queue")}
          onDiscardLegacyQueue={() => reportRecordingAction(discardLegacyQueue, "Could not discard old queue")}
          onConfirmLanguage={confirmQueuedLanguage}
          onRemove={(id) => reportRecordingAction(() => removeItem(id), "Could not remove recording")}
          onReveal={(path) => void revealPath(path)}
          onRetryMigration={retryMigration}
          onSelect={selectQueueItem}
          queue={queue}
          languageOptions={languageOptions}
          migrationError={migrationError}
          migrationPending={migrationState === "pending"}
          selectedId={selectedId}
        />
      ) : null}

      {showHistory ? (
        <HistoryPanel
          entries={history}
          onCopy={(entry) => void copyTranscript(historyJob(entry))}
          onDelete={(entry) => void historyActions.deleteHistoryEntry(entry)}
          onDeleteRecoverable={(entry) => void historyActions.deleteRecoverableHistoryEntry(entry)}
          onHide={historyActions.hideHistoryEntry}
          onLoadPreviewText={loadHistoryPreviewText}
          onOpen={(entry) => void openAppPath(entry.outputPath)}
          onOpenHelp={() => openWorkspace("help")}
          onPreview={(entry) => void previewHistoryEntry(entry)}
          onReveal={(entry) => void revealPath(entry.outputPath)}
          onRecover={(entry) => void historyActions.recoverHistoryEntry(entry)}
          onSelect={openHistoryEntry}
          selectedOutputPath={selectedHistoryOutput}
        />
      ) : null}

      {showPolish ? (
        <PolishPanel
          item={selectedItem}
          onOpenHelp={() => openWorkspace("help")}
          onPolished={(outputPath, text) => {
            rememberPolishedText(outputPath, text);
            toast.success("Polished draft ready");
          }}
          onSave={savePolishedTranscript}
          originalText={selectedItem?.outputPath ? transcriptText[selectedItem.outputPath] : undefined}
          polishedText={selectedItem?.outputPath ? polishedText[selectedItem.outputPath] : undefined}
        />
      ) : null}
    </>
  );
  const workspaceTranscriptPane = showTranscript ? (
    <div className="h-full min-w-0">
      <TranscriptPanel
        elapsedSeconds={0}
        item={selectedItem}
        onCopy={copyTranscript}
        onOpen={(path) => void openAppPath(path)}
        onOpenHelp={() => openWorkspace("help")}
        onRetry={(id) => reportRecordingAction(() => retryItem(id), "Could not retry recording")}
        onReveal={(path) => void revealPath(path)}
        running={false}
        text={selectedItem?.outputPath ? transcriptText[selectedItem.outputPath] : undefined}
      />
    </div>
  ) : null;
  const workspaceMain = (
    <div
      className={cn(
        "grid w-full min-w-0 gap-5",
        showTranscript
          ? "grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(380px,0.78fr)]"
          : "grid-cols-1",
      )}
    >
      {workspaceLeftPane}
      {workspaceTranscriptPane}
    </div>
  );
  const appWorkspace = (
    <section className="surface-workspace scrollbar-none h-full min-h-0 w-full min-w-0 flex-1 overflow-x-hidden overflow-y-auto bg-card p-4">
      <WorkspaceHeader
        auth={settings.auth}
        description={workspace.description}
        historyCount={history.length}
        onOpenDetails={() => openWorkspace("details")}
        onOpenHelp={() => openWorkspace("help")}
        serverState={settings.serverState}
        status={status}
        title={workspace.title}
      />

      {workspaceView === "transcribe" ? (
        <DropHero
          dragging={recordingDrop.dragging}
          onDragLeave={recordingDrop.onDragLeave}
          onDragOver={recordingDrop.onDragOver}
          onDrop={recordingDrop.onDrop}
          languageOptions={importLanguageOptions}
          onLanguageChange={setRecordingLanguageOptionId}
          onOpenHelp={() => openWorkspace("help")}
          onOpenLanguageSettings={showDetails}
          onPickFiles={() => void pickFiles()}
          selectedLanguageOptionId={recordingLanguageOptionId}
        />
      ) : null}

      <section className="mt-7 w-full min-w-0">
        {workspaceMain}
      </section>
    </section>
  );

  return (
    <SidebarProvider
      className="h-screen overflow-hidden bg-background text-foreground"
      onOpenChange={(open) => setRailCollapsed(!open)}
      open={!railCollapsed}
    >
      <AppSidebar active={activeRail} onAction={openWorkspace} />
      <SidebarInset className="flex min-h-0 flex-col overflow-hidden">
        <AppChrome />
        <div className="min-h-0 w-full min-w-0 flex-1 overflow-hidden bg-background pb-4 pr-4 pt-0">
          {appWorkspace}
        </div>
      </SidebarInset>
      <AppOverlays
        closeDetails={closeDetails}
        closeHistoryReview={closeHistoryReview}
        closeTranscriptPreview={closeTranscriptPreview}
        copyTranscript={copyTranscript}
        detailsOpen={detailsOpen}
        helpOpen={helpOpen}
        historyJob={historyJob}
        historyReviewOpen={workspaceView === "home" && Boolean(selectedHistoryItem)}
        languageOptions={languageOptions}
        onDetailsOpenChange={onDetailsOpenChange}
        onHelpOpenChange={onHelpOpenChange}
        openAppPath={openAppPath}
        openWorkspace={openWorkspace}
        previewEntry={previewEntry}
        previewText={previewText}
        revealPath={revealPath}
        reviewMorphOrigin={reviewMorphOrigin}
        selectedHistoryItem={selectedHistoryItem}
        selectedHistoryEntry={selectedHistoryEntry}
        settings={settings}
        status={status}
        transcriptText={transcriptText}
      />
    </SidebarProvider>
  );
}
