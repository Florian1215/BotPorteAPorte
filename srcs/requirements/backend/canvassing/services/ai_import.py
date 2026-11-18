"""AI import of an organization's zones: a Claude Managed Agents session finds the electoral map, the results and
a social indicator of the organization's city, and the party closest to LFI in its country.

The agent works in its own container (web search, downloads, Python to convert any format) and only hands over
normalized files (`OUTPUT_CONTRACT`). It then calls our `submit_import` tool: the server reads the files with the
same code as the other imports and checks them (results matched, zones around the organization's city…). A
failed check goes back to the agent as an error to fix; a passing one replaces the organization's districts.

The agent and its environment are created once by `manage.py setup_ai_agent` (stored in `AiAgentConfig`); each
import is one session, capped by `AI_IMPORT_BUDGET_USD`.
"""
import logging
import math
import threading
import time
from dataclasses import dataclass, field

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from ..models import AiAgentConfig, DistrictImport
from . import districts as district_service

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
OUTPUT_DIR = "/mnt/session/outputs"
MAX_FILE_BYTES = 100 * 1024 * 1024
MIN_MATCHED_SHARE = 0.8
DISTANCE_MARGIN_KM = 20
SESSION_TIMEOUT_S = 40 * 60
MAX_STREAM_RECONNECTS = 5

OUTPUT_CONTRACT = f"""\
Write these files to {OUTPUT_DIR}/ (UTF-8):
- districts.geojson: a GeoJSON FeatureCollection in EPSG:4326 (lon/lat), one feature per zone (Polygon or
  MultiPolygon), with properties "id" (the zone identifier, the same as in results.csv) and "name" (a readable name).
- results.csv: one row per zone, comma-separated, with columns "id", "eligible" (registered voters), "voters"
  (ballots cast), "valid" (valid votes), then one column per party holding its number of votes (absolute counts,
  not percentages). Use the party names as column headers, as the official results write them. If postal votes
  are counted separately, add them to the zones they belong to when the source tells how; otherwise leave them out
  and say so. Leave "eligible" / "voters" empty if the source does not give them.
- optionally, the social indicator, as either social.csv (columns "id", "value": one value per zone id) or
  social.geojson (polygons in EPSG:4326 with a numeric property "value", e.g. neighbourhoods; the server spreads it
  over the zones).
"""

SYSTEM_PROMPT = f"""\
You prepare data for a door-to-door canvassing tool used by local groups (\"groupes d'action\", GA) of La France
insoumise (LFI) abroad. A GA canvasses French citizens living in one city. To decide where to go first, the tool
scores the city's zones with: the vote share of the local party closest to LFI, abstention, and a social
indicator (poorer zones first). Your job: find the official open data for the GA's city and hand it over in a
fixed format.

What to find, for the city given in the request:
1. The map of the zones and the results of one election in those zones.
   - Prefer polling districts (Wahlbezirke, Wahlsprengel, bureaux de vote, stembureaus...). If the city publishes
     no map of them, use the finest level for which both a map and results exist (neighbourhoods, city districts,
     municipalities of the metropolitan area), and say which level you used.
   - Take the most recent election with results per zone for that city (national, regional or local), unless the
     request names one. Use the party-list / second vote when the election has two votes.
   - Use official sources (city or statistical office open data portals, electoral authorities, WFS services).
2. The party closest to LFI in that country (the \"reference party\"). Main criterion: membership of The Left
   group in the European Parliament or of the \"Now the People\" (Maintenant le peuple) alliance, then programme
   and alliances. Starting points to check, not to trust blindly: DE Die Linke; AT KPÖ; BE PTB-PVDA; NL SP;
   LU déi Lénk; ES Podemos (or the Sumar list it ran in); PT Bloco de Esquerda; SE Vänsterpartiet;
   FI Vasemmistoliitto; DK Enhedslisten; NO Rødt; IE People Before Profit (or Sinn Féin); GR Plefsi Eleftherias;
   CH PdA / solidaritéS / Ensemble à gauche; IT Movimento 5 Stelle or Alleanza Verdi Sinistra; UK no direct
   equivalent (left candidates); CA (Québec) Québec solidaire. If the party ran in a joint list, or several lists
   fit, give every matching results column. If it did not stand in the election you chose, prefer an election it
   stood in.
3. A social indicator per zone or per neighbourhood of the city, as recent as possible: share of residents on
   minimum social benefits, poverty rate, unemployment rate, or median income (say which; for an income, a higher
   value means richer). Skip it if nothing usable exists: the election data comes first.

{OUTPUT_CONTRACT}
Then call the submit_import tool. The server checks the files: at least {int(MIN_MATCHED_SHARE * 100)} % of the
zones must have results, the zones must lie around the GA's city, and the reference party columns must exist in
results.csv. If the check fails you get the reason: fix the files and call submit_import again. After a successful
submit_import, end with a one-sentence summary.

Rules:
- Work in Python in your container (pandas, geopandas/fiona/shapely/pyproj if useful; install what you need).
  Download files with Python or curl rather than reading big files through web_fetch.
- Call report_progress at each main step, with one short sentence in French for the GA (e.g. \"Carte des bureaux
  de vote de Vienne trouvée (1 495 bureaux)\").
- Never invent or estimate figures: only official data, converted. If you cannot find usable data, stop and
  explain in one or two French sentences what is missing, without calling submit_import.
- You have a limited budget: go for the official open data portals first, avoid repeating searches.
"""

CUSTOM_TOOLS = [
    {
        "type": "custom",
        "name": "report_progress",
        "description": "Show the GA a short progress step (one French sentence). Call it at each main step.",
        "input_schema": {
            "type": "object",
            "properties": {"message": {"type": "string", "description": "One short sentence in French."}},
            "required": ["message"],
        },
    },
    {
        "type": "custom",
        "name": "submit_import",
        "description": (
            f"Hand over the files written to {OUTPUT_DIR}/ (districts.geojson, results.csv, optional social.csv or "
            "social.geojson). The server checks and imports them; on failure it returns the reason to fix."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "election": {"type": "string", "description": "Election, in French, e.g. \"Législatives autrichiennes, 29/09/2024\"."},
                "level": {"type": "string", "description": "Kind of zones, in French, e.g. \"bureaux de vote\", \"quartiers\"."},
                "sources": {"type": "array", "items": {"type": "string"}, "description": "URLs of the official sources used."},
                "notes": {"type": "string", "description": "Anything the GA should know (postal votes left out...), in French."},
                "reference_party": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name shown to the GA, e.g. \"KPÖ\"."},
                        "columns": {"type": "array", "items": {"type": "string"}, "description": "results.csv columns of its votes."},
                        "reason": {"type": "string", "description": "Why this party, in one or two French sentences."},
                    },
                    "required": ["name", "columns", "reason"],
                },
                "social": {
                    "type": ["object", "null"],
                    "properties": {
                        "label": {"type": "string", "description": "French label, e.g. \"Taux de pauvreté (2023)\"."},
                        "higher_is_poorer": {"type": "boolean", "description": "false for an income."},
                        "source": {"type": "string"},
                    },
                    "required": ["label", "higher_is_poorer"],
                },
            },
            "required": ["election", "level", "sources", "reference_party"],
        },
    },
]


def agent_definition() -> dict:
    return {
        "name": "Import des zones (porte-à-porte)",
        "description": "Finds the electoral map, results and a social indicator of a city for the canvassing tool.",
        "model": {"id": MODEL, "effort": "high"},
        "system": SYSTEM_PROMPT,
        "tools": [
            {
                # bash, files and both web tools: the sites are not known in advance (each city has its portal).
                "type": "agent_toolset_20260401",
                "default_config": {"enabled": True, "permission_policy": {"type": "always_allow"}},
            },
            *CUSTOM_TOOLS,
        ],
    }


def environment_definition() -> dict:
    # Full egress (chosen by the site admins): the container holds no secret and no voter data.
    return {"name": "porte-a-porte-imports", "config": {"type": "cloud", "networking": {"type": "unrestricted"}}}


def make_client():
    import anthropic

    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY or None)


def ensure_agent(client=None) -> AiAgentConfig:
    """Create the agent and its environment, or update the agent to the current definition (one-time setup)."""
    client = client or make_client()
    config = AiAgentConfig.objects.filter(key="districts").first()
    if config is None:
        environment = client.beta.environments.create(**environment_definition())
        agent = client.beta.agents.create(**agent_definition())
        return AiAgentConfig.objects.create(
            key="districts", agent_id=agent.id, agent_version=agent.version, environment_id=environment.id
        )
    agent = client.beta.agents.update(config.agent_id, **agent_definition())
    config.agent_version = agent.version
    config.save(update_fields=["agent_version", "updated_at"])
    return config


def unavailable_reason() -> str | None:
    """Why the AI import cannot run (shown to the responsable), or None."""
    if not settings.ANTHROPIC_API_KEY:
        return "L'import par IA n'est pas configuré sur ce serveur (clé ANTHROPIC_API_KEY manquante)."
    if not AiAgentConfig.objects.filter(key="districts").exists():
        return "L'import par IA n'est pas encore installé : un·e admin du site doit lancer « make ai-agent »."
    return None


# --------------------------------------------------------------------------- the session


COUNTRY_NAMES = {
    "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "CH": "Switzerland", "CY": "Cyprus", "CZ": "Czechia",
    "DE": "Germany", "DK": "Denmark", "EE": "Estonia", "ES": "Spain", "FI": "Finland", "FR": "France",
    "GB": "United Kingdom", "GR": "Greece", "HR": "Croatia", "HU": "Hungary", "IE": "Ireland", "IT": "Italy",
    "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia", "MT": "Malta", "NL": "Netherlands", "NO": "Norway",
    "PL": "Poland", "PT": "Portugal", "RO": "Romania", "SE": "Sweden", "SI": "Slovenia", "SK": "Slovakia",
    "CA": "Canada", "US": "United States",
}


def request_text(job: DistrictImport) -> str:
    """The request sent to the agent: where, and what to find (the details and the file format are in its
    system prompt). Only the city, never data about people."""
    organization = job.organization
    country = COUNTRY_NAMES.get(organization.country_code, organization.country_code)
    city = organization.city or organization.name
    lines = [
        "Build the canvassing zones of this local group (GA).",
        "",
        f"- City: {city}",
        f"- Country: {country} (ISO code {organization.country_code})",
        f"- City centre: lat {organization.city_lat}, lon {organization.city_lon}",
        f"- Area: within {organization.radius_km} km of the centre (the city itself first; suburbs only if they come "
        "in the same datasets)",
        "",
        "Data to retrieve, from official sources (electoral authority, city or national statistics, open data portals):",
        f"1. Zone outlines: the polling districts of {city} (or, if no map of them is published, the smallest "
        "official areas that election results are published for: neighbourhoods, wards, municipal districts).",
        "2. Results of the most recent election with results per zone: registered voters, voters, valid votes and "
        "the votes of every party/list.",
        f"3. A social indicator per zone (or per neighbourhood overlapping the zones) for {city}: share of low-income "
        "households, poverty or unemployment rate, or median income; skip it if none is published.",
        f"4. The party standing in for La France insoumise in {country} (radical left, The Left group in the European "
        "Parliament or its national equivalent), with the result columns to sum for it.",
        "",
        "Write the normalized files described in your instructions, then call submit_import.",
    ]
    if job.hint.strip():
        lines += ["", f"Request of the GA (in French, it overrides the defaults above): {job.hint.strip()}"]
    return "\n".join(lines)


def start(job: DistrictImport) -> None:
    job.status = DistrictImport.ImportStatus.RUNNING
    job.message = ""
    job.save(update_fields=["status", "message"])
    threading.Thread(target=_run, args=(job.id,), daemon=True).start()


def _run(job_id: int) -> None:
    close_old_connections()
    job = DistrictImport.objects.select_related("organization").get(pk=job_id)
    try:
        ImportSession(job, make_client()).run()
    except Exception as exc:  # noqa: BLE001 - reported to the user, details in the logs
        log.exception("AI district import %s failed", job_id)
        job.status, job.message = DistrictImport.ImportStatus.FAILED, f"Erreur inattendue : {exc}"
    if job.status == DistrictImport.ImportStatus.RUNNING:
        job.status = DistrictImport.ImportStatus.FAILED
        job.message = job.message or "L'agent s'est arrêté sans importer de zones."
    job.finished_at = timezone.now()
    job.save()
    close_old_connections()


@dataclass
class ImportSession:
    job: DistrictImport
    client: object
    imported: bool = False
    last_message: str = ""
    seen: set = field(default_factory=set)
    interrupted: bool = False

    def run(self) -> None:
        config = AiAgentConfig.objects.get(key="districts")
        session = self.client.beta.sessions.create(
            agent={"type": "agent", "id": config.agent_id, "version": config.agent_version},
            environment_id=config.environment_id,
            title=f"Zones – {self.job.organization.name}"[:200],
            metadata={"organization": self.job.organization.code, "import_id": str(self.job.id)},
            # Minor units (cents), as an integer string: "200" = $2.00.
            budget={"type": "limit", "max_list_cost": {"amount": str(round(settings.AI_IMPORT_BUDGET_USD * 100)), "currency": "USD"}},
        )
        self.job.ai_session_id = session.id
        self.job.save(update_fields=["ai_session_id"])
        self.deadline = time.monotonic() + SESSION_TIMEOUT_S

        for attempt in range(MAX_STREAM_RECONNECTS + 1):
            if attempt:
                time.sleep(min(2**attempt, 30))
            with self.client.beta.sessions.events.stream(session_id=session.id) as stream:
                if attempt == 0:  # stream first, then send
                    self.client.beta.sessions.events.send(
                        session_id=session.id,
                        events=[{"type": "user.message", "content": [{"type": "text", "text": request_text(self.job)}]}],
                    )
                else:  # no replay on SSE: catch up from the history (lossless reconnect)
                    for event in self.client.beta.sessions.events.list(session_id=session.id):
                        if self.handle(session.id, event):
                            return
                for event in stream:
                    if self.handle(session.id, event):
                        return
            log.warning("AI import %s: stream closed early, reconnecting", self.job.id)
        self.fail("La connexion avec l'agent a été perdue.")

    def handle(self, session_id: str, event) -> bool:
        """Process one event (once); True when the session is over."""
        new = event.id not in self.seen
        self.seen.add(event.id)
        kind = event.type
        if new and kind == "agent.message":
            text = "".join(b.text for b in event.content if getattr(b, "type", "") == "text").strip()
            if text:
                self.last_message = text
        elif new and kind == "agent.custom_tool_use":
            ok, text = self.run_tool(session_id, event.name, event.input or {})
            self.client.beta.sessions.events.send(
                session_id=session_id,
                events=[{
                    "type": "user.custom_tool_result", "custom_tool_use_id": event.id,
                    "content": [{"type": "text", "text": text}], "is_error": not ok,
                }],
            )
        elif new and kind == "session.usage":
            usage = getattr(event, "usage", None) or event
            self.record_cost(getattr(usage, "list_cost", None))
        elif kind == "session.status_terminated":
            return self.finish("La session de l'agent s'est arrêtée.")
        elif kind == "session.status_idle":
            reason = event.stop_reason.type
            if reason == "requires_action":
                return False
            if reason == "budget_reached":
                return self.finish(f"Budget de {settings.AI_IMPORT_BUDGET_USD} $ atteint avant la fin de l'import.")
            if reason == "retries_exhausted":
                return self.finish("L'agent a rencontré une erreur répétée.")
            return self.finish(self.last_message or "L'agent s'est arrêté sans importer de zones.")
        if not self.interrupted and time.monotonic() > self.deadline:
            self.interrupted = True
            self.client.beta.sessions.events.send(session_id=session_id, events=[{"type": "user.interrupt"}])
            self.fail("L'import a pris trop de temps (40 min) et a été arrêté.")
        return False

    def finish(self, failure: str) -> bool:
        self.refresh_cost()
        if self.imported:
            self.job.status = DistrictImport.ImportStatus.DONE
            self.job.message = ""
        elif self.job.status == DistrictImport.ImportStatus.RUNNING:
            self.fail(failure)
        return True

    def fail(self, message: str) -> None:
        self.job.status = DistrictImport.ImportStatus.FAILED
        self.job.message = message[:2000]

    def record_cost(self, list_cost) -> None:
        amount = getattr(list_cost, "amount", None) if list_cost is not None else None
        if amount is not None:  # cents, as an integer string
            self.job.report = {**(self.job.report or {}), "cost_usd": round(int(amount) / 100, 2)}

    def refresh_cost(self) -> None:
        try:
            session = self.client.beta.sessions.retrieve(session_id=self.job.ai_session_id)
            self.record_cost(getattr(getattr(session, "usage", None), "list_cost", None))
        except Exception:  # noqa: BLE001 - the cost is informative only
            log.info("AI import %s: could not read the session cost", self.job.id)

    # ----------------------------------------------------------------------- custom tools

    def run_tool(self, session_id: str, name: str, data: dict) -> tuple[bool, str]:
        if name == "report_progress":
            message = str(data.get("message") or "").strip()[:300]
            if message:
                self.job.progress_log = [*(self.job.progress_log or []), {"at": timezone.now().isoformat(), "message": message}]
                self.job.save(update_fields=["progress_log"])
            return True, "ok"
        if name == "submit_import":
            if self.imported:
                return False, "The zones are already imported: end with a one-sentence summary."
            try:
                summary = submit(self.job, download_outputs(self.client, session_id), data)
            except district_service.DistrictImportError as exc:
                return False, str(exc)
            self.imported = True
            return True, summary
        return False, f"Unknown tool {name}."


def download_outputs(client, session_id: str, attempts: int = 5) -> dict[str, bytes]:
    """Files the agent wrote to the outputs folder (name → bytes). They appear after a short indexing lag."""
    wanted = {"districts.geojson", "results.csv", "social.csv", "social.geojson"}
    for attempt in range(attempts):
        files = {}
        for f in client.beta.files.list(scope_id=session_id, betas=["managed-agents-2026-04-01"]):
            name = f.filename.rsplit("/", 1)[-1]
            if name not in wanted:
                continue
            if (f.size_bytes or 0) > MAX_FILE_BYTES:
                raise district_service.DistrictImportError(f"{name} is larger than 100 MB: simplify the geometries.")
            files[name] = f  # the latest one wins if a file was written twice
        if {"districts.geojson", "results.csv"} <= set(files):
            return {name: client.files.download(f.id).read() for name, f in files.items()}
        time.sleep(1 + attempt)
    raise district_service.DistrictImportError(
        f"districts.geojson and results.csv not found in {OUTPUT_DIR}/: write them there, then call submit_import again."
    )


def _km(lat1, lon1, lat2, lon2) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def check(organization, rows, report: dict, data: dict) -> list[str]:
    """Reasons to send the files back to the agent (empty: they can be imported)."""
    problems = []
    if len(rows) < 2:
        problems.append("districts.geojson has fewer than 2 zones.")
    matched = len(rows) - report["n_without_results"]
    if rows and matched / len(rows) < MIN_MATCHED_SHARE:
        problems.append(
            f"Only {matched} of {len(rows)} zones have results in results.csv (ids not matching?). "
            f"Zone ids without results, e.g.: {', '.join(report['examples_without_results'][:5])}."
        )
    columns = (data.get("reference_party") or {}).get("columns") or []
    missing = [c for c in columns if c not in report["party_columns"]]
    if not columns:
        problems.append("reference_party.columns is empty.")
    elif missing:
        problems.append(f"Reference party columns not in results.csv: {', '.join(missing)}. Columns: {', '.join(report['party_columns'])}.")
    if organization.city_lat is not None and organization.city_lon is not None and rows:
        limit = organization.radius_km + DISTANCE_MARGIN_KM
        near = [r for r in rows if _km(organization.city_lat, organization.city_lon, r.geometry.centroid.y, r.geometry.centroid.x) <= limit]
        if not near:
            first = rows[0].geometry.centroid
            problems.append(
                f"No zone lies within {limit} km of the GA's city ({organization.city_lat}, {organization.city_lon}); "
                f"e.g. zone {rows[0].code} is at ({first.y:.4f}, {first.x:.4f}). Wrong city, or coordinates not in "
                "EPSG:4326 lon/lat?"
            )
    return problems


def submit(job: DistrictImport, files: dict[str, bytes], data: dict) -> str:
    """Check the agent's files and import them. Raises DistrictImportError with the reason to fix."""
    organization = job.organization
    rows, report = district_service.rows_from_normalized(files["districts.geojson"], files["results.csv"], files.get("social.csv"))
    problems = check(organization, rows, report, data)
    if problems:
        raise district_service.DistrictImportError("Import refused:\n- " + "\n- ".join(problems))

    party = data["reference_party"]
    social = data.get("social") or None
    has_social = bool(social) and ("social.csv" in files or "social.geojson" in files)
    for row in rows:
        row.reference_votes = sum(row.parties.get(c) or 0 for c in party["columns"]) if any(c in row.parties for c in party["columns"]) else None
    from ..models import SocialArea

    SocialArea.objects.filter(organization=organization).delete()
    if has_social and "social.geojson" in files and "social.csv" not in files:
        district_service.social_areas_from_geojson(organization, files["social.geojson"], f"ai:{organization.id}")
    settings_ = district_service.ImportSettings(
        reference_party=str(party.get("name") or party["columns"][0]),
        reference_party_columns=list(party["columns"]),
        social_label=str(social.get("label") or "Indicateur social") if has_social else "Bas revenus",
        social_higher_is_poorer=bool(social.get("higher_is_poorer", True)) if has_social else True,
    )
    election = str(data.get("election") or "")[:128]
    saved = district_service.save_districts(organization, rows, election, settings_)
    job.report = {
        **(job.report or {}),
        **saved,
        "n_without_results": report["n_without_results"],
        "election": election,
        "level": str(data.get("level") or ""),
        # Shown as links: web addresses only (the agent's output is not trusted).
        "sources": [str(u)[:500] for u in (data.get("sources") or []) if str(u).startswith(("https://", "http://"))][:20],
        "notes": str(data.get("notes") or ""),
        "reference_party": settings_.reference_party,
        "reference_party_columns": settings_.reference_party_columns,
        "reference_reason": str(party.get("reason") or ""),
        "social_label": settings_.social_label if has_social else None,
        "social_source": str(social.get("source") or "") if has_social else "",
    }
    job.save(update_fields=["report"])
    return f"Imported {saved['n_districts']} zones ({saved['n_with_social']} with the social indicator)."
