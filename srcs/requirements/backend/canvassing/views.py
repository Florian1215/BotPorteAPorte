from datetime import timedelta

from django.contrib.gis.geos import Polygon
from django.db.models import BooleanField, Count, Q
from django.db.models.expressions import RawSQL
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Role, User
from accounts.permissions import IsCanvasser, IsSiteAdmin

from .models import SUCCESS_RESULTS, Address, District, DistrictImport, Election, Status, Tour, Visit, VisitResult
from .serializers import (
    CreateTourSerializer,
    NearbySerializer,
    ResultSerializer,
    StopsResultSerializer,
    FreeTourPreviewSerializer,
    address_to_dict,
    short_name,
    district_to_dict,
    with_outline,
    tour_to_dict,
)
from .services import districts as district_service
from .services import elections as election_service
from .services import scoring
from .services import tours as tour_service
from .services.geo import bbox_around

NEARBY_LIMIT = 3000
TOP_AREAS = 10


def error(message: str, status_code: int = status.HTTP_400_BAD_REQUEST, **extra) -> Response:
    return Response({"detail": message, **extra}, status=status_code)


class CanvasserView(APIView):
    permission_classes = [IsCanvasser]

    def handle_exception(self, exc):
        if isinstance(exc, tour_service.TourError):
            return error(exc.message, exc.status_code, **exc.extra)
        return super().handle_exception(exc)


# --------------------------------------------------------------------------- tours


class TourListView(CanvasserView):
    def post(self, request):
        """Prepare a tour (draft): select and order addresses, compute the route."""
        tour_service.expire_stale_tours()
        serializer = CreateTourSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data["kind"] == Tour.Kind.FREE:
            tour = tour_service.prepare_free_tour(request.user, data["start"], data["end"], data["radius_km"])
        else:
            area = get_object_or_404(District, pk=data["area_id"], organization_id=request.user.organization_id)
            tour = tour_service.prepare_predefined_tour(request.user, area, data["start"])
        return Response(tour_to_dict(tour), status=status.HTTP_201_CREATED)


class FreeTourPreviewView(CanvasserView):
    def post(self, request):
        """Corridor shown on the map while choosing the radius of a free tour."""
        serializer = FreeTourPreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return Response(tour_service.preview_free_tour(request.user, data["start"], data["end"], data["radius_km"]))


class CurrentTourView(CanvasserView):
    def get(self, request):
        tour_service.expire_stale_tours()
        tour = tour_service.current_tour(request.user)
        return Response(tour_to_dict(tour) if tour else None)


class TourMixin:
    def get_tour(self, request, pk) -> Tour:
        return get_object_or_404(Tour.objects.select_related("area"), pk=pk, user=request.user)


class TourDetailView(TourMixin, CanvasserView):
    def get(self, request, pk):
        return Response(tour_to_dict(self.get_tour(request, pk)))

    def delete(self, request, pk):
        """Cancel a draft, or a started tour where no door was knocked yet (nothing is recorded)."""
        tour = self.get_tour(request, pk)
        if tour.status == Tour.TourStatus.COMPLETED:
            return error("Cette tournée est déjà terminée.", status.HTTP_409_CONFLICT)
        tour_service.discard_tour(tour)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TourStartView(TourMixin, CanvasserView):
    def post(self, request, pk):
        tour = tour_service.start_tour(self.get_tour(request, pk))
        return Response(tour_to_dict(tour))


class TourFinishView(TourMixin, CanvasserView):
    def post(self, request, pk):
        tour = tour_service.finish_tour(self.get_tour(request, pk))
        return Response(tour_to_dict(tour))


class StopResultView(TourMixin, CanvasserView):
    def post(self, request, pk, stop_id):
        tour = self.get_tour(request, pk)
        stop = get_object_or_404(tour.stops.select_related("address"), pk=stop_id)
        serializer = ResultSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tour_service.record_stop_result(
            tour, stop, serializer.validated_data["result"], serializer.validated_data["absent_detail"]
        )
        return Response(tour_to_dict(tour))


class StopsResultView(TourMixin, CanvasserView):
    def post(self, request, pk):
        """Same feedback for several people at once (everyone selected at one address)."""
        tour = self.get_tour(request, pk)
        serializer = StopsResultSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = set(serializer.validated_data["stop_ids"])
        stops = list(tour.stops.select_related("address").filter(id__in=ids))
        if len(stops) != len(ids):
            return error("Certaines personnes ne font pas partie de cette tournée.", status.HTTP_404_NOT_FOUND)
        tour_service.record_stop_results(
            tour, stops, serializer.validated_data["result"], serializer.validated_data["absent_detail"]
        )
        return Response(tour_to_dict(tour))

    def delete(self, request, pk):
        """Remove the feedback of these people (tapped again on the selected one): to visit again."""
        tour = self.get_tour(request, pk)
        ids = {int(i) for i in request.query_params.get("stop_ids", "").split(",") if i.strip().isdigit()}
        stops = list(tour.stops.filter(id__in=ids))
        if not ids or len(stops) != len(ids):
            return error("Certaines personnes ne font pas partie de cette tournée.", status.HTTP_404_NOT_FOUND)
        tour_service.clear_stop_results(tour, stops)
        return Response(tour_to_dict(tour))


# --------------------------------------------------------------------------- areas & addresses


class AreaListView(CanvasserView):
    """Best polling districts of the user's organization (by score) that still have addresses to visit."""

    def get(self, request):
        organization_id = request.user.organization_id
        progress = district_service.progress(organization_id)
        candidates = [pk for pk, p in progress.items() if p["to_visit"] > 0]
        districts = list(with_outline(District.objects.filter(id__in=candidates)).order_by("-score")[:TOP_AREAS])
        # ?zone=<id>: a district picked on the zones map (responsables), even outside the top list.
        zone = request.query_params.get("zone")
        if zone and zone.isdigit() and int(zone) in candidates and all(d.id != int(zone) for d in districts):
            districts.insert(0, with_outline(District.objects.filter(id=int(zone))).get())
        return Response(
            [
                district_to_dict(d, n_to_visit=progress[d.id]["to_visit"], done_pct=progress[d.id]["done_pct"])
                for d in districts
            ]
        )


class DistrictManagerView(CanvasserView):
    """Polling districts of the current organization: map, details, import, score weights (responsables)."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not (request.user.can_manage_organization or request.user.is_site_admin):
            raise PermissionDenied("Réservé aux responsables de l'organisation.")
        if request.user.organization_id is None:
            raise PermissionDenied("Choisis d'abord une organisation.")

    @property
    def organization(self):
        return self.request.user.organization



def progress_election(election: Election | None) -> dict:
    """The zones' progress is the one of the current election (chosen by the site admins)."""
    return {"progress_election": election.name if election else None}


class ManageDistrictListView(DistrictManagerView):
    def get(self, request):
        organization = self.organization
        election = Election.current()
        progress = district_service.progress(organization.id, election=election)
        districts = with_outline(District.objects.filter(organization=organization))
        first = District.objects.filter(organization=organization).only("election").first()
        return Response(
            {
                "election": first.election if first else "",
                "districts": [
                    district_to_dict(d, done_pct=progress.get(d.id, {}).get("done_pct", 0)) for d in districts
                ],
                "weights": scoring.weights_of(organization),
                "criteria": [{"key": c.key, "label": c.label} for c in scoring.CRITERIA],
                "import": import_to_dict(last_import(organization)),
                "presets": [{"key": k, **v} for k, v in district_service.PRESETS.items()],
                **progress_election(election),
            }
        )


class ManageDistrictDetailView(DistrictManagerView):
    def get(self, request, pk):
        district = get_object_or_404(District, pk=pk, organization_id=request.user.organization_id)
        election = Election.current()
        progress = district_service.progress(district.organization_id, [district.id], election=election).get(
            district.id, district_service.EMPTY_PROGRESS
        )
        return Response({**district_detail(district, progress), **progress_election(election)})


def district_detail(d: District, progress: dict) -> dict:
    def pct(num, den):
        return round(100 * num / den, 1) if num is not None and den else None

    parties = sorted(d.parties.items(), key=lambda kv: -kv[1])
    density = d.population / d.area_km2 if d.population is not None and d.area_km2 else None
    return {
        **district_to_dict(d, done_pct=progress["done_pct"]),
        "election": d.election,
        "eligible": d.eligible,
        "voters": d.voters,
        "valid": d.valid,
        "linke": d.linke,
        "linke_pct": pct(d.linke, d.valid),
        "turnout_pct": pct(d.voters, d.eligible),
        "parties": [{"name": name, "votes": votes, "pct": pct(votes, d.valid)} for name, votes in parties[:6]],
        "population": d.population,
        "area_km2": round(d.area_km2, 3),
        "density": round(density) if density is not None else None,
        "share_18_29": d.share_18_29,
        "share_65_plus": d.share_65_plus,
        "share_foreign": d.share_foreign,
        "rent_m2": d.rent_m2,
        "low_income": d.low_income,
        "score_parts": [
            {"key": c.key, "label": c.label, **(d.score_parts.get(c.key) or {"value": None, "rank": None, "weight": 0})}
            for c in scoring.CRITERIA
        ],
        "progress": progress,
        "ages": district_service.age_pyramid(d),
    }


STALE_IMPORT = timedelta(minutes=30)


def last_import(organization) -> DistrictImport | None:
    job = DistrictImport.objects.filter(organization=organization).defer("geometry_file", "results_file").first()
    if job and job.status == DistrictImport.ImportStatus.RUNNING and timezone.now() - job.created_at > STALE_IMPORT:
        job.status = DistrictImport.ImportStatus.FAILED
        job.message = "L'import a été interrompu (redémarrage du serveur ?). Relance-le."
        DistrictImport.objects.filter(pk=job.pk).update(status=job.status, message=job.message)
    return job


def import_to_dict(job: DistrictImport | None) -> dict | None:
    if job is None:
        return None
    return {
        "id": job.id,
        "source": job.source,
        "status": job.status,
        "message": job.message,
        "report": job.report,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }


class DistrictImportView(DistrictManagerView):
    """GET: the last import (polled while it runs). POST {preset}: one-click import of a city."""

    def get(self, request):
        return Response(import_to_dict(last_import(self.organization)))

    def post(self, request):
        preset = request.data.get("preset")
        if preset not in district_service.PRESETS:
            return error("Import inconnu.")
        job = self.new_job(preset)
        district_service.start_import(job)
        return Response(import_to_dict(job), status=status.HTTP_202_ACCEPTED)

    def new_job(self, source: str, **fields) -> DistrictImport:
        running = last_import(self.organization)
        if running and running.status == DistrictImport.ImportStatus.RUNNING:
            raise tour_service.TourError("Un import est déjà en cours.", status.HTTP_409_CONFLICT)
        return DistrictImport.objects.create(organization=self.organization, user=self.request.user, source=source, **fields)


class DistrictImportInspectView(DistrictImportView):
    """Custom import, step 1: upload the two files (or pick another sheet) → columns and preview."""

    parser_classes = [MultiPartParser, JSONParser]

    def post(self, request):
        sheet = request.data.get("sheet") or None
        job_id = request.data.get("import_id")
        if job_id:
            job = get_object_or_404(
                DistrictImport, pk=job_id, organization=self.organization, status=DistrictImport.ImportStatus.PENDING
            )
        else:
            geometry, results = request.FILES.get("geometry"), request.FILES.get("results")
            if geometry is None or results is None:
                return error("Envoie le fichier des bureaux (GeoJSON) et le fichier des résultats (CSV ou Excel).")
            job = self.new_job(
                "custom",
                geometry_file=geometry.read(),
                results_file=results.read(),
                results_filename=results.name,
            )
        try:
            info = district_service.inspect_files(bytes(job.geometry_file), bytes(job.results_file), job.results_filename, sheet)
        except district_service.DistrictImportError as exc:
            job.delete()
            return error(str(exc))
        return Response({"import_id": job.id, **info})


class DistrictImportStartView(DistrictManagerView):
    """Custom import, step 2: the chosen columns → run the import."""

    def post(self, request, pk):
        job = get_object_or_404(
            DistrictImport, pk=pk, organization=self.organization, status=DistrictImport.ImportStatus.PENDING
        )
        mapping = request.data if isinstance(request.data, dict) else {}
        district_service.start_import(job, dict(mapping))
        return Response(import_to_dict(job), status=status.HTTP_202_ACCEPTED)


class ScoreWeightsView(DistrictManagerView):
    def get(self, request):
        return Response(scoring.weights_of(self.organization))

    def put(self, request):
        try:
            weights = scoring.clean_weights(request.data if isinstance(request.data, dict) else {})
        except ValueError as exc:
            return error(str(exc))
        organization = self.organization
        organization.score_weights = weights
        organization.save(update_fields=["score_weights"])
        scoring.rescore_organization(organization)
        return Response(weights)


class NearbyAddressesView(CanvasserView):
    def get(self, request):
        """Addresses still to visit around a point (the bot's /adresses_alentours)."""
        serializer = NearbySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        lat, lon, radius_km = (serializer.validated_data[k] for k in ("lat", "lon", "radius_km"))
        bbox = Polygon.from_bbox(bbox_around([(lat, lon)], radius_km))
        qs = (
            Address.objects.filter(organization_id=request.user.organization_id, status=Status.TO_VISIT, location__within=bbox)
            .alias(
                near=RawSQL(
                    "ST_DWithin(location::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)",
                    (lon, lat, radius_km * 1000),
                    output_field=BooleanField(),
                )
            )
            .filter(near=True)
        )
        total = qs.count()
        addresses = [address_to_dict(a, with_names=False) for a in qs[:NEARBY_LIMIT]]
        return Response({"total": total, "truncated": total > len(addresses), "addresses": addresses})


# --------------------------------------------------------------------------- stats


def ranked_members(queryset):
    """Members with their number of doors knocked (= feedbacks given) and successes, best first."""
    return queryset.annotate(
        doors=Count("visits"),
        successes=Count("visits", filter=Q(visits__result__in=[r.value for r in SUCCESS_RESULTS])),
    ).order_by("-doors", "-successes", "first_name", "email")


def organization_members_all():
    """Approved members of every organization (site admins excluded)."""
    return User.objects.filter(organization__isnull=False, is_active=True, is_approved=True, is_superuser=False).exclude(
        role=Role.ADMIN
    )


def organization_members(organization_id):
    """Approved members of an organization (site admins only visit organizations: not ranked)."""
    return User.objects.filter(organization_id=organization_id, is_active=True, is_approved=True, is_superuser=False).exclude(
        role=Role.ADMIN
    )


class MyStatsView(CanvasserView):
    def get(self, request):
        counts = dict(
            Visit.objects.filter(user=request.user).values_list("result").annotate(n=Count("id")).order_by()
        )
        by_result = {r.value: counts.get(r.value, 0) for r in VisitResult}
        total_visits = sum(by_result.values())

        # Rank in the organization by doors knocked (ties share the same rank).
        doors = list(
            ranked_members(organization_members(request.user.organization_id).exclude(pk=request.user.pk)).values_list(
                "doors", flat=True
            )
        )
        rank = 1 + sum(1 for n in doors if n > total_visits)
        return Response(
            {
                "total_success": sum(by_result[r.value] for r in SUCCESS_RESULTS),
                "total_visits": total_visits,
                "by_result": by_result,
                "tours_completed": Tour.objects.filter(user=request.user, status=Tour.TourStatus.COMPLETED).count(),
                "rank": rank,
                "ranked_members": len(doors) + 1,
            }
        )


LEADERBOARD_SIZE = 100


def with_ranks(rows: list[dict]) -> list[dict]:
    """Competition ranking on "doors" (rows already sorted best first): ties share the same rank."""
    for i, row in enumerate(rows):
        row["rank"] = rows[i - 1]["rank"] if i and rows[i - 1]["doors"] == row["doors"] else i + 1
    return rows


def top_and_me(rows: list[dict], is_me) -> list[dict]:
    """The first LEADERBOARD_SIZE rows, plus the user's own row if they are further down."""
    top = rows[:LEADERBOARD_SIZE]
    if not any(is_me(r) for r in top):
        top += [r for r in rows[LEADERBOARD_SIZE:] if is_me(r)]
    return top


class LeaderboardView(CanvasserView):
    """Doors knocked: `scope=group` (my organization), `all` (every militant), `organizations` (organizations)."""

    def get(self, request):
        user = request.user
        scope = request.query_params.get("scope", "group")

        if scope == "organizations":
            from accounts.models import Organization

            orgs = Organization.objects.annotate(doors=Count("addresses__visits")).order_by("-doors", "name")
            members = dict(
                organization_members_all().values_list("organization_id").annotate(n=Count("id")).order_by()
            )
            rows = with_ranks(
                [
                    {
                        "id": o.id,
                        "name": o.name,
                        "city": o.city,
                        "logo_url": o.logo_url,
                        "members": members.get(o.id, 0),
                        "doors": o.doors,
                        "is_me": o.id == user.organization_id,
                    }
                    for o in orgs
                ]
            )
            return Response({"scope": scope, "rows": top_and_me(rows, lambda r: r["is_me"])})

        members = organization_members_all() if scope == "all" else organization_members(user.organization_id)
        rows = with_ranks(
            [
                {
                    "id": m.id,
                    "name": short_name(m),
                    "organization": m.organization.name,
                    "doors": m.doors,
                    "is_me": m.id == user.id,
                }
                for m in ranked_members(members.select_related("organization"))
            ]
        )
        return Response({"scope": "all" if scope == "all" else "group", "rows": top_and_me(rows, lambda r: r["is_me"])})


class OrganizationOverviewView(CanvasserView):
    def get(self, request):
        """Progress of the whole organization (shown on the home page)."""
        counts = dict(
            Address.objects.filter(organization_id=request.user.organization_id)
            .values_list("status")
            .annotate(n=Count("id"))
            .order_by()
        )
        # Every door knocked by anyone in the organization (one feedback = one door, "absent" included).
        visits = dict(
            Visit.objects.filter(address__organization_id=request.user.organization_id)
            .values_list("result")
            .annotate(n=Count("id"))
            .order_by()
        )
        return Response(
            {
                "total": sum(counts.values()),
                "by_status": {s.name.lower(): counts.get(s.value, 0) for s in Status},
                "doors_knocked": sum(visits.values()),
                "doors_by_result": {r.value: visits.get(r.value, 0) for r in VisitResult},
            }
        )


# --------------------------------------------------------------------------- site administration (elections)


def election_to_dict(election: Election, n_visits: int = 0) -> dict:
    return {
        "id": election.id,
        "name": election.name,
        "is_current": election.is_current,
        "created_at": election.created_at,
        "started_at": election.started_at,
        "n_visits": n_visits,
    }


class SiteElectionListView(APIView):
    """Elections of the whole site (administrateur·rices du site): list, create."""

    permission_classes = [IsSiteAdmin]

    def get(self, request):
        elections = Election.objects.annotate(n_visits=Count("visits"))
        return Response(
            {
                "elections": [election_to_dict(e, e.n_visits) for e in elections],
                # Addresses that would go back to "to visit" if another election became current.
                "to_reset": election_service.addresses_to_reset().count(),
            }
        )

    def post(self, request):
        name = " ".join(str(request.data.get("name") or "").split())[:128]
        if not name:
            return error("Donne un nom à l'élection (ex. « Élection présidentielle 2027 »).")
        if Election.objects.filter(name__iexact=name).exists():
            return error("Une élection porte déjà ce nom.")
        return Response(election_to_dict(Election.objects.create(name=name)), status=status.HTTP_201_CREATED)


class SiteElectionDetailView(APIView):
    permission_classes = [IsSiteAdmin]

    def patch(self, request, pk):
        election = get_object_or_404(Election, pk=pk)
        name = " ".join(str(request.data.get("name") or "").split())[:128]
        if not name:
            return error("Donne un nom à l'élection.")
        if Election.objects.filter(name__iexact=name).exclude(pk=pk).exists():
            return error("Une élection porte déjà ce nom.")
        election.name = name
        election.save(update_fields=["name"])
        return Response(election_to_dict(election, election.visits.count()))

    def delete(self, request, pk):
        election = get_object_or_404(Election, pk=pk)
        if election.is_current:
            return error("C'est l'élection en cours : choisis-en une autre avant de la supprimer.")
        if election.visits.exists():
            return error("Des portes ont déjà été frappées pour cette élection : elle ne peut plus être supprimée.")
        election.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SiteElectionActivateView(APIView):
    """Make an election the current one for the whole site (starts the canvassing over)."""

    permission_classes = [IsSiteAdmin]

    def post(self, request, pk):
        election = get_object_or_404(Election, pk=pk)
        reset = election_service.set_current(election)
        return Response({**election_to_dict(election, election.visits.count()), "reset": reset})
