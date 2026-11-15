import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { Member } from "../api/types";
import { useAuth } from "../context/AuthContext";

/** Fired after a sign-up is accepted / refused, so every badge and notification refreshes. */
const PENDING_CHANGED = "canvassing:pending-changed";

export function notifyPendingChanged() {
  window.dispatchEvent(new Event(PENDING_CHANGED));
}

/** Sign-ups waiting for approval in the user's organization (empty if they cannot validate). */
export function usePendingMembers(): { members: Member[]; reload: () => void } {
  const { user } = useAuth();
  const [members, setMembers] = useState<Member[]>([]);
  const allowed = Boolean(user?.can_validate && user.organization);
  const org = user?.organization?.code;

  const reload = useCallback(() => {
    if (!allowed) return setMembers([]);
    api<Member[]>("/manage/members/", { query: { status: "pending" } })
      .then(setMembers)
      .catch(() => setMembers([]));
  }, [allowed, org]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    reload();
    window.addEventListener(PENDING_CHANGED, reload);
    return () => window.removeEventListener(PENDING_CHANGED, reload);
  }, [reload]);

  return { members, reload };
}

/** Number of sign-ups waiting for approval (0 if the user cannot validate). */
export function usePendingCount(): number {
  return usePendingMembers().members.length;
}
