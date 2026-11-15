import { LoaderCircle, MapPin, Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, errorMessage } from "../api/client";
import type { City, CityFields } from "../api/types";
import { Field, inputClass } from "./ui";

/** Search-as-you-type city field: picking a result gives the city, its position and its country at once. */
export default function CityPicker({ value, onChange }: { value: CityFields; onChange: (city: CityFields) => void }) {
  const [editing, setEditing] = useState(!value.city);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<City[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setResults(null);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      setLoading(true);
      setError(null);
      api<City[]>("/manage/cities/", { query: { q } })
        .then((r) => !cancelled && setResults(r))
        .catch((e) => !cancelled && setError(errorMessage(e)))
        .finally(() => !cancelled && setLoading(false));
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query]);

  const pick = (city: City) => {
    onChange({ city: city.name, city_lat: city.lat, city_lon: city.lon, country_code: city.country_code });
    setEditing(false);
    setQuery("");
    setResults(null);
  };

  if (!editing && value.city)
    return (
      <Field label="Ville">
        <button
          type="button"
          onClick={() => {
            setEditing(true);
            setTimeout(() => input.current?.focus());
          }}
          className="flex h-12 w-full items-center gap-2.5 rounded-xl bg-zinc-100 px-4 text-left text-base"
        >
          <MapPin className="size-[18px] shrink-0 text-brand-600" />
          <span className="min-w-0 flex-1 truncate font-medium">{value.city}</span>
          <span className="shrink-0 rounded-md bg-white px-1.5 py-0.5 text-xs font-semibold text-zinc-500 ring-1 ring-zinc-950/10">
            {value.country_code}
          </span>
          <span className="shrink-0 text-sm font-semibold text-brand-600">Changer</span>
        </button>
      </Field>
    );

  return (
    <Field label="Ville">
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-3.5 size-[18px] -translate-y-1/2 text-zinc-400" />
        <input
          ref={input}
          className={`${inputClass} px-10`}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Rechercher une ville…"
          autoComplete="off"
          autoFocus={!!value.city}
        />
        {loading ? (
          <LoaderCircle className="absolute top-1/2 right-3.5 size-[18px] -translate-y-1/2 animate-spin text-zinc-400" />
        ) : (
          value.city && (
            <button
              type="button"
              aria-label="Annuler"
              onClick={() => (setEditing(false), setQuery(""))}
              className="absolute top-1/2 right-2 flex size-8 -translate-y-1/2 items-center justify-center rounded-full text-zinc-400 active:bg-zinc-200"
            >
              <X className="size-4" />
            </button>
          )
        )}
      </div>
      {error && <span className="mt-1.5 block text-xs text-red-600">{error}</span>}
      {results && (
        <div className="mt-1.5 overflow-hidden rounded-xl bg-white ring-1 ring-zinc-950/10">
          {results.length === 0 ? (
            <p className="px-4 py-3 text-sm text-zinc-500">Aucune ville trouvée.</p>
          ) : (
            results.map((city) => (
              <button
                key={`${city.name}-${city.lat}-${city.lon}`}
                type="button"
                onClick={() => pick(city)}
                className="flex w-full items-center gap-3 border-b border-zinc-950/5 px-3.5 py-2.5 text-left last:border-b-0 active:bg-zinc-50"
              >
                <MapPin className="size-4 shrink-0 text-zinc-400" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">{city.name}</span>
                  <span className="block truncate text-xs text-zinc-500">{[city.region, city.country].filter(Boolean).join(", ")}</span>
                </span>
                <span className="shrink-0 text-xs font-semibold text-zinc-400">{city.country_code}</span>
              </button>
            ))
          )}
        </div>
      )}
    </Field>
  );
}
