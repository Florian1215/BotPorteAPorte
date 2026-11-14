import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../api/client";
import type { AddressDTO, GeocodedAddress, ResultValue } from "../api/types";
import { FlyTo, MapLayers, PinMarker } from "../components/map";
import { Alert, Button, Field, ResultButtons, Sheet, inputClass } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { RESULT_BY_VALUE } from "../lib/constants";

type Step = "address" | "confirm" | "name" | "result" | "done";

const EXAMPLES: Record<string, { street: string; city: string }> = {
  FR: { street: "12 rue de la Paix", city: "75002 Paris" },
  AT: { street: "Praterstraße 32", city: "1020 Wien" },
};

export default function ManualMark() {
  const { user } = useAuth();
  const example = EXAMPLES[user?.scope?.country_code ?? ""] ?? { street: "Rostocker Str. 32", city: "10553 Berlin" };

  const [step, setStep] = useState<Step>("address");
  const [street, setStreet] = useState("");
  const [postcodeCity, setPostcodeCity] = useState("");
  const [geocoded, setGeocoded] = useState<GeocodedAddress | null>(null);
  const [name, setName] = useState("");
  const [matches, setMatches] = useState<AddressDTO[]>([]);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [result, setResult] = useState<ResultValue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<string | null>(null);

  const run = async (key: string, fn: () => Promise<void>) => {
    setLoading(key);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(null);
    }
  };

  const geocode = (e: FormEvent) => {
    e.preventDefault();
    run("geocode", async () => {
      setGeocoded(await api<GeocodedAddress>("/manual/geocode/", { method: "POST", body: { street, postcode_city: postcodeCity } }));
      setStep("confirm");
    });
  };

  const search = (e: FormEvent) => {
    e.preventDefault();
    if (!geocoded) return;
    run("search", async () => {
      const found = await api<AddressDTO[]>("/manual/search/", {
        method: "POST",
        body: { address: geocoded.address, zip_code: geocoded.zip_code, city: geocoded.city, name },
      });
      if (found.length === 0) {
        setError("Cette adresse n'a pas été trouvée dans la base de données, ou a déjà été visitée ou marquée comme invalide.");
        return;
      }
      setMatches(found);
      setChecked(new Set(found.map((m) => m.id)));
      setStep("result");
    });
  };

  const mark = (value: ResultValue) =>
    run(value, async () => {
      await api("/manual/mark/", { method: "POST", body: { address_ids: [...checked], result: value } });
      setResult(value);
      setStep("done");
    });

  const reset = () => {
    setStep("address");
    setStreet("");
    setPostcodeCity("");
    setGeocoded(null);
    setName("");
    setMatches([]);
    setResult(null);
    setError(null);
  };

  const geocodedLabel = geocoded ? `${geocoded.address}, ${geocoded.zip_code} ${geocoded.city}` : "";

  return (
    <>
      {geocoded && (
        <MapLayers>
          <FlyTo point={[geocoded.lat, geocoded.lon]} zoom={17} />
          <PinMarker point={geocoded} color="#c8102e" label={geocoded.address} />
        </MapLayers>
      )}

      {step === "address" && (
        <Sheet title="Marquer une adresse" subtitle="Une adresse que tu as visitée en dehors d'une tournée.">
          <form onSubmit={geocode} className="space-y-3">
            <Field label="Rue et numéro">
              <input
                className={inputClass}
                placeholder={example.street}
                value={street}
                onChange={(e) => setStreet(e.target.value)}
                autoComplete="street-address"
                required
              />
            </Field>
            <Field label="Code postal et ville">
              <input
                className={inputClass}
                placeholder={example.city}
                value={postcodeCity}
                onChange={(e) => setPostcodeCity(e.target.value)}
                required
              />
            </Field>
            {error && <Alert>{error}</Alert>}
            <Button type="submit" className="w-full" loading={loading === "geocode"}>
              Rechercher l'adresse
            </Button>
          </form>
        </Sheet>
      )}

      {step === "confirm" && geocoded && (
        <Sheet
          title="C'est bien ici ?"
          subtitle={geocodedLabel}
          footer={
            <div className="grid grid-cols-2 gap-2">
              <Button variant="secondary" onClick={() => setStep("address")}>
                👎 Corriger
              </Button>
              <Button onClick={() => setStep("name")}>👍 Oui</Button>
            </div>
          }
        />
      )}

      {step === "name" && (
        <Sheet title="Qui habite ici ?" subtitle={geocodedLabel}>
          <form onSubmit={search} className="space-y-3">
            <Field label="Nom de famille (nom d'usage)" hint="Au moins les 3 premières lettres.">
              <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} minLength={3} required autoFocus />
            </Field>
            {error && <Alert>{error}</Alert>}
            <Button type="submit" className="w-full" loading={loading === "search"}>
              Chercher dans la liste
            </Button>
          </form>
        </Sheet>
      )}

      {step === "result" && (
        <Sheet title="Quel retour ?" subtitle={geocodedLabel}>
          <div className="rounded-2xl bg-slate-50 p-3 ring-1 ring-slate-200">
            <p className="mb-1 text-xs font-medium text-slate-500">
              {matches.length > 1 ? "Plusieurs personnes portent ce nom à cette adresse :" : "Personne trouvée :"}
            </p>
            {matches.map((m) => (
              <label key={m.id} className="flex items-center gap-3 py-1.5">
                <input
                  type="checkbox"
                  className="size-5 accent-brand-600"
                  checked={checked.has(m.id)}
                  onChange={(e) => {
                    const next = new Set(checked);
                    if (e.target.checked) next.add(m.id);
                    else next.delete(m.id);
                    setChecked(next);
                  }}
                />
                <span className="font-semibold">
                  {m.first_name} {m.name}
                </span>
              </label>
            ))}
          </div>
          {error && <Alert>{error}</Alert>}
          <ResultButtons busy={loading} disabled={checked.size === 0} onPick={mark} />
        </Sheet>
      )}

      {step === "done" && result && (
        <Sheet
          title="Merci pour l'information ! ✊"
          subtitle={`${checked.size > 1 ? `Les ${checked.size} personnes ont` : "L'adresse a"} bien été marquée${
            checked.size > 1 ? "s" : ""
          } : ${RESULT_BY_VALUE[result].emoji} ${RESULT_BY_VALUE[result].label}`}
          footer={
            <div className="grid grid-cols-2 gap-2">
              <Button variant="secondary" onClick={reset}>
                Autre adresse
              </Button>
              <Link to="/" className="flex min-h-12 items-center justify-center rounded-2xl bg-brand-600 font-semibold text-white">
                Accueil
              </Link>
            </div>
          }
        />
      )}
    </>
  );
}
