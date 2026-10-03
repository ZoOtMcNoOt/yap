import { useEffect, useState } from "react";

// Clear each request owner's private state before adopting a new native
// connection. The render guard hides old values before the effect runs.
// Availability controls results; an unchanged owner can still draft offline.
export function useConnectionAuthority(
  available: boolean,
  revision: string,
  invalidate: (changed: boolean) => void,
) {
  const [ownerRevision, setOwnerRevision] = useState(revision);
  useEffect(() => {
    const changed = ownerRevision !== revision;
    if (changed || !available) {
      invalidate(changed);
      setOwnerRevision(revision);
    }
  }, [available, revision, ownerRevision, invalidate]);
  return (
    typeof revision === "string" &&
    /^\d{1,20}$/.test(revision) &&
    ownerRevision === revision
  );
}
