import { Check, UserPlus, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import type { Member } from "../api/types";
import { notifyPendingChanged } from "../hooks/usePendingCount";
import { Button } from "./ui";

/** Notification shown above the home sheet: "X wants to join <organization>" with accept / refuse. */
export default function JoinRequest({ member, organization, others }: { member: Member; organization: string; others: number }) {
  const [busy, setBusy] = useState<"accept" | "refuse" | null>(null);
  const [confirmRefuse, setConfirmRefuse] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const name = [member.first_name, member.last_name].filter(Boolean).join(" ") || member.email;

  const act = async (kind: "accept" | "refuse") => {
    setBusy(kind);
    setError(null);
    try {
      if (kind === "accept") await api(`/manage/members/${member.id}/`, { method: "PATCH", body: { is_approved: true } });
      else await api(`/manage/members/${member.id}/`, { method: "DELETE" });
      notifyPendingChanged();
    } catch (e) {
      setError(errorMessage(e));
      setBusy(null);
    }
  };

  return (
    <div className="rounded-3xl bg-white/[0.97] p-3.5 shadow-float ring-1 ring-zinc-950/5 backdrop-blur-xl" role="status">
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-600">
          <UserPlus className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm leading-snug">
            <strong className="font-semibold">{name}</strong> veut rejoindre <strong className="font-semibold">{organization}</strong>
          </p>
          <p className="mt-0.5 truncate text-xs text-zinc-500">
            {member.email}
            {others > 0 && (
              <>
                {" · "}
                <Link to="/members" className="font-semibold text-brand-600">
                  +{others} autre{others > 1 ? "s" : ""}
                </Link>
              </>
            )}
          </p>
        </div>
      </div>
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
      <div className="mt-3 grid grid-cols-2 gap-2">
        {confirmRefuse ? (
          <>
            <Button variant="secondary" size="sm" onClick={() => setConfirmRefuse(false)} disabled={busy !== null}>
              Annuler
            </Button>
            <Button variant="danger" size="sm" icon={X} loading={busy === "refuse"} onClick={() => act("refuse")}>
              Confirmer le refus
            </Button>
          </>
        ) : (
          <>
            <Button variant="secondary" size="sm" icon={X} onClick={() => setConfirmRefuse(true)} disabled={busy !== null}>
              Refuser
            </Button>
            <Button size="sm" icon={Check} loading={busy === "accept"} onClick={() => act("accept")}>
              Accepter
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
