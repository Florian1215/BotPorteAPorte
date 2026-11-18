import { ChevronDown } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { VoterList } from "../api/types";
import { Field, inputClass } from "./ui";

/** Radius proposed around the organization's city (km). */
const RADII_KM = [10, 20, 30, 50, 100, 200];

export type VoterListChoice = { voter_list: number | null; radius_km: number };

/**
 * Site admins: the voter list (LEC) an organization depends on, and how far around its city its addresses go
 * (several organizations can share one list, e.g. Berlin and Leipzig on the Berlin consulate's list).
 */
export default function VoterListPicker({ value, onChange }: { value: VoterListChoice; onChange: (v: VoterListChoice) => void }) {
  const [lists, setLists] = useState<VoterList[] | null>(null);
  useEffect(() => {
    api<VoterList[]>("/manage/voter-lists/")
      .then(setLists)
      .catch(() => setLists([]));
  }, []);

  const radii = RADII_KM.includes(value.radius_km) ? RADII_KM : [...RADII_KM, value.radius_km].sort((a, b) => a - b);

  return (
    <div className="grid grid-cols-[1fr_auto] gap-2">
      <Field label="LEC" hint={lists?.length === 0 ? "Aucune LEC : crée-la d'abord dans le menu « LEC »." : undefined}>
        <div className="relative">
          <ChevronDown className="pointer-events-none absolute top-1/2 right-3.5 size-[18px] -translate-y-1/2 text-zinc-400" />
          <select
            className={`${inputClass} appearance-none pr-10`}
            value={value.voter_list ?? ""}
            onChange={(e) => onChange({ ...value, voter_list: e.target.value ? Number(e.target.value) : null })}
            required
          >
            <option value="" disabled>
              {lists ? "Choisis la LEC…" : "Chargement…"}
            </option>
            {lists?.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </div>
      </Field>
      <Field label="Rayon">
        <div className="relative">
          <ChevronDown className="pointer-events-none absolute top-1/2 right-3 size-[18px] -translate-y-1/2 text-zinc-400" />
          <select
            className={`${inputClass} appearance-none pr-9 tabular-nums`}
            value={value.radius_km}
            onChange={(e) => onChange({ ...value, radius_km: Number(e.target.value) })}
          >
            {radii.map((km) => (
              <option key={km} value={km}>
                {km} km
              </option>
            ))}
          </select>
        </div>
      </Field>
    </div>
  );
}
