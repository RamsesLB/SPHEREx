import logging
from urllib.parse import urlencode

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from .forms import CoordinateForm
from .models import ExampleSkyObject, SpherexImage
from . import services

logger = logging.getLogger(__name__)


def home(request):
    if "ra" in request.GET or "dec" in request.GET or (request.GET.get("format") or "").strip().lower() == "json":
        target = reverse("index")
        query = request.META.get("QUERY_STRING", "")
        if query:
            target = f"{target}?{query}"
        return redirect(target)
    return render(request, "search/home.html")


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
        if form.is_valid() and _wants_json(request):
            frames, error, info, trail = _search_json_sources(form)
        elif form.is_valid():
            frames, error, info, trail, refresh_url = _search_page(form)
        else:
            error = _("Check the coordinates and the cutout size.")

    target_ra, target_dec = _map_target(form)
    query = _submitted_query(form) if searched and form.is_valid() else None

    if _wants_json(request):
        return _search_json(request, form, frames, error, info, trail, searched)

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
        "example_objects_json": _example_objects(),
    })


def _example_objects():
    return [
        {
            "id": f"ex-{item.pk}",
            "name": item.name,
            "description": item.description,
            "ra": item.ra,
            "dec": item.dec,
            "fov": f"{item.fov:g}",
            "unit": item.unit,
        }
        for item in ExampleSkyObject.objects.filter(is_active=True)
    ]


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


def allwise_catalog(request):
    try:
        payload = services.allwise_anchor(request.GET.get("ra", ""), request.GET.get("dec", ""))
    except services.SearchError:
        return JsonResponse({"found": False})
    return JsonResponse(payload)


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


def _cutout_ids(raw, limit=6):
    try:
        ids = [int(part) for part in (raw or "").split(",") if part.strip()]
    except ValueError:
        return None
    ids = list(dict.fromkeys(ids))
    if not ids or len(ids) > limit:
        return None
    return ids


def _images_for_ids(ids):
    images = list(SpherexImage.objects.filter(pk__in=ids))
    if len(images) != len(ids):
        return None
    return images


def sum_cutout(request):
    ids = _cutout_ids(request.GET.get("ids", ""))
    if ids is None:
        return HttpResponse(
            _("Select at least one detector."),
            status=400,
            content_type="text/plain; charset=utf-8",
        )
    images = _images_for_ids(ids)
    if images is None:
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


def diff_cutout(request):
    before_ids = _cutout_ids(request.GET.get("before", ""))
    after_ids = _cutout_ids(request.GET.get("after", ""))
    if before_ids is None or after_ids is None or set(before_ids) & set(after_ids):
        return HttpResponse(
            _("Choose exactly two observations."),
            status=400,
            content_type="text/plain; charset=utf-8",
        )
    before = _images_for_ids(before_ids)
    after = _images_for_ids(after_ids)
    if before is None or after is None:
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
        path = services.cached_diff_cutout(
            before,
            after,
            request.GET.get("ra", ""),
            request.GET.get("dec", ""),
            fov_arcsec,
        )
    except services.SearchError as exc:
        return HttpResponse(str(exc), status=422, content_type="text/plain; charset=utf-8")
    except Exception:
        logger.exception("Could not subtract images %s - %s", after_ids, before_ids)
        return HttpResponse(
            _("The cutout could not be generated."),
            status=502,
            content_type="text/plain; charset=utf-8",
        )
    return _png_response(path, (before_ids, after_ids))


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


def information(request):
    return render(request, "search/information.html")


def health_check(request):
    return JsonResponse({"status": "ok", "app": "SPHEREx NASA Hackaton live"})


def _wants_json(request):
    """Same search URL, JSON when a client asks for it instead of the page."""
    if (request.GET.get("format") or "").strip().lower() == "json":
        return True
    accept = request.headers.get("Accept", "")
    if "application/json" not in accept:
        return False
    html_at = accept.find("text/html")
    json_at = accept.find("application/json")
    return html_at == -1 or json_at < html_at


def _search_json(request, form, frames, error, info, trail, searched):
    if searched and not form.is_valid():
        return JsonResponse({
            "status": "invalid",
            "query": None,
            "count": 0,
            "results": [],
            "error": error,
            "info": None,
            "trail": None,
        }, status=400)
    query = _submitted_query(form) if searched and form.is_valid() else None
    if query is not None:
        object_name = (request.GET.get("object") or "").strip()
        if object_name:
            query["object"] = object_name[:80]
        query["collections"] = list(form.cleaned_data.get("collections") or [])
    if not searched:
        status = "idle"
    elif error:
        status = "error"
    elif frames:
        status = "ok"
    else:
        status = "empty"
    results = [_result_payload(request, frame, query) for frame in frames]
    return JsonResponse({
        "status": status,
        "query": query,
        "count": len(results),
        "results": results,
        "error": error,
        "info": info or None,
        "trail": trail,
    })


def _result_payload(request, frame, query):
    item = dict(frame)
    if query:
        params = urlencode({
            "ra": query["ra"],
            "dec": query["dec"],
            "fov": query["fov"],
            "unit": query["unit"],
        })
        item["cutout"] = request.build_absolute_uri(
            f"{reverse('cutout', args=[frame['id']])}?{params}"
        )
    return item


def _search_json_sources(form):
    """Local first, then IRSA. An IRSA failure keeps the saved rows."""
    data = form.cleaned_data
    try:
        coord = services.parse_coordinates(data["ra"], data["dec"])
        local = list(services.local_images_covering(coord, data["collections"]))
    except services.SearchError as exc:
        local_state, local_text = _local_trail([])
        irsa_state, irsa_text = _irsa_trail("unavailable_empty", 0)
        return [], str(exc), None, _trail(local_state, local_text, irsa_state, irsa_text)
    local_state, local_text = _local_trail(local)
    try:
        images, new_count = services.search_collections(data["ra"], data["dec"], data["collections"])
    except services.SearchError as exc:
        return _json_local_fallback(local, local_state, local_text, str(exc))
    except Exception:
        logger.exception("Unexpected IRSA search error")
        return _json_local_fallback(
            local,
            local_state,
            local_text,
            _("IRSA could not be queried. Try again in a few seconds."),
        )
    frames = [_frame_payload(image) for image in images]
    if not frames:
        irsa_state, irsa_text = _irsa_trail("empty", 0)
        info = _("IRSA returned no SPHEREx images for this position in %(collection)s.") % {
            "collection": _collection_phrase(data["collections"]),
        }
    else:
        irsa_state, irsa_text = _irsa_trail("ready", new_count, images)
        info = _result_info(images, new_count)
    return frames, None, info, _trail(local_state, local_text, irsa_state, irsa_text)


def _json_local_fallback(local, local_state, local_text, irsa_error):
    irsa_state, irsa_text = _irsa_trail("unavailable" if local else "unavailable_empty", 0)
    trail = _trail(local_state, local_text, irsa_state, irsa_text)
    if not local:
        return [], irsa_error, None, trail
    frames = [_frame_payload(image) for image in local]
    info = _("Showing saved observations. A cutout still needs the FITS file.")
    return frames, None, info, trail


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
    """Strings the playback script reads from #ui-messages."""
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
        "chooseObservation": _("Click an observation, or tick several checkboxes and press play."),
        "selectToPlay": _("Select at least one observation to play."),
        "selectObservation": _("Include in playback"),
        "sum": _("Sum"),
        "detectorNumber": _("Detector %(number)s"),
        "sumNone": _("No observation includes every selected detector."),
        "selectDetector": _("Select at least one detector."),
        "sumReady": _("%(count)s observations ready to sum. Press play."),
        "sumPlaying": _("Summing detectors for %(count)s observations."),
        "sumGroup": _("Detectors %(list)s · %(count)s observations"),
        "sumDetectors": _("Detectors %(list)s"),
        "sumCount": _("%(count)s summed images"),
        "sumResults": _("Sum results"),
        "chooseSum": _("Choose a summed image."),
        "sumPick": _("Choose the observations to include. Each checked observation becomes one summed image. Confirm with none checked to keep every match."),
        "sumNoGroup": _("No observation has more than one detector to sum."),
        "diff": _("Subtract"),
        "diffHelp": _("Choose one detector or a detector group. The next step asks for exactly two dates. The later epoch is subtracted from the earlier one."),
        "diffPick": _("Choose exactly two observations. The later one is subtracted from the earlier one, on the same sky grid."),
        "diffMax": _("Only two observations can be subtracted."),
        "diffNeed": _("Choose exactly two observations of this detector."),
        "diffNeedSums": _("Choose exactly two summed images."),
        "diffReady": _("Two observations ready to subtract. Press play."),
        "diffPlaying": _("Subtracting the later observation from the earlier one."),
        "diffCount": _("%(count)s subtracted images"),
        "diffOne": _("1 subtracted image"),
        "diffResults": _("Subtraction results"),
        "diffGroup": _("Detector %(number)s · %(count)s observations"),
        "diffNone": _("No detector has two observations to subtract."),
        "chooseDiff": _("Choose a subtracted image."),
        "confirm": _("Confirm"),
        "wiseLabel": _("AllWISE %(year)s · %(separation)s"),
        "wiseOutside": _("The 2010 position falls outside this cutout."),
        "wiseArcmin": _("%(value)s arcmin"),
        "wiseArcsec": _("%(value)s arcsec"),
        "wiseMissing": _("No AllWISE position is saved for this point, and IRSA did not return one."),
    }
