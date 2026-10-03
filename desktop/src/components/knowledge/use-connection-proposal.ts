import { useCallback, useEffect, useRef, useState } from "react";
import { useConnectionAuthority } from "@/hooks/use-connection-authority";
import {
  cancelKnowledgeConnections,
  knowledgeConnections,
  type ConnectionProposal,
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
  const [reference, setReference] = useState("");
  const [view, setView] = useState<ConnectionProposal>();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const epoch = useRef(0);
  const running = useRef<{ id: string; cancelSent: boolean } | null>(null);
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
      setError("");
      if (changed) setReference("");
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
    async (value = reference) => {
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
      running.current = { id, cancelSent: false };
      setPending(true);
      setView(undefined);
      setError("");
      try {
        const receipt = await knowledgeConnections(
          id,
          { action: "proposal", proposalId },
          snapshot.authorityRevision,
        );
        if (started !== epoch.current) return;
        if (receipt.response.kind !== "proposal")
          throw { code: "invalidResponse" };
        setView(receipt.response.value);
      } catch (failure) {
        if (started !== epoch.current) return;
        const code =
          typeof failure === "object" && failure && "code" in failure
            ? failure.code
            : "unavailable";
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
          setPending(false);
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
      if (deferred.current !== handoff) {
        deferred.current = handoff;
        epoch.current += 1;
        void stop()?.catch(() => undefined);
        setView(undefined);
        setError("");
        setReference(handoff.reference);
      }
      return;
    }
    deferred.current = undefined;
    consumed.current = handoff;
    setReference(handoff.reference);
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
    requestId: running.current?.id,
    run,
    cancel,
    canRead:
      available && owned && !pending && /^[0-9a-f]{64}$/.test(reference.trim()),
  };
}
