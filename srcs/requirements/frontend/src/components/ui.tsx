import { useContext, useLayoutEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from "react";

import type { ResultValue } from "../api/types";
import { useMapUI } from "../context/MapContext";
import { GeoContext } from "../hooks/useGeolocation";
import { RESULTS } from "../lib/constants";
import { useFlyTo } from "./map";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand-600 text-white active:bg-brand-700 hover:bg-brand-700 disabled:bg-brand-600/50",
  secondary: "bg-white text-slate-800 ring-1 ring-slate-300 active:bg-slate-100 hover:bg-slate-50 disabled:text-slate-400",
  ghost: "text-slate-700 active:bg-slate-100 hover:bg-slate-100",
  danger: "bg-white text-red-700 ring-1 ring-red-300 active:bg-red-50 hover:bg-red-50",
};

export function Button({
  variant = "primary",
  className = "",
  loading = false,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  return (
    <button
      {...props}
      disabled={props.disabled || loading}
      className={`inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl px-4 py-3 text-[15px] font-semibold transition select-none disabled:cursor-not-allowed ${VARIANTS[variant]} ${className}`}
    >
      {loading && <Spinner className="size-4" />}
      {children}
    </button>
  );
}

/** Round floating button used over the map. */
export function FloatingButton({ className = "", children, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className={`pointer-events-auto flex size-12 items-center justify-center rounded-full bg-white text-slate-800 shadow-lg ring-1 ring-black/5 transition active:scale-95 ${className}`}
    >
      {children}
    </button>
  );
}

export function Spinner({ className = "size-6" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="4" />
      <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
    </svg>
  );
}

export function Alert({ kind = "error", children }: { kind?: "error" | "info" | "warning" | "success"; children: ReactNode }) {
  const styles = {
    error: "bg-red-50 text-red-800 ring-red-200",
    info: "bg-sky-50 text-sky-900 ring-sky-200",
    warning: "bg-amber-50 text-amber-900 ring-amber-200",
    success: "bg-green-50 text-green-900 ring-green-200",
  }[kind];
  return <div className={`rounded-2xl px-3.5 py-2.5 text-sm ring-1 ${styles}`}>{children}</div>;
}

/** Single-choice pills, horizontally scrollable on small screens. */
export function Chips<T extends string | number>({
  options,
  value,
  onChange,
  format = String,
}: {
  options: T[];
  value: T | null;
  onChange: (v: T) => void;
  format?: (v: T) => string;
}) {
  return (
    <div className="-mx-5 flex gap-2 overflow-x-auto px-5 pb-1 [scrollbar-width:none]">
      {options.map((option) => (
        <button
          key={String(option)}
          type="button"
          onClick={() => onChange(option)}
          className={`min-h-11 shrink-0 rounded-full px-4 text-sm font-semibold ring-1 transition ${
            option === value ? "bg-brand-600 text-white ring-brand-600" : "bg-white text-slate-700 ring-slate-300 active:bg-slate-100"
          }`}
        >
          {format(option)}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "block w-full rounded-2xl border-0 bg-slate-50 px-4 py-3 text-base ring-1 ring-slate-200 placeholder:text-slate-400 focus:bg-white focus:ring-2 focus:ring-brand-600 focus:outline-none";

/** Re-centers the map on the device position. */
export function LocateButton({ className = "" }: { className?: string }) {
  const geo = useContext(GeoContext);
  const flyTo = useFlyTo();
  if (!geo) return null;
  const located = geo.status === "ok" && geo.here;
  return (
    <FloatingButton
      className={className}
      aria-label="Me localiser"
      onClick={() => (geo.here ? flyTo([geo.here.lat, geo.here.lon], 16) : geo.retry())}
    >
      {geo.status === "pending" ? (
        <Spinner className="size-5 text-sky-600" />
      ) : (
        <svg viewBox="0 0 24 24" className={`size-6 ${located ? "text-sky-600" : "text-slate-500"}`} fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="7" />
          <circle cx="12" cy="12" r="2.5" fill={located ? "currentColor" : "none"} />
          <path d="M12 2v3M12 19v3M2 12h3M19 12h3" strokeLinecap="round" />
        </svg>
      )}
    </FloatingButton>
  );
}

/**
 * Bottom sheet docked over the background map (the mobile layout of every screen).
 * Swipe down / tap the handle to collapse it and see the map, swipe up to expand.
 */
export function Sheet({
  title,
  subtitle,
  action,
  children,
  footer,
  locate = true,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  locate?: boolean;
}) {
  const { sheetHeight } = useMapUI();
  const ref = useRef<HTMLDivElement>(null);
  const touchY = useRef<number | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => (sheetHeight.current = el.offsetHeight);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => {
      observer.disconnect();
      sheetHeight.current = 0;
    };
  }, [sheetHeight]);

  const swipe = {
    onTouchStart: (e: React.TouchEvent) => (touchY.current = e.touches[0].clientY),
    onTouchEnd: (e: React.TouchEvent) => {
      if (touchY.current === null) return;
      const dy = e.changedTouches[0].clientY - touchY.current;
      if (dy > 40) setCollapsed(true);
      if (dy < -40) setCollapsed(false);
      touchY.current = null;
    },
  };

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 z-[1000] flex justify-center sm:px-4 sm:pb-4">
      <div ref={ref} className="pointer-events-auto relative w-full max-w-md">
        {locate && <LocateButton className="absolute -top-16 right-3" />}
        <div className="flex max-h-[80dvh] flex-col rounded-t-[28px] bg-white shadow-[0_-6px_30px_rgb(0_0_0/0.18)] sm:rounded-[28px]">
          <div {...swipe} className="shrink-0 touch-none">
            <button
              type="button"
              onClick={() => setCollapsed((c) => !c)}
              aria-label={collapsed ? "Déplier le panneau" : "Replier le panneau"}
              className="flex w-full justify-center pt-2.5 pb-2"
            >
              <span className="h-1.5 w-10 rounded-full bg-slate-300" />
            </button>
            {(title || action) && (
              <div className="flex items-start gap-3 px-5 pb-3">
                <div className="min-w-0 flex-1" onClick={() => collapsed && setCollapsed(false)}>
                  {title && <h1 className="text-lg leading-snug font-bold tracking-tight">{title}</h1>}
                  {subtitle && <div className="mt-0.5 text-sm text-slate-500">{subtitle}</div>}
                </div>
                {action && <div className="shrink-0">{action}</div>}
              </div>
            )}
          </div>
          {!collapsed && children && (
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain px-5 pb-4">{children}</div>
          )}
          {!collapsed && footer && <div className="shrink-0 border-t border-slate-100 px-5 pt-3 pb-3">{footer}</div>}
          <div className="h-[env(safe-area-inset-bottom)] shrink-0" />
        </div>
      </div>
    </div>
  );
}

/** The 5 feedback options of the bot, as big thumb-friendly buttons. */
export function ResultButtons({
  onPick,
  busy,
  disabled = false,
}: {
  onPick: (value: ResultValue) => void;
  busy: string | null;
  disabled?: boolean;
}) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {RESULTS.map((r, i) => (
        <button
          key={r.value}
          disabled={disabled || busy !== null}
          onClick={() => onPick(r.value)}
          className={`flex min-h-16 flex-col items-center justify-center gap-0.5 rounded-2xl px-2 py-2 text-center text-[13px] leading-tight font-semibold transition active:scale-[0.98] disabled:opacity-60 ${r.className} ${
            i === RESULTS.length - 1 ? "col-span-2 min-h-12 flex-row gap-2" : ""
          }`}
        >
          <span className="text-xl">{busy === r.value ? <Spinner className="size-5" /> : r.emoji}</span>
          {r.short}
        </button>
      ))}
    </div>
  );
}

export function OverlaySpinner() {
  return (
    <div className="absolute inset-0 z-[1000] flex items-center justify-center bg-white/40 text-brand-600">
      <Spinner className="size-8" />
    </div>
  );
}
