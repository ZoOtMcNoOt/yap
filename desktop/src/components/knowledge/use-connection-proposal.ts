import { useCallback, useEffect, useRef, useState } from "react";
import { useConnectionAuthority } from "@/hooks/use-connection-authority";
import {
  cancelKnowledgeConnections,
  knowledgeConnections,
  type ConnectionProposal,
  type ConnectionProposalDisposition,
} from "@/knowledge-connections";
import type { ServerConnectionSnapshot } from "@/server";

export type ProposalHandoff = {
  reference: string;
  authorityRevision: string;
  nonce: number;
};

export function useConnectionProposal(
  snapshot: ServerConnectionSnapshot,
  handoff?: ProposalHandoff,
) {
  const available =
    snapshot.state === "ready" && snapshot.capabilities.knowledgeConnections;
  const [reference, updateReference] = useState("");
  const [view, setView] = useState<ConnectionProposal>();
  const [error, setError] = useState("");
  const [pendingAction, setPendingAction] = useState<
    "proposal" | "discard" | null
  >(null);
  const pending = pendingAction !== null;
  const [disposition, setDisposition] = useState<ConnectionProposalDisposition>();
  const [discardUnconfirmed, setDiscardUnconfirmed] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [queuedHandoff, setQueuedHandoff] = useState<ProposalHandoff>();
  function setReference(value: string) {
    updateReference(value);
    setDisposition(undefined);
    setDiscardUnconfirmed(false);
    setConfirming(false);
    setQueuedHandoff(undefined);
    setError("");
  }
  const epoch = useRef(0);
  const running = useRef<{
    id: string;
    action: "proposal" | "discard";
    cancelSent: boolean;
  } | null>(null);
  const consumed = useRef<ProposalHandoff | undefined>(undefined);
  const deferred = useRef<ProposalHandoff | undefined>(undefined);
  const stop = useCallback(() => {
    const request = running.current;
    if (!request || request.cancelSent) return;
    request.cancelSent = true;
    return cancelKnowledgeConnections(request.id);
  }, []);
  const invalidate = useCallback(
    (changed: boolean) => {
      epoch.current += 1;
      void stop()?.catch(() => undefined);
      setView(undefined);
      setDisposition(undefined);
      setDiscardUnconfirmed(false);
      setConfirming(false);
      setQueuedHandoff(undefined);
      setError("");
      if (changed) updateReference("");
    },
    [stop],
  );
  const owned = useConnectionAuthority(
    available,
    snapshot.authorityRevision,
    invalidate,
  );
  useEffect(
    () => () => {
      epoch.current += 1;
      void stop()?.catch(() => undefined);
    },
    [stop],
  );
  const run = useCallback(
    async (value = reference, action: "proposal" | "discard" = "proposal") => {
      const proposalId = value.trim();
      if (
        !available ||
        !owned ||
        running.current ||
        !/^[0-9a-f]{64}$/.test(proposalId)
      )
        return;
      const id = crypto.randomUUID();
      const started = ++epoch.current;
      running.current = { id, action, cancelSent: false };
      setPendingAction(action);
      setConfirming(false);
      if (action === "proposal") {
        setView(undefined);
        setDisposition(undefined);
        setDiscardUnconfirmed(false);
      }
      setError("");
      try {
        const receipt = await knowledgeConnections(
          id,
          { action, proposalId },
          snapshot.authorityRevision,
        );
        if (started !== epoch.current) return;
        if (action === "discard") {
          if (receipt.response.kind !== "discarded")
            throw { code: "invalidResponse" };
          setDisposition(receipt.response.value);
          setView(undefined);
          setDiscardUnconfirmed(false);
        } else {
          if (receipt.response.kind !== "proposal")
            throw { code: "invalidResponse" };
          setView(receipt.response.value);
        }
      } catch (failure) {
        if (started !== epoch.current) return;
        const code =
          typeof failure === "object" && failure && "code" in failure
            ? failure.code
            : "unavailable";
        if (action === "discard") {
          setDiscardUnconfirmed(code !== "denied" && code !== "notFound");
          if (code === "denied" || code === "identityChanged" || code === "notFound")
            setView(undefined);
          setError(
            code === "notFound"
              ? "This proposal is unavailable for your account. Check its reference."
              : code === "denied"
                ? "Your organization has not granted permission to discard this proposal."
                : code === "identityChanged"
                  ? "Your server or sign-in changed. Discard could not be confirmed. Check your connection."
                  : "Discard could not be confirmed. It may already have completed. Retry the same reference to confirm its status.",
          );
          return;
        }
        setError(
          code === "knowledgeChanged"
            ? "Knowledge changed since this proposal was created. Search current sources and propose the connection again."
            : code === "notFound"
              ? "This connection proposal is unavailable in your current knowledge view. Check its reference or search current sources."
              : code === "identityChanged"
                ? "Your server or sign-in changed. Check the connection before opening this proposal."
                : code === "denied"
                  ? "Your organization has not granted access to this proposal."
                  : code === "invalidResponse"
                    ? "The server returned inconsistent proposal evidence. Check your server and try again."
                    : "The saved proposal could not be read. Check your connection and try again.",
        );
      } finally {
        if (running.current?.id === id) {
          running.current = null;
          setPendingAction(null);
        }
      }
    },
    [available, owned, reference, snapshot.authorityRevision],
  );
  useEffect(() => {
    if (
      !handoff ||
      consumed.current === handoff ||
      handoff.authorityRevision !== snapshot.authorityRevision ||
      !available ||
      !owned
    )
      return;
    if (running.current) {
      if (running.current.action === "discard") {
        consumed.current = handoff;
        setQueuedHandoff(handoff);
        return;
      }
      if (deferred.current !== handoff) {
        deferred.current = handoff;
        epoch.current += 1;
        void stop()?.catch(() => undefined);
        setView(undefined);
        setError("");
        updateReference(handoff.reference);
        setDisposition(undefined);
        setDiscardUnconfirmed(false);
        setConfirming(false);
      }
      return;
    }
    deferred.current = undefined;
    consumed.current = handoff;
    setQueuedHandoff(undefined);
    updateReference(handoff.reference);
    setDisposition(undefined);
    setDiscardUnconfirmed(false);
    setConfirming(false);
    void run(handoff.reference);
  }, [
    available,
    handoff,
    owned,
    pending,
    run,
    snapshot.authorityRevision,
    stop,
  ]);
  async function cancel() {
    if (pendingAction === "discard") return;
    const cancelled = ++epoch.current;
    setError("Proposal inspection cancelled. You can try again.");
    try {
      await stop();
    } catch {
      if (cancelled !== epoch.current) return;
      setError(
        "Cancellation could not be confirmed. Waiting for this read to finish.",
      );
    }
  }
  return {
    available,
    reference: owned ? reference : "",
    setReference,
    view:
      available && owned && view?.proposalId === reference.trim()
        ? view
        : undefined,
    error: owned ? error : "",
    pending,
    discarding: pendingAction === "discard",
    disposition:
      available && owned && disposition?.proposalId === reference.trim()
        ? disposition
        : undefined,
    discardUnconfirmed: owned && discardUnconfirmed,
    confirming: available && owned && confirming,
    setConfirming,
    queuedHandoff: owned ? queuedHandoff : undefined,
    canOpenQueued:
      available && owned && !pending && !discardUnconfirmed &&
      queuedHandoff?.authorityRevision === snapshot.authorityRevision,
    openQueued: () => {
      if (
        !available || !owned || !queuedHandoff || pending || discardUnconfirmed ||
        queuedHandoff.authorityRevision !== snapshot.authorityRevision
      ) return;
      setReference(queuedHandoff.reference);
      void run(queuedHandoff.reference);
    },
    discard: () => run(reference, "discard"),
    canDiscard:
      available && owned && !pending && !disposition &&
      /^[0-9a-f]{64}$/.test(reference.trim()),
    requestId: running.current?.id,
    run,
    cancel,
    canRead:
      available && owned && !pending && !disposition && /^[0-9a-f]{64}$/.test(reference.trim()),
  };
}
