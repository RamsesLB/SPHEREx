import logging

from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import gettext as _

from .forms import CoordinateForm
from .models import SpherexImage
from . import services

logger = logging.getLogger(__name__)


def index(request):
    has_query = "ra" in request.GET or "dec" in request.GET
    form = CoordinateForm(request.GET if has_query else None)
    frames = []
    error = None
    info = None
    searched = False

    if has_query:
        searched = True
        if form.is_valid():
            try:
                images = services.search_and_store(
                    form.cleaned_data["ra"],
                    form.cleaned_data["dec"],
                    collection=form.cleaned_data["collection"],
                )
            except services.SearchError as exc:
                error = str(exc)
            except Exception:
                logger.exception("Unexpected IRSA search error")
                error = _("IRSA could not be queried. Try again in a few seconds.")
            else:
                frames = [_frame_payload(image) for image in images]
                if not frames:
                    info = _("IRSA returned no SPHEREx images for this position in %(collection)s.") % {
                        "collection": form.cleaned_data["collection"],
                    }
                elif len(frames) >= services.MAX_RESULTS:
                    info = _("Showing the %(count)s most recent observations.") % {
                        "count": services.MAX_RESULTS,
                    }
        else:
            error = _("Check the coordinates and the cutout size.")

    target_ra, target_dec = _map_target(form)
    query = _submitted_query(form) if searched and form.is_valid() else None

    return render(request, "search/index.html", {
        "form": form,
        "frames": frames,
        "error": error,
        "info": info,
        "searched": searched,
        "target_ra": target_ra,
        "target_dec": target_dec,
        "map_fov": _map_fov(form),
        "query": query,
        "messages_json": _js_messages(),
    })


def cutout(request, pk):
    image = get_object_or_404(SpherexImage, pk=pk)
    try:
        fov_arcsec = services.fov_to_arcsec(
            request.GET.get("fov"),
            request.GET.get("unit", "arcsec"),
        )
        path = services.cached_cutout(
            image,
            request.GET.get("ra", ""),
            request.GET.get("dec", ""),
            fov_arcsec,
        )
    except services.SearchError as exc:
        return HttpResponse(str(exc), status=422, content_type="text/plain; charset=utf-8")
    except Exception:
        logger.exception("Could not cut out image %s", pk)
        return HttpResponse(
            _("The cutout could not be generated."),
            status=502,
            content_type="text/plain; charset=utf-8",
        )
    try:
        return FileResponse(path.open("rb"), content_type="image/png")
    except Exception:
        logger.exception("Could not read cutout file for image %s", pk)
        return HttpResponse(
            _("The cutout could not be generated."),
            status=502,
            content_type="text/plain; charset=utf-8",
        )


def health_check(request):
    return JsonResponse({"status": "ok", "app": "SPHEREx NASA Hackaton live"})


def _frame_payload(image):
    return {
        "id": image.pk,
        "obs_id": image.obs_id,
        "detector": image.detector,
        "date": timezone.localtime(image.observation_date).strftime("%Y-%m-%d %H:%M UTC"),
        "wavelength": services.wavelength_label(image.em_min, image.em_max),
        "collection": image.collection,
    }


def _map_target(form):
    ra = form["ra"].value() or form.fields["ra"].initial
    dec = form["dec"].value() or form.fields["dec"].initial
    try:
        coord = services.parse_coordinates(ra, dec)
    except services.SearchError:
        coord = services.parse_coordinates("08h55m10.831s", "-7d14m42.53s")
    return f"{coord.ra.deg:.6f}", f"{coord.dec.deg:.6f}"


def _map_fov(form):
    fov = form["fov"].value() or form.fields["fov"].initial
    unit = form["unit"].value() or form.fields["unit"].initial
    try:
        arcsec = services.fov_to_arcsec(fov, unit)
    except services.SearchError:
        arcsec = 60
    return f"{max(arcsec / 3600 * 5, 0.05):.5f}"


def _submitted_query(form):
    data = form.cleaned_data
    return {
        "ra": data["ra"],
        "dec": data["dec"],
        "fov": data["fov"],
        "unit": data["unit"],
        "collection": data["collection"],
    }


def _js_messages():
    return {
        "searchFirst": _("Search a sky position to play the sequence."),
        "noDetector": _("No observations for this detector."),
        "cutoutFailed": _("The cutout could not be generated."),
        "cutoutLoadFailed": _("The cutout could not be loaded."),
        "inDetector": _("%(count)s for this detector"),
        "noneInDetector": _("0 for this detector"),
        "play": _("Play"),
        "pause": _("Pause"),
        "mapFailed": _("The map could not start. You can still type coordinates."),
        "coordinatesUnread": _("RA and Dec could not be read."),
        "cutoutSize": _("%(size)s × %(size)s"),
        "measuring": _("Timing the first image…"),
        "progress": _("%(done)s / %(total)s · %(eta)s left"),
    }
