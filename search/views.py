import logging
from urllib.parse import urlencode

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

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

    trail = None
    refresh_url = ""
    if has_query:
        searched = True
        if form.is_valid():
            frames, error, info, trail, refresh_url = _search_page(form)
        else:
            error = _("Check the coordinates and the cutout size.")

    target_ra, target_dec = _map_target(form)
    query = _submitted_query(form) if searched and form.is_valid() else None

    return render(request, "search/index.html", {
        "form": form,
        "frames": frames,
        "error": error,
        "info": info,
        "trail": trail,
        "refresh_url": refresh_url,
        "searched": searched,
        "target_ra": target_ra,
        "target_dec": target_dec,
        "map_fov": _map_fov(form),
        "query": query,
        "messages_json": _js_messages(),
    })


def refresh(request):
    form = CoordinateForm(request.GET)
    if not form.is_valid():
        return JsonResponse({"status": "invalid"}, status=400)
    data = form.cleaned_data
    try:
        coord = services.parse_coordinates(data["ra"], data["dec"])
        had_local = bool(services.local_images_covering(coord, data["collections"]))
    except services.SearchError:
        had_local = False
    try:
        images, new_count = services.search_collections(data["ra"], data["dec"], data["collections"])
    except services.SearchError:
        state, text = _irsa_trail("unavailable" if had_local else "unavailable_empty", 0)
        payload = {"status": "unavailable", "irsa_state": state, "irsa_text": text}
        if had_local:
            payload["info"] = _("Showing saved observations. A cutout still needs the FITS file.")
        return JsonResponse(payload)
    except Exception:
        logger.exception("Unexpected IRSA refresh error")
        state, text = _irsa_trail("unavailable" if had_local else "unavailable_empty", 0)
        return JsonResponse({"status": "unavailable", "irsa_state": state, "irsa_text": text})
    if not images:
        return JsonResponse({
            "status": "empty",
            "frames": [],
            "irsa_state": "empty",
            "irsa_text": _irsa_trail("empty", 0)[1],
            "info": _("IRSA returned no SPHEREx images for this position in %(collection)s.") % {
                "collection": _collection_phrase(data["collections"]),
            },
        })
    state, text = _irsa_trail("ready", new_count, images)
    return JsonResponse({
        "status": "updated",
        "frames": [_frame_payload(image) for image in images],
        "new_count": new_count,
        "irsa_state": state,
        "irsa_text": text,
        "info": _result_info(images, new_count),
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
    return _png_response(path, pk)


def sum_cutout(request):
    try:
        ids = [int(part) for part in request.GET.get("ids", "").split(",") if part.strip()]
    except ValueError:
        return HttpResponse(
            _("Select at least one detector."),
            status=400,
            content_type="text/plain; charset=utf-8",
        )
    ids = list(dict.fromkeys(ids))
    if not ids or len(ids) > 6:
        return HttpResponse(
            _("Select at least one detector."),
            status=400,
            content_type="text/plain; charset=utf-8",
        )
    images = list(SpherexImage.objects.filter(pk__in=ids))
    if len(images) != len(ids):
        return HttpResponse(
            _("The cutout could not be generated."),
            status=404,
            content_type="text/plain; charset=utf-8",
        )
    try:
        fov_arcsec = services.fov_to_arcsec(
            request.GET.get("fov"),
            request.GET.get("unit", "arcsec"),
        )
        path = services.cached_sum_cutout(
            images,
            request.GET.get("ra", ""),
            request.GET.get("dec", ""),
            fov_arcsec,
        )
    except services.SearchError as exc:
        return HttpResponse(str(exc), status=422, content_type="text/plain; charset=utf-8")
    except Exception:
        logger.exception("Could not sum images %s", ids)
        return HttpResponse(
            _("The cutout could not be generated."),
            status=502,
            content_type="text/plain; charset=utf-8",
        )
    return _png_response(path, ids)


def _png_response(path, label):
    try:
        payload = path.read_bytes()
    except Exception:
        logger.exception("Could not read cutout file for %s", label)
        return HttpResponse(
            _("The cutout could not be generated."),
            status=502,
            content_type="text/plain; charset=utf-8",
        )
    if not payload:
        logger.error("Cutout file for %s was empty", label)
        return HttpResponse(
            _("The cutout could not be generated."),
            status=502,
            content_type="text/plain; charset=utf-8",
        )
    return HttpResponse(payload, content_type="image/png")


def health_check(request):
    return JsonResponse({"status": "ok", "app": "SPHEREx NASA Hackaton live"})


def _search_page(form):
    data = form.cleaned_data
    try:
        coord = services.parse_coordinates(data["ra"], data["dec"])
        local = services.local_images_covering(coord, data["collections"])
    except services.SearchError as exc:
        local_state, local_text = _local_trail([])
        irsa_state, irsa_text = _irsa_trail("unavailable_empty", 0)
        return [], str(exc), None, _trail(local_state, local_text, irsa_state, irsa_text), ""
    if local:
        frames = [_frame_payload(image) for image in local]
        local_state, local_text = _local_trail(local)
        irsa_state, irsa_text = _irsa_trail("pending", 0)
        return frames, None, _result_info(local, 0), _trail(local_state, local_text, irsa_state, irsa_text), _refresh_url(data)
    try:
        images, new_count = services.search_collections(data["ra"], data["dec"], data["collections"])
    except services.SearchError as exc:
        local_state, local_text = _local_trail([])
        irsa_state, irsa_text = _irsa_trail("unavailable_empty", 0)
        return [], str(exc), None, _trail(local_state, local_text, irsa_state, irsa_text), ""
    except Exception:
        logger.exception("Unexpected IRSA search error")
        local_state, local_text = _local_trail([])
        irsa_state, irsa_text = _irsa_trail("unavailable_empty", 0)
        return [], _("IRSA could not be queried. Try again in a few seconds."), None, _trail(local_state, local_text, irsa_state, irsa_text), ""
    frames = [_frame_payload(image) for image in images]
    local_state, local_text = _local_trail([])
    if not frames:
        irsa_state, irsa_text = _irsa_trail("empty", 0)
        info = _("IRSA returned no SPHEREx images for this position in %(collection)s.") % {
            "collection": _collection_phrase(data["collections"]),
        }
    else:
        irsa_state, irsa_text = _irsa_trail("ready", new_count, images)
        info = _result_info(images, new_count)
    return frames, None, info, _trail(local_state, local_text, irsa_state, irsa_text), ""


def _refresh_url(data):
    pairs = [
        ("ra", data["ra"]),
        ("dec", data["dec"]),
        ("fov", data["fov"]),
        ("unit", data["unit"]),
        ("collection", data["collection"]),
        ("detector", data["detector"]),
    ]
    if data.get("advanced"):
        pairs.append(("advanced", "on"))
        pairs.extend(("collections", name) for name in data["collections"])
    return f"{reverse('refresh')}?{urlencode(pairs)}"


def _collection_phrase(names):
    return ", ".join(str(services.collection_label(name)) for name in names)


def _trail(local_state, local_text, irsa_state, irsa_text):
    return {
        "local_state": local_state,
        "local_text": local_text,
        "irsa_state": irsa_state,
        "irsa_text": irsa_text,
    }


def _detector_phrase(images):
    numbers = sorted({image.detector for image in images if getattr(image, "detector", None)})
    if not numbers:
        return ""
    return _("Detectors %(list)s") % {"list": ", ".join(str(number) for number in numbers)}


def _with_detectors(text, images):
    phrase = _detector_phrase(images or [])
    if not phrase:
        return text
    return f"{text} · {phrase}"


def _local_trail(images):
    count = len(images)
    if count:
        text = ngettext(
            "%(count)s saved observation",
            "%(count)s saved observations",
            count,
        ) % {"count": count}
        return "ready", _with_detectors(text, images)
    return "empty", _("Nothing saved for this point")


def _irsa_trail(status, new_count, images=None):
    if status == "pending":
        return "pending", _("Checking IRSA…")
    if status in {"unavailable", "unavailable_empty"}:
        return "failed", _("IRSA did not respond")
    if status == "empty":
        return "empty", _("No images in this collection")
    if new_count:
        text = ngettext(
            "%(count)s new observation",
            "%(count)s new observations",
            new_count,
        ) % {"count": new_count}
    else:
        text = _("No new observations")
    return "ready", _with_detectors(text, images)


def _result_info(images, new_count):
    if new_count:
        return ngettext(
            "%(count)s new observation",
            "%(count)s new observations",
            new_count,
        ) % {"count": new_count}
    return ""


def _frame_payload(image):
    return {
        "id": image.pk,
        "obs_id": image.obs_id,
        "detector": image.detector,
        "date": timezone.localtime(image.observation_date).strftime("%Y-%m-%d %H:%M UTC"),
        "wavelength": services.wavelength_label(image.em_min, image.em_max),
        "collection": image.collection,
        "detector_label": (
            _("Detector %(number)s") % {"number": image.detector}
            if image.detector
            else _("Detector not identified")
        ),
    }


def _map_target(form):
    ra = form["ra"].value() or ""
    dec = form["dec"].value() or ""
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
        "noResults": _("No results."),
        "chooseObservation": _("Choose an observation or press play."),
        "selectToPlay": _("Select at least one observation to play."),
        "selectObservation": _("Include in playback"),
        "sum": _("Sum"),
        "detectorNumber": _("Detector %(number)s"),
        "sumNone": _("No observation includes every selected detector."),
        "selectDetector": _("Select at least one detector."),
        "sumReady": _("%(count)s observations ready to sum. Press play."),
        "sumGroup": _("Detectors %(list)s · %(count)s observations"),
        "sumDetectors": _("Detectors %(list)s"),
        "sumCount": _("%(count)s summed images"),
        "sumPick": _("Choose the observations to include. Each checked observation becomes one summed image. Confirm with none checked to keep every match."),
        "sumNoGroup": _("No observation has more than one detector to sum."),
        "confirm": _("Confirm"),
    }
