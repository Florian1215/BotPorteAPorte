import type { ReactNode } from "react";

import { Sheet } from "../components/ui";

/** Sign-in screens: the map stays visible behind a bottom sheet. */
export default function AuthShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <>
      <div className="pointer-events-none absolute inset-x-0 top-0 z-[1000] flex justify-center px-4 pt-[max(1rem,env(safe-area-inset-top))]">
        <div className="flex items-center gap-2 rounded-full bg-white/95 px-4 py-2 text-sm font-bold shadow-lg ring-1 ring-black/5">
          <span aria-hidden>🚪</span> Porte-à-porte militant
        </div>
      </div>
      <Sheet title={title} locate={false}>
        {children}
      </Sheet>
    </>
  );
}
