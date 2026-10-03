import { useConnectionAuthority } from "@/hooks/use-connection-authority";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ServerConnectionSnapshot } from "@/server";
import {
  cancelKnowledgeConnections,
  connectionsError,
  knowledgeConnections,
  type ConceptPage,
  type ConnectionNode,
  type ConnectionsRequest,
  type KnowledgeNeighborhood,
} from "@/knowledge-connections";

export function useKnowledgeConnections(
  active: boolean,
  snapshot: ServerConnectionSnapshot,
) {
  const available =
    snapshot.state === "ready" && snapshot.capabilities.knowledgeConnections;
  const [search, setSearch] = useState("");
  const [topics, setTopics] = useState<ConceptPage | null>(null);
  const [graph, setGraph] = useState<KnowledgeNeighborhood | null>(null);
  const [trail, setTrail] = useState<ConnectionNode[]>([]);
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const epoch = useRef(0);
  const running = useRef<{ id: string; epoch: number } | null>(null);
  const lastRequest = useRef<{
    request: ConnectionsRequest;
    trail: ConnectionNode[];
  } | null>(null);

  const clear = useCallback(() => {
    lastRequest.current = null;
    setTopics(null);
    setGraph(null);
    setTrail([]);
    setSelectedEdge(null);
    setSearch("");
  }, []);
  const invalidate = useCallback(() => {
    epoch.current += 1;
    if (running.current)
      void cancelKnowledgeConnections(running.current.id).catch(
        () => undefined,
      );
  }, []);
  const invalidateView = useCallback(
    (changed: boolean) => {
      invalidate();
      clear();
      setError(
        changed && active
          ? "Your server or sign-in changed. Refresh topics to continue."
          : "",
      );
    },
    [active, clear, invalidate],
  );
  const owned = useConnectionAuthority(
    active && available,
    snapshot.authorityRevision,
    invalidateView,
  );
  const current = active && available && owned;
  const awaitingAuthority = active && available && !current;
  useEffect(() => () => invalidate(), [invalidate]);

  async function run(
    request: ConnectionsRequest,
    nextTrail: ConnectionNode[] = [],
  ) {
    if (!current || running.current) return;
    const id = crypto.randomUUID();
    const started = epoch.current;
    running.current = { id, epoch: started };
    setPending(true);
    setError("");
    // Clear the previous neighborhood immediately: its source must never be
    // mistaken for the topic currently loading or left visible after denial.
    setGraph(null);
    setSelectedEdge(null);
    lastRequest.current = { request, trail: nextTrail };
    try {
      const receipt = await knowledgeConnections(
        id,
        request,
        snapshot.authorityRevision,
      );
      if (started !== epoch.current) return;
      if (receipt.response.kind === "topics") {
        setTopics(receipt.response.value);
        setTrail([]);
      } else if (receipt.response.kind === "neighborhood") {
        setGraph(receipt.response.value);
        setTrail(nextTrail.slice(-8));
      }
    } catch (failure) {
      if (started !== epoch.current) return;
      const view = connectionsError(failure);
      if (view.clear) clear();
      setError(view.message);
    } finally {
      if (running.current?.id === id) {
        running.current = null;
        setPending(false);
      }
    }
  }
  function browse(reset = false) {
    if (reset) {
      clear();
      return run({ action: "browse", search: "" });
    }
    return run({ action: "browse", search: search.trim() });
  }
  function explore(node: ConnectionNode, previous = trail) {
    const generation = graph?.generationSha256 ?? topics?.generationSha256;
    if (!generation) return;
    const next = [...previous, node];
    return run(
      {
        action: "read",
        conceptId: node.conceptId,
        generationSha256: generation,
      },
      next,
    );
  }
  function back(index: number) {
    const node = trail[index];
    if (node) return explore(node, trail.slice(0, index));
  }
  function retry() {
    const last = lastRequest.current;
    return last ? run(last.request, last.trail) : browse(true);
  }
  async function cancel() {
    const request = running.current;
    if (!request) return;
    epoch.current += 1;
    setError("Exploration cancelled. You can try again.");
    // Keep the control busy until the native request releases its permit.
    // Server SQL is read-only and may finish within its own time limits.
    try {
      await cancelKnowledgeConnections(request.id);
    } catch {
      setError(
        "Cancellation could not be confirmed. Waiting for this read to finish.",
      );
    }
  }
  const selected =
    (current ? graph : null)?.relationships.find(
      (edge) => edge.relationshipId === selectedEdge,
    ) ?? null;
  return {
    available,
    search: current ? search : "",
    setSearch,
    topics: current ? topics : null,
    graph: current ? graph : null,
    trail: current ? trail : [],
    selected,
    setSelectedEdge,
    error,
    pending,
    checkingAuthority: awaitingAuthority,
    browse,
    explore,
    back,
    retry,
    cancel,
  };
}
