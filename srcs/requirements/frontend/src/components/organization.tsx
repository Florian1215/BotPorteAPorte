import { ChevronDown, DoorOpen } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { Organization } from "../api/types";
import { Field, inputClass } from "./ui";

/** Organization logo, or its initial on a brand-colored disc when it has none. */
export function OrgLogo({ organization, className = "size-10" }: { organization: Pick<Organization, "name" | "logo_url"> | null; className?: string }) {
  if (organization?.logo_url) {
    return <img src={organization.logo_url} alt="" className={`${className} shrink-0 rounded-xl bg-white object-contain p-0.5 ring-1 ring-zinc-950/10`} />;
  }
  return (
    <span
      className={`${className} flex shrink-0 items-center justify-center rounded-xl bg-brand-600 font-semibold text-white`}
      aria-hidden
    >
      {organization?.name.trim().charAt(0).toUpperCase() || <DoorOpen className="size-1/2" />}
    </span>
  );
}

/** Public list of organizations (login / sign-up screens). `null` while loading. */
export function useOrganizations(): Organization[] | null {
  const [organizations, setOrganizations] = useState<Organization[] | null>(null);
  useEffect(() => {
    api<Organization[]>("/auth/organizations/").then(setOrganizations).catch(() => setOrganizations([]));
  }, []);
  return organizations;
}

export function OrganizationSelect({
  organizations,
  value,
  onChange,
  required = true,
}: {
  organizations: Organization[];
  value: string;
  onChange: (code: string) => void;
  required?: boolean;
}) {
  const selected = organizations.find((o) => o.code === value) ?? null;
  return (
    <Field label="Organisation">
      <div className="relative">
        <span className="pointer-events-none absolute top-1/2 left-2 -translate-y-1/2">
          <OrgLogo organization={selected} className="size-8 text-sm" />
        </span>
        <ChevronDown className="pointer-events-none absolute top-1/2 right-3.5 size-[18px] -translate-y-1/2 text-zinc-400" />
        <select className={`${inputClass} appearance-none pr-10 pl-12 font-medium`} value={value} onChange={(e) => onChange(e.target.value)} required={required}>
          <option value="" disabled={required}>
            Choisis ton organisation…
          </option>
          {organizations.map((o) => (
            <option key={o.code} value={o.code}>
              {o.name}
            </option>
          ))}
        </select>
      </div>
    </Field>
  );
}
