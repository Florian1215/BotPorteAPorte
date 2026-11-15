import { Check, ChevronLeft, CircleAlert, CircleCheck, Info, LoaderCircle, LocateFixed, TriangleAlert, type LucideIcon } from "lucide-react";
import { useCallback, useContext, useLayoutEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from "react";

import type { AbsentDetail, ResultValue } from "../api/types";
import { useBack } from "../context/BackContext";
import { useMapUI } from "../context/MapContext";
import { GeoContext } from "../hooks/useGeolocation";
import { ABSENT_DETAILS, RESULTS } from "../lib/constants";
import { useFlyTo } from "./map";

// --------------------------------------------------------------------------- buttons

type Variant = "primary" | "secondary" | "ghost" | "danger" | "destructive" | "dark";
type Size = "md" | "sm";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-brand-600 text-white hover:bg-brand-700 active:bg-brand-700 disabled:bg-brand-600/50",
  secondary: "bg-white text-zinc-800 ring-1 ring-zinc-950/10 hover:bg-zinc-50 active:bg-zinc-100 disabled:text-zinc-400",
  ghost: "text-zinc-600 hover:bg-zinc-100 active:bg-zinc-100",
  danger: "bg-red-50 text-red-700 ring-1 ring-red-200 hover:bg-red-100 active:bg-red-100",
  destructive: "bg-red-600 text-white hover:bg-red-700 active:bg-red-700 disabled:bg-red-600/50",
  dark: "bg-zinc-900 text-white hover:bg-zinc-800 active:bg-zinc-800 disabled:bg-zinc-900/50",
};

const SIZES: Record<Size, string> = {
  md: "min-h-12 short:min-h-11 tiny:min-h-10 rounded-2xl px-4 text-[15px] gap-2",
  sm: "min-h-9 rounded-xl px-3 text-sm gap-1.5",
};

export function Button({
  variant = "primary",
  size = "md",
  icon: Icon,
  className = "",
  loading = false,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; icon?: LucideIcon; loading?: boolean }) {
  const iconSize = size === "sm" ? "size-4" : "size-[18px]";
  return (
    <button
      {...props}
      disabled={props.disabled || loading}
      className={`inline-flex items-center justify-center font-semibold tracking-[-0.01em] transition select-none active:scale-[0.98] disabled:cursor-not-allowed disabled:active:scale-100 ${SIZES[size]} ${VARIANTS[variant]} ${className}`}
    >
      {loading ? <Spinner className={iconSize} /> : Icon && <Icon className={iconSize} strokeWidth={2.25} />}
      {children}
    </button>
  );
}

/** Round floating button used over the map. */
export function FloatingButton({ className = "", children, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className={`pointer-events-auto flex size-12 items-center justify-center rounded-full bg-white/90 text-zinc-800 shadow-float ring-1 ring-zinc-950/5 backdrop-blur-xl transition active:scale-95 ${className}`}
    >
      {children}
    </button>
  );
}

// --------------------------------------------------------------------------- feedback

export function Spinner({ className = "size-6" }: { className?: string }) {
  return <LoaderCircle className={`animate-spin ${className}`} aria-hidden />;
}

export function Loading() {
  return (
    <div className="flex justify-center py-8 text-brand-600">
      <Spinner />
    </div>
  );
}

const ALERTS = {
  error: { style: "bg-red-50 text-red-900 ring-red-200/70", icon: CircleAlert, iconStyle: "text-red-600" },
  info: { style: "bg-sky-50 text-sky-950 ring-sky-200/70", icon: Info, iconStyle: "text-sky-600" },
  warning: { style: "bg-amber-50 text-amber-950 ring-amber-200/70", icon: TriangleAlert, iconStyle: "text-amber-600" },
  success: { style: "bg-emerald-50 text-emerald-950 ring-emerald-200/70", icon: CircleCheck, iconStyle: "text-emerald-600" },
};

export function Alert({ kind = "error", children }: { kind?: keyof typeof ALERTS; children: ReactNode }) {
  const { style, icon: Icon, iconStyle } = ALERTS[kind];
  return (
    <div className={`flex gap-2.5 rounded-2xl px-3.5 py-3 text-sm leading-snug ring-1 ${style}`} role={kind === "error" ? "alert" : undefined}>
      <Icon className={`mt-px size-[18px] shrink-0 ${iconStyle}`} />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

export function EmptyState({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-4 py-8 text-center">
      <span className="flex size-12 items-center justify-center rounded-2xl bg-zinc-100 text-zinc-500">
        <Icon className="size-6" />
      </span>
      <p className="mt-3 font-semibold">{title}</p>
      {children && <p className="mt-1 text-sm text-zinc-500">{children}</p>}
    </div>
  );
}

// --------------------------------------------------------------------------- layout bits

const TILE_TONES = {
  brand: "bg-brand-50 text-brand-600",
  neutral: "bg-zinc-100 text-zinc-600",
  sky: "bg-sky-50 text-sky-600",
  amber: "bg-amber-50 text-amber-600",
  emerald: "bg-emerald-50 text-emerald-600",
  inverse: "bg-white/15 text-white",
};

/** Icon in a soft rounded square. */
export function IconTile({
  icon: Icon,
  tone = "brand",
  className = "size-10",
}: {
  icon: LucideIcon;
  tone?: keyof typeof TILE_TONES;
  className?: string;
}) {
  return (
    <span className={`flex shrink-0 items-center justify-center rounded-xl ${TILE_TONES[tone]} ${className}`}>
      <Icon className="size-[55%]" strokeWidth={2} />
    </span>
  );
}

export function Card({ className = "", children }: { className?: string; children: ReactNode }) {
  return <div className={`rounded-2xl bg-white ring-1 ring-zinc-950/[0.07] ${className}`}>{children}</div>;
}

export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-center justify-between pt-1">
      <h2 className="text-[13px] font-semibold text-zinc-500">{children}</h2>
      {action}
    </div>
  );
}

/** iOS-like segmented control; the white pill slides to the selected tab. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: ReactNode }[];
  value: T;
  onChange: (v: T) => void;
}) {
  const index = Math.max(0, options.findIndex((o) => o.value === value));
  return (
    <div className="relative grid auto-cols-fr grid-flow-col rounded-2xl bg-zinc-100 p-1">
      <span
        aria-hidden
        className="absolute top-1 bottom-1 left-1 rounded-xl bg-white shadow-sm ring-1 ring-zinc-950/5 transition-transform duration-300 ease-[cubic-bezier(.2,.8,.2,1)]"
        style={{ width: `calc((100% - 0.5rem) / ${options.length})`, transform: `translateX(${index * 100}%)` }}
      />
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          aria-pressed={o.value === value}
          className={`relative min-h-10 rounded-xl px-2 text-sm font-semibold transition-colors duration-300 ${
            o.value === value ? "text-zinc-900" : "text-zinc-500 active:text-zinc-700"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
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
          className={`min-h-10 shrink-0 rounded-full px-4 text-sm font-semibold tabular-nums transition ${
            option === value
              ? "bg-zinc-900 text-white shadow-sm"
              : "bg-zinc-100 text-zinc-700 active:bg-zinc-200"
          }`}
        >
          {format(option)}
        </button>
      ))}
    </div>
  );
}

export function StatTile({ value, label, icon: Icon, accent = false }: { value: number | string; label: string; icon?: LucideIcon; accent?: boolean }) {
  return (
    <div
      className={`rounded-2xl p-3 ${
        accent ? "bg-brand-600 text-white" : "bg-zinc-50 ring-1 ring-zinc-950/5"
      }`}
    >
      {Icon && <Icon className={`size-4 ${accent ? "opacity-80" : "text-zinc-400"}`} />}
      <p className="mt-1.5 text-2xl font-semibold tracking-tight tabular-nums">{value}</p>
      <p className={`text-xs ${accent ? "text-white/80" : "text-zinc-500"}`}>{label}</p>
    </div>
  );
}

// --------------------------------------------------------------------------- forms

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-semibold text-zinc-700">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-xs text-zinc-500">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "block h-12 w-full rounded-xl border-0 bg-zinc-100 px-4 text-base text-zinc-900 ring-1 ring-transparent transition placeholder:text-zinc-400 focus:bg-white focus:ring-2 focus:ring-brand-600 focus:outline-none";

// --------------------------------------------------------------------------- map overlay

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
        <LocateFixed className={`size-[22px] ${located ? "text-sky-600" : "text-zinc-400"}`} strokeWidth={2.25} />
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
  back = true,
  above,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  locate?: boolean;
  /** Show the screen's back button next to the title (when there is one). */
  back?: boolean;
  /** Floating content docked right above the sheet (e.g. a notification). */
  above?: ReactNode;
}) {
  const { sheetHeight } = useMapUI();
  const goBack = useBack();
  const showBack = back && goBack !== null;
  const ref = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const header = useRef<HTMLDivElement>(null);
  const [collapsed, setCollapsed] = useState(false);
  // How far the panel slides down when collapsed (everything but the header), and the live drag offset.
  const [hideBy, setHideBy] = useState(0);
  const [drag, setDrag] = useState<number | null>(null);
  const gesture = useRef<{ id: number; y: number; t: number; base: number; moved: boolean; lastY: number; lastT: number } | null>(null);
  const justDragged = useRef(false);
  const [contentHeight, setContentHeight] = useState<number | null>(null);
  const contentObserver = useRef<ResizeObserver | null>(null);

  // The scrollable body follows the natural height of its content with a transition,
  // so the sheet grows / shrinks smoothly (tabs, loading → list…) instead of jumping.
  const content = useCallback((el: HTMLDivElement | null) => {
    contentObserver.current?.disconnect();
    contentObserver.current = null;
    if (!el) return setContentHeight(null);
    setContentHeight(el.offsetHeight);
    contentObserver.current = new ResizeObserver(() => setContentHeight(el.offsetHeight));
    contentObserver.current.observe(el);
  }, []);

  const offset = drag ?? (collapsed ? hideBy : 0);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => {
      const max = panel.current && header.current ? Math.max(0, panel.current.offsetHeight - header.current.offsetHeight) : 0;
      setHideBy(max);
      // The map keeps what is under the visible part of the sheet free (fit bounds, fly to).
      sheetHeight.current = el.offsetHeight - (collapsed ? max : 0);
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    if (header.current) observer.observe(header.current);
    return () => {
      observer.disconnect();
      sheetHeight.current = 0;
    };
  }, [sheetHeight, collapsed]);

  // Drag the sheet by its header: it follows the finger, then settles open or collapsed
  // (by position, or by a quick flick). A simple tap on the handle still toggles it.
  const dragHandlers = {
    onPointerDown: (e: React.PointerEvent) => {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      gesture.current = { id: e.pointerId, y: e.clientY, t: e.timeStamp, base: collapsed ? hideBy : 0, moved: false, lastY: e.clientY, lastT: e.timeStamp };
    },
    onPointerMove: (e: React.PointerEvent) => {
      const g = gesture.current;
      if (!g || g.id !== e.pointerId) return;
      const dy = e.clientY - g.y;
      if (!g.moved) {
        if (Math.abs(dy) < 6) return;
        g.moved = true; // a real drag: from now on the header follows the pointer (and its buttons are not clicked)
        (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
      }
      g.lastY = e.clientY;
      g.lastT = e.timeStamp;
      const next = g.base + dy;
      // Rubber band beyond the open position.
      setDrag(next < 0 ? next / 4 : Math.min(next, hideBy + 24));
    },
    onPointerUp: (e: React.PointerEvent) => {
      const g = gesture.current;
      gesture.current = null;
      if (!g || g.id !== e.pointerId || !g.moved) return;
      justDragged.current = true;
      window.setTimeout(() => (justDragged.current = false), 350); // no click followed (released outside)
      const position = g.base + (e.clientY - g.y);
      const velocity = (e.clientY - g.lastY) / Math.max(1, e.timeStamp - g.lastT); // px/ms, > 0 downwards
      const close = Math.abs(velocity) > 0.4 ? velocity > 0 : position > hideBy / 2;
      setCollapsed(close);
      setDrag(null);
    },
    onPointerCancel: () => {
      gesture.current = null;
      setDrag(null);
    },
    // After a drag, the click that follows the pointer release must not hit a button of the header.
    onClickCapture: (e: React.MouseEvent) => {
      if (justDragged.current) {
        justDragged.current = false;
        e.stopPropagation();
        e.preventDefault();
      }
    },
  };

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 z-[1000] flex justify-center sm:px-4 sm:pb-4">
      <div
        ref={ref}
        className={`pointer-events-auto relative w-full max-w-md animate-[sheet-in_.25s_ease-out] ${
          drag === null ? "transition-transform duration-300 ease-[cubic-bezier(.2,.8,.2,1)]" : ""
        }`}
        style={offset ? { transform: `translateY(${offset}px)` } : undefined}
      >
        {(locate || above) && (
          <div className="absolute inset-x-0 bottom-full flex flex-col gap-3 px-3 pb-3 sm:px-0">
            {locate && <LocateButton className="self-end" />}
            {above}
          </div>
        )}
        <div ref={panel} className="flex max-h-[82dvh] short:max-h-[88dvh] flex-col rounded-t-[30px] bg-white/[0.97] shadow-sheet ring-1 ring-zinc-950/5 backdrop-blur-2xl sm:rounded-[30px]">
          <div ref={header} {...dragHandlers} className="shrink-0 touch-none select-none">
            <button
              type="button"
              onClick={() => setCollapsed((c) => !c)}
              aria-label={collapsed ? "Déplier le panneau" : "Replier le panneau"}
              className="flex w-full justify-center pt-2.5 pb-2 short:pt-1.5 short:pb-1.5"
            >
              <span className="h-[5px] w-9 rounded-full bg-zinc-300" />
            </button>
            {(title || action) && (
              <div className="flex items-start gap-3 px-5 pb-3 short:pb-2">
                {showBack && (
                  <button
                    type="button"
                    onClick={goBack}
                    aria-label="Retour"
                    className="-mt-1.5 -ml-2 flex size-9 shrink-0 items-center justify-center rounded-full text-zinc-700 active:bg-zinc-100"
                  >
                    <ChevronLeft className="size-6" strokeWidth={2.25} />
                  </button>
                )}
                <div className="min-w-0 flex-1" onClick={() => collapsed && setCollapsed(false)}>
                  {title && <h1 className="text-xl short:text-lg leading-tight font-semibold tracking-[-0.02em] text-zinc-950">{title}</h1>}
                  {subtitle && <div className="mt-1 short:mt-0.5 text-sm leading-snug text-zinc-500">{subtitle}</div>}
                </div>
                {action && <div className="shrink-0">{action}</div>}
              </div>
            )}
          </div>
          {children && (
            <div
              className="min-h-0 shrink overflow-y-auto overscroll-contain transition-[height] duration-300 ease-[cubic-bezier(.2,.8,.2,1)]"
              style={contentHeight === null ? undefined : { height: contentHeight }}
            >
              <div ref={content} className="space-y-3 px-5 pt-0.5 pb-4 short:space-y-2 short:pb-3">
                {children}
              </div>
            </div>
          )}
          {footer && <div className="shrink-0 border-t border-zinc-950/5 px-5 py-3 short:py-2">{footer}</div>}
          <div className="h-[env(safe-area-inset-bottom)] shrink-0" />
        </div>
      </div>
    </div>
  );
}

/**
 * The 5 feedback options of the bot, as big thumb-friendly buttons.
 * Neutral by default; once a feedback is recorded (`selected`), that button is solid and the others are greyed,
 * so coming back to a person shows at a glance what was picked (tap another one to change it).
 * "Absent·e" does not record anything by itself: it splits in two (leaflet left / mailbox out of reach).
 * Tapping the selected feedback again removes it (`onClear`).
 */
export function ResultButtons({
  onPick,
  onClear,
  busy,
  disabled = false,
  selected = null,
  selectedDetail = null,
}: {
  onPick: (value: ResultValue, absentDetail?: AbsentDetail) => void;
  onClear?: () => void;
  busy: string | null;
  disabled?: boolean;
  selected?: ResultValue | null;
  selectedDetail?: AbsentDetail | null;
}) {
  const [split, setSplit] = useState(false);
  return (
    <div className="grid grid-cols-2 gap-2 short:gap-1.5">
      {RESULTS.map((r, i) => {
        const last = i === RESULTS.length - 1;
        const isSelected = selected === r.value;
        const dimmed = selected !== null && !isSelected;
        if (r.value === "address_to_retry" && (split || isSelected))
          return (
            <div key={r.value} className="grid min-h-[4.5rem] short:min-h-14 tiny:min-h-12 grid-rows-2 gap-1.5 short:gap-1">
              {ABSENT_DETAILS.map((d) => {
                const on = isSelected && selectedDetail === d.value;
                const busyHere = busy === `${r.value}:${d.value}` || (on && busy === "clear");
                return (
                  <button
                    key={d.value}
                    disabled={disabled || busy !== null}
                    onClick={() => (on && onClear ? (setSplit(false), onClear()) : onPick(r.value, d.value))}
                    aria-pressed={on}
                    className={`flex items-center gap-2 rounded-xl px-2.5 py-1.5 text-left text-[12px] leading-tight font-semibold transition active:scale-[0.98] disabled:cursor-not-allowed ${
                      on ? `${r.solid} ring-2` : "bg-amber-50 text-amber-900 ring-1 ring-amber-500/40 active:bg-amber-100"
                    }`}
                  >
                    {busyHere ? (
                      <Spinner className="size-4 shrink-0" />
                    ) : on ? (
                      <Check className="size-4 shrink-0" strokeWidth={3} />
                    ) : (
                      <r.icon className="size-4 shrink-0 text-amber-600" strokeWidth={2.25} />
                    )}
                    {d.label}
                  </button>
                );
              })}
            </div>
          );
        return (
          <button
            key={r.value}
            disabled={disabled || busy !== null}
            onClick={() =>
              isSelected && onClear ? onClear() : r.value === "address_to_retry" ? setSplit(true) : (setSplit(false), onPick(r.value))
            }
            aria-pressed={isSelected}
            className={`flex min-h-[4.5rem] short:min-h-14 tiny:min-h-12 items-center gap-2.5 rounded-2xl px-3 py-2.5 short:py-1.5 text-left text-[13px] leading-tight font-semibold transition active:scale-[0.98] disabled:cursor-not-allowed ${
              isSelected
                ? `${r.solid} ring-2`
                : dimmed
                  ? "bg-zinc-50 text-zinc-400 ring-1 ring-zinc-950/5"
                  : "bg-white text-zinc-800 ring-1 ring-zinc-950/10 active:bg-zinc-50"
            } ${disabled && !isSelected ? "opacity-50" : ""} ${last ? "col-span-2 min-h-14 short:min-h-11 tiny:min-h-10" : ""}`}
          >
            <span
              className={`flex size-9 tiny:size-7 shrink-0 items-center justify-center rounded-full ${
                isSelected ? "bg-white/20 text-white" : dimmed ? "bg-zinc-200 text-zinc-400" : `${r.disc} text-white`
              }`}
            >
              {busy === r.value || (isSelected && busy === "clear") ? <Spinner className="size-[18px]" /> : isSelected ? <Check className="size-[18px]" strokeWidth={3} /> : <r.icon className="size-[18px]" strokeWidth={2.25} />}
            </span>
            {r.short}
          </button>
        );
      })}
    </div>
  );
}

export function OverlaySpinner() {
  return (
    <div className="absolute inset-0 z-[1000] flex items-center justify-center bg-white/40 text-brand-600 backdrop-blur-[2px]">
      <Spinner className="size-8" />
    </div>
  );
}
