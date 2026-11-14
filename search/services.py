import http.client
import io
import logging
import re
import time
import urllib.error
from datetime import timezone as datetime_timezone
from pathlib import Path

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.nddata import Cutout2D
from astropy.nddata.utils import NoOverlapError
from astropy.time import Time
from astropy.utils.data import conf
from astropy.wcs import WCS
from astroquery.ipac.irsa import Irsa
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone
from django.utils.translation import gettext as _
from PIL import Image

from .models import SpherexImage

conf.remote_timeout = 120

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "spherex_qr3"
FALLBACK_COLLECTIONS = (
    "spherex_qr3",
    "spherex_qr3_deep",
    "spherex_qr2",
    "spherex_qr2_deep",
)
SEARCH_RADIUS = 1 * u.arcsec
MAX_RESULTS = 80
_COLLECTION_CACHE = {"expires": 0.0, "names": []}

# Longitud de onda central aproximada de cada detector, en micrones.
DETECTOR_BANDS = (
    (1, 0.75, 1.09),
    (2, 1.10, 1.62),
    (3, 1.63, 2.41),
    (4, 2.42, 3.82),
    (5, 3.83, 4.41),
    (6, 4.42, 5.00),
)


class SearchError(Exception):
    """Error que se puede mostrar en la página."""


def parse_coordinates(ra, dec):
    ra_text = " ".join(str(ra).strip().split())
    dec_text = " ".join(str(dec).strip().split())
    if not ra_text or not dec_text:
        raise SearchError(_("Missing RA and Dec."))

    try:
        if _is_decimal(ra_text) and _is_decimal(dec_text):
            coord = SkyCoord(float(ra_text), float(dec_text), unit="deg", frame="icrs")
        else:
            coord = SkyCoord(ra_text, dec_text, unit=(u.hourangle, u.deg), frame="icrs")
    except (ValueError, u.UnitsError, TypeError) as exc:
        raise SearchError(
            _("RA and Dec could not be read. Use 08h55m10.831s and -7d14m42.53s, or decimal degrees.")
        ) from exc

    if not np.isfinite(coord.ra.deg) or not np.isfinite(coord.dec.deg):
        raise SearchError(_("RA or Dec is out of range."))
    return coord


def fov_to_arcsec(value, unit):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SearchError(_("The cutout size is not a number.")) from exc
    if number <= 0:
        raise SearchError(_("The cutout size must be greater than zero."))
    try:
        arcsec = float((number * u.Unit(unit)).to(u.arcsec).value)
    except (ValueError, u.UnitsError) as exc:
        raise SearchError(_("Unknown size unit.")) from exc
    if arcsec > 3600:
        raise SearchError(_("In this version the maximum cutout is 1 degree."))
    return arcsec


def wavelength_label(em_min, em_max):
    lo = em_to_um(em_min)
    hi = em_to_um(em_max)
    if lo is None or hi is None:
        return ""
    return f"{lo:.2f}–{hi:.2f} µm"


def search_and_store(ra, dec, collection=None):
    coord = parse_coordinates(ra, dec)
    if collection:
        candidates = [collection]
    else:
        candidates = wide_collections()
    results = None
    collection_name = None
    errors = 0
    for candidate in candidates:
        try:
            found = Irsa.query_sia(pos=(coord, SEARCH_RADIUS), collection=candidate)
        except Exception:
            logger.exception("Fallo la consulta SIA para %s", candidate)
            errors += 1
            continue
        if found is not None and len(found) > 0:
            results = found
            collection_name = candidate
            break
    if results is None:
        if errors:
            raise SearchError(_("IRSA could not be queried. Try again in a few seconds."))
        return []

    saved = []
    for row in _most_recent(results, MAX_RESULTS):
        url = _text(_cell(row, "access_url"), limit=1000)
        if not url:
            continue
        em_min = _optional_float(_cell(row, "em_min"))
        em_max = _optional_float(_cell(row, "em_max"))
        observed = _mjd_to_datetime(_cell(row, "t_min")) or timezone.now()
        defaults = {
            "obs_id": _text(_cell(row, "obs_id"), limit=255) or "unknown",
            "ra_center": _optional_float(_cell(row, "s_ra")) or float(coord.ra.deg),
            "dec_center": _optional_float(_cell(row, "s_dec")) or float(coord.dec.deg),
            "observation_date": observed,
            "em_min": em_min,
            "em_max": em_max,
            "collection": collection_name[:64],
            "band": _text(_cell(row, "energy_bandpassname"), limit=80),
        }
        image, _created = SpherexImage.objects.update_or_create(access_url=url, defaults=defaults)
        guessed = detector_from_wavelength(em_min, em_max)
        if image.detector is None and guessed is not None:
            image.detector = guessed
            image.save(update_fields=["detector"])
        saved.append(image)

    saved.sort(key=lambda image: (image.observation_date, image.obs_id))
    return saved


def cached_cutout(image, ra, dec, fov_arcsec):
    coord = parse_coordinates(ra, dec)
    path = _cutout_cache_path(image.pk, coord.ra.deg, coord.dec.deg, fov_arcsec)
    if path.exists() and path.stat().st_size > 0:
        return path

    png = render_cutout(image, coord, fov_arcsec)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".part")
    png.save(temporary, format="PNG")
    temporary.replace(path)
    return path


def render_cutout(image, coord, fov_arcsec):
    if settings.FITS_IMAGE_CACHE == "r2":
        data, header = cached_image_hdu(image)
    else:
        data, header = _open_image(image.access_url)
    detector = _detector_number(header.get("DETECTOR"))
    if detector and image.detector != detector:
        image.detector = detector
        image.save(update_fields=["detector"])

    try:
        cutout = Cutout2D(
            data,
            position=coord,
            size=fov_arcsec * u.arcsec,
            wcs=WCS(header),
            mode="partial",
        )
    except NoOverlapError as exc:
        raise SearchError(_("This observation does not cover the requested position.")) from exc
    return _stretch_to_png(cutout.data)


def collection_choices():
    names = list_spherex_collections() or list(FALLBACK_COLLECTIONS)
    return [(name, collection_label(name)) for name in sort_collections(names)]


def collection_label(name):
    match = re.search(r"qr(\d+)", name)
    if not match:
        return name
    number = match.group(1)
    if name.endswith("_deep"):
        return _("Quick Release %(number)s (deep survey)") % {"number": number}
    return _("Quick Release %(number)s (wide survey)") % {"number": number}


def sort_collections(names):
    def key(name):
        deep = 1 if str(name).endswith("_deep") else 0
        return (-_release_number(name), deep, name)

    return sorted(names, key=key)


def default_collection(names=None):
    ordered = sort_collections(names or [choice[0] for choice in collection_choices()])
    for name in ordered:
        if not name.endswith("_deep"):
            return name
    return ordered[0] if ordered else DEFAULT_COLLECTION


def wide_collections(preferred=None):
    """Wide surveys, newest first. An empty newer release falls through to the previous one."""
    preferred = preferred or DEFAULT_COLLECTION
    names = list_spherex_collections()
    wide = [name for name in names if "deep" not in name and "qr" in name]
    wide.sort(key=_release_number, reverse=True)
    if not names:
        return [preferred]
    if preferred in names and preferred not in wide:
        wide.insert(0, preferred)
    elif preferred in wide:
        wide.remove(preferred)
        wide.insert(0, preferred)
    return wide or [preferred]


def list_spherex_collections():
    now = time.monotonic()
    if _COLLECTION_CACHE["names"] and now < _COLLECTION_CACHE["expires"]:
        return list(_COLLECTION_CACHE["names"])
    try:
        table = Irsa.list_collections(servicetype="SIA", filter="spherex")
    except Exception:
        logger.exception("Could not list SPHEREx collections")
        return []
    if table is None or "collection" not in getattr(table, "colnames", []):
        return []
    names = [str(name) for name in table["collection"] if str(name).strip()]
    if names:
        _COLLECTION_CACHE["names"] = names
        _COLLECTION_CACHE["expires"] = now + 600
    return names


def em_to_um(value):
    number = _optional_float(value)
    if number is None:
        return None
    if number < 1e-3:
        return number * 1e6
    return number


def detector_from_wavelength(em_min, em_max):
    lo = em_to_um(em_min)
    hi = em_to_um(em_max)
    if lo is None or hi is None:
        return None
    midpoint = (lo + hi) / 2
    for detector, band_lo, band_hi in DETECTOR_BANDS:
        if band_lo - 0.05 <= midpoint <= band_hi + 0.05:
            return detector
    return None


def cached_image_hdu(image):
    """Return the IMAGE array from R2, downloading and storing it on the first miss."""
    key = _image_cache_path(image.pk)
    if default_storage.exists(key):
        try:
            with default_storage.open(key, "rb") as stored:
                return _read_fits_bytes(stored.read())
        except Exception:
            logger.exception("Cached IMAGE %s could not be read; downloading again", key)

    data, header = _open_image(image.access_url, native=True)
    if data.dtype == np.float64:
        data = data.astype(np.float32)
    try:
        if default_storage.exists(key):
            default_storage.delete(key)
        default_storage.save(key, ContentFile(_fits_bytes(data, header)))
    except Exception:
        logger.exception("Could not store IMAGE cache %s", key)
    return data, header


def _image_cache_path(image_id):
    return f"fits-cache/v1_{image_id}.fits"


def _header_for_cached_image(header):
    cached = header.copy()
    for key in ("XTENSION", "PCOUNT", "GCOUNT", "EXTNAME", "BSCALE", "BZERO", "BLANK", "CHECKSUM", "DATASUM"):
        if key in cached:
            del cached[key]
    return cached


def _fits_bytes(data, header):
    buffer = io.BytesIO()
    fits.PrimaryHDU(data=np.asarray(data), header=_header_for_cached_image(header)).writeto(buffer)
    return buffer.getvalue()


def _read_fits_bytes(raw):
    with fits.open(io.BytesIO(raw), memmap=False) as hdul:
        hdu = hdul[0]
        if hdu.data is None:
            raise SearchError(_("The IMAGE extension is empty."))
        data = np.array(hdu.data, copy=True)
        header = hdu.header.copy()
    return data, header


def _open_image(url, *, native=False):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with fits.open(url, memmap=False) as hdul:
                try:
                    image_hdu = hdul["IMAGE"]
                except KeyError as exc:
                    raise SearchError(_("The FITS file has no IMAGE extension.")) from exc
                if image_hdu.data is None:
                    raise SearchError(_("The IMAGE extension is empty."))
                if native:
                    data = np.array(image_hdu.data, copy=True)
                else:
                    data = np.array(image_hdu.data, dtype=np.float64)
                header = image_hdu.header.copy()
            return data, header
        except SearchError:
            raise
        except (
            TimeoutError,
            urllib.error.HTTPError,
            urllib.error.URLError,
            http.client.IncompleteRead,
            ConnectionError,
        ) as exc:
            logger.warning("Intento %s al abrir %s falló: %s", attempt + 1, url, exc)
            if attempt == max_retries - 1:
                raise SearchError(_("The FITS file could not be downloaded from IRSA.")) from exc
            time.sleep(5 * (attempt + 1))
    raise SearchError(_("The FITS file could not be downloaded from IRSA."))


def _stretch_to_png(data):
    array = np.asarray(data, dtype=np.float64)
    if array.ndim != 2 or array.size == 0:
        raise SearchError(_("The cutout was empty."))

    finite = array[np.isfinite(array)]
    if finite.size == 0:
        scaled = np.zeros(array.shape, dtype=np.uint8)
    else:
        low, high = np.percentile(finite, (1, 99))
        if not np.isfinite(low) or not np.isfinite(high) or high <= low:
            scaled = np.zeros(array.shape, dtype=np.uint8)
        else:
            scaled = (array - low) / (high - low)
            scaled = np.clip(np.nan_to_num(scaled, nan=0.0), 0, 1)
            scaled = (scaled * 255).astype(np.uint8)

    return Image.fromarray(np.flipud(scaled), mode="L")


def _cutout_cache_path(image_id, ra_deg, dec_deg, fov_arcsec):
    name = f"v1_{image_id}_{ra_deg:.5f}_{dec_deg:.5f}_{float(fov_arcsec):.2f}.png"
    return Path(settings.MEDIA_ROOT) / "cutouts" / name


def _most_recent(results, limit):
    if "t_min" not in results.colnames:
        return results[:limit]
    times = np.array([_optional_float(_cell(row, "t_min")) or -1 for row in results])
    order = np.argsort(times)[-limit:]
    return results[order]


def _mjd_to_datetime(value):
    number = _optional_float(value)
    if number is None:
        return None
    try:
        return Time(number, format="mjd", scale="utc").to_datetime(timezone=datetime_timezone.utc)
    except (ValueError, OverflowError, TypeError):
        logger.warning("t_min MJD inválido: %s", value)
        return None


def _release_number(name):
    match = re.search(r"qr(\d+)", name)
    return int(match.group(1)) if match else -1


def _is_decimal(text):
    try:
        float(text)
    except ValueError:
        return False
    return True


def _optional_float(value):
    if value is None:
        return None
    try:
        if np.ma.is_masked(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number


def _detector_number(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if 1 <= number <= 6:
        return number
    return None


def _text(value, limit):
    if value is None:
        return ""
    try:
        if np.ma.is_masked(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = str(value).strip()
    if text.lower() in {"", "nan", "--", "none", "masked"}:
        return ""
    return text[:limit]


def _cell(row, name):
    if name not in row.colnames:
        return None
    return row[name]
