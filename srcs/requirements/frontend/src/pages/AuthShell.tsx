import { DoorOpen } from "lucide-react";
import type { ReactNode } from "react";

import type { Organization } from "../api/types";
import { OrgLogo } from "../components/organization";
import { Sheet } from "../components/ui";

/** Sign-in screens: the map stays visible behind a bottom sheet. */
export default function AuthShell({
  title,
  subtitle,
  organization = null,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  organization?: Organization | null;
  children: ReactNode;
}) {
  return (
    <>
      <div className="pointer-events-none absolute inset-x-0 top-0 z-[1000] flex justify-center px-4 pt-[max(1rem,env(safe-area-inset-top))]">
        <div className="flex h-12 items-center gap-2.5 rounded-full bg-white/90 py-1.5 pr-5 pl-1.5 text-sm font-semibold tracking-tight shadow-float ring-1 ring-zinc-950/5 backdrop-blur-xl">
          {organization ? (
            <>
              <OrgLogo organization={organization} className="size-9 rounded-full text-sm" />
              {organization.name}
            </>
          ) : (
            <>
              <span className="flex size-9 items-center justify-center rounded-full bg-brand-600 text-white">
                <DoorOpen className="size-[18px]" />
              </span>
              Porte-à-porte militant
            </>
          )}
        </div>
      </div>
      <Sheet title={title} subtitle={subtitle} locate={false}>
        {children}
      </Sheet>
    </>
  );
}
