"""Sampling-time semantics contract for the standardized database.

Contract ``atlas-sampling-time-v1``.

Doctrine
--------
``sampling_time`` states when the physical sample was collected -- the
moment whose element content the measurement describes.  Publication
years, database release years and compilation years are never sampling
times: a source that only reports when results were published is recorded
as ``publisher_not_reported`` with the controlled reason
``publication_year_not_sampling_time`` instead of borrowing that year.

Raw values are parsed strictly per source.  The registered archives mix
mutually contradictory notations in the same column position (Australian
``D/M/YYYY`` in NGSA, US ``MM/DD/YY`` in the USGS CONUS workbook, and the
BraSol workbook stores 273 of its 396 rows as ``DD.MM.YY`` text next to
123 rows kept as Excel serial day numbers), so global format guessing is
forbidden; every source declares its raw field and format family below,
and values that do not match the declared family degrade honestly to
``unparseable_raw_value`` while the original text stays in ``sampled_at``.

Two-digit years use a fixed pivot: 00-49 map to 2000-2049 and 50-99 map
to 1950-1999.  Excel serial days count from the 1900 date system epoch
(1899-12-30).  Normalized values outside 1900..2035 are rejected as
unparseable rather than silently accepted.
"""

from __future__ import annotations

import datetime
import re

CONTRACT_ID = "atlas-sampling-time-v1"

STATUS_REPORTED = "publisher_reported"
STATUS_NOT_REPORTED = "publisher_not_reported"
STATUS_UNPARSEABLE = "unparseable_raw_value"

PRECISION_SECOND = "second"
PRECISION_MINUTE = "minute"
PRECISION_DAY = "day"
PRECISION_MONTH = "month"
PRECISION_YEAR = "year"
PRECISION_YEAR_RANGE = "year_range"

# Controlled vocabulary for why a source carries no sampling time.
REASON_PUBLICATION_YEAR = "publication_year_not_sampling_time"
REASON_NOT_IN_ARCHIVE = "no_extractable_sampling_time_in_registered_archive"

_YEAR_MIN = 1900
_YEAR_MAX = 2035

# Excel 1900 date system epoch (serial 1 renders as 1900-01-01 there, and
# the historical leap-year bug makes 1899-12-30 the working epoch).
_EXCEL_EPOCH = datetime.date(1899, 12, 30)

_ISO_PATTERN = re.compile(
    r"^(?P<year>\d{4})"
    r"(?:-(?P<month>\d{2})"
    r"(?:-(?P<day>\d{2})"
    r"(?:[T ](?P<hour>\d{2}):(?P<minute>\d{2})"
    r"(?::(?P<second>\d{2})(?:\.\d+)?)?"
    r")?)?)?$"
)
_DMY_SLASH_PATTERN = re.compile(
    r"^(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>\d{4})$"
)
_MDY_SLASH_2DIGIT_PATTERN = re.compile(
    r"^(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{2})$"
)
_DMY_DOT_2DIGIT_PATTERN = re.compile(
    r"^(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>\d{2})$"
)
_YEAR_PATTERN = re.compile(r"^(?P<year>\d{4})$")
_YEAR_RANGE_PATTERN = re.compile(r"^(?P<start>\d{4})/(?P<end>\d{4})$")
_EXCEL_SERIAL_PATTERN = re.compile(r"^\d{1,6}$")

# Per-source declarations.  ``raw_field`` documents which publisher field
# feeds the D1 ``sampled_at`` column; parsing happens in D2 against
# ``raw_format`` only.  Sources without an extractable sampling time say
# so with a controlled reason instead of borrowing unrelated years.
SOURCE_SAMPLING_TIME: dict[str, dict[str, str]] = {
    # -- sampling time reported by the publisher ------------------------
    "geotraces-idp2025": {
        "raw_field": "yyyy-mm-ddThh:mm:ss.sss",
        "raw_format": "iso8601",
    },
    "gemstat-open-archive": {
        "raw_field": "Sample Date + Sample Time",
        "raw_format": "iso8601",
    },
    "us-wqp-sacramento-river-arsenic": {
        "raw_field": "ActivityStartDate + ActivityStartTime/Time",
        "raw_format": "iso8601",
    },
    "pangaea-amazonas-soil": {"raw_field": "Date/Time", "raw_format": "iso8601"},
    "usgs-conus-soil": {"raw_field": "CollDate", "raw_format": "mdy_slash_2digit"},
    "australia-ngsa": {"raw_field": "DATE SAMPLED", "raw_format": "dmy_slash"},
    "australia-ngsa-mercury": {
        "raw_field": "DATE_SAMPLED",
        "raw_format": "dmy_slash",
    },
    "pangaea-brasol-ne-brazil-soil": {
        # The publisher workbook mixes DD.MM.YY text cells with Excel
        # serial-number date cells in the same column.
        "raw_field": "Date",
        "raw_format": "dmy_dot_2digit_or_excel_serial",
    },
    "norway-marchem": {"raw_field": "Cruise_year", "raw_format": "year"},
    "afsis-phase-i-wet-chemistry": {
        # The workbook states the 2009-2013 sampling period without
        # row-level dates; the range is the publisher's own claim.
        "raw_field": "sampling period (dataset metadata)",
        "raw_format": "year_range_slash",
    },
    # -- literature compilations: only publication years exist ----------
    "georoc-archaean": {"reason": REASON_PUBLICATION_YEAR},
    "georoc-antarctica-intraplate": {"reason": REASON_PUBLICATION_YEAR},
    "georoc-convergent-margins": {"reason": REASON_PUBLICATION_YEAR},
    "earthchem-dehailonggang-rock": {"reason": REASON_PUBLICATION_YEAR},
    # -- registered archives without an extractable sampling time -------
    "4tu-northern-china-sediment": {"reason": REASON_NOT_IN_ARCHIVE},
    "eidc-ningbo-soil": {"reason": REASON_NOT_IN_ARCHIVE},
    "figshare-yangtze-basin-soil-heavy-metals": {"reason": REASON_NOT_IN_ARCHIVE},
    "foregs-floodplain-sediment": {"reason": REASON_NOT_IN_ARCHIVE},
    "foregs-humus": {"reason": REASON_NOT_IN_ARCHIVE},
    "foregs-stream-sediment": {"reason": REASON_NOT_IN_ARCHIVE},
    "foregs-stream-water": {"reason": REASON_NOT_IN_ARCHIVE},
    "foregs-subsoil": {"reason": REASON_NOT_IN_ARCHIVE},
    "foregs-topsoil": {"reason": REASON_NOT_IN_ARCHIVE},
    "gemas-europe": {"reason": REASON_NOT_IN_ARCHIVE},
    "japan-gsj-geochemical-map": {"reason": REASON_NOT_IN_ARCHIVE},
    "japan-gsj-marine-sediment": {"reason": REASON_NOT_IN_ARCHIVE},
    "pangaea-arabian-sea-sediment": {"reason": REASON_NOT_IN_ARCHIVE},
    "pangaea-barents-c-horizon-soil": {"reason": REASON_NOT_IN_ARCHIVE},
    "pangaea-batagay-soil": {"reason": REASON_NOT_IN_ARCHIVE},
    "pangaea-east-china-sea-clay": {"reason": REASON_NOT_IN_ARCHIVE},
    "pangaea-north-africa-soil": {"reason": REASON_NOT_IN_ARCHIVE},
    "pangaea-south-china-sea-sediment": {"reason": REASON_NOT_IN_ARCHIVE},
    "tpdc-china-mountain-soil": {"reason": REASON_NOT_IN_ARCHIVE},
    "zenodo-yangtze-yellow-river-sediment": {"reason": REASON_NOT_IN_ARCHIVE},
    # Bundled synthetic regression fixture (not a registered manifest source);
    # its sampled_at column carries literal ISO dates by construction.
    "synthetic-demo-v1": {"raw_field": "sampled_at", "raw_format": "iso8601"},
}


def _valid_date(year: int, month: int, day: int) -> bool:
    if not _YEAR_MIN <= year <= _YEAR_MAX:
        return False
    try:
        datetime.date(year, month, day)
    except ValueError:
        return False
    return True


def _parse_iso8601(raw: str) -> tuple[str, str] | None:
    match = _ISO_PATTERN.match(raw)
    if match is None:
        return None
    year = int(match.group("year"))
    month = match.group("month")
    day = match.group("day")
    hour = match.group("hour")
    second = match.group("second")
    if month is None:
        if not _YEAR_MIN <= year <= _YEAR_MAX:
            return None
        return f"{year:04d}", PRECISION_YEAR
    if day is None:
        if not _valid_date(year, int(month), 1):
            return None
        return f"{year:04d}-{month}", PRECISION_MONTH
    if not _valid_date(year, int(month), int(day)):
        return None
    date_text = f"{year:04d}-{month}-{day}"
    if hour is None:
        return date_text, PRECISION_DAY
    minute = match.group("minute")
    if int(hour) > 23 or int(minute) > 59:
        return None
    if second is None:
        return f"{date_text}T{hour}:{minute}", PRECISION_MINUTE
    if int(second) > 60:
        return None
    return f"{date_text}T{hour}:{minute}:{second}", PRECISION_SECOND


def _parse_dmy_slash(raw: str) -> tuple[str, str] | None:
    match = _DMY_SLASH_PATTERN.match(raw)
    if match is None:
        return None
    year = int(match.group("year"))
    month = int(match.group("month"))
    day = int(match.group("day"))
    if not _valid_date(year, month, day):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}", PRECISION_DAY


def _parse_mdy_slash_2digit(raw: str) -> tuple[str, str] | None:
    match = _MDY_SLASH_2DIGIT_PATTERN.match(raw)
    if match is None:
        return None
    two_digit = int(match.group("year"))
    year = 2000 + two_digit if two_digit <= 49 else 1900 + two_digit
    month = int(match.group("month"))
    day = int(match.group("day"))
    if not _valid_date(year, month, day):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}", PRECISION_DAY


def _parse_year(raw: str) -> tuple[str, str] | None:
    match = _YEAR_PATTERN.match(raw)
    if match is None:
        return None
    year = int(match.group("year"))
    if not _YEAR_MIN <= year <= _YEAR_MAX:
        return None
    return f"{year:04d}", PRECISION_YEAR


def _parse_year_range_slash(raw: str) -> tuple[str, str] | None:
    match = _YEAR_RANGE_PATTERN.match(raw)
    if match is None:
        return None
    start = int(match.group("start"))
    end = int(match.group("end"))
    if not (_YEAR_MIN <= start <= end <= _YEAR_MAX):
        return None
    return f"{start:04d}/{end:04d}", PRECISION_YEAR_RANGE


def _parse_excel_serial_day(raw: str) -> tuple[str, str] | None:
    if _EXCEL_SERIAL_PATTERN.match(raw) is None:
        return None
    date = _EXCEL_EPOCH + datetime.timedelta(days=int(raw))
    if not _YEAR_MIN <= date.year <= _YEAR_MAX:
        return None
    return date.isoformat(), PRECISION_DAY


def _parse_dmy_dot_2digit(raw: str) -> tuple[str, str] | None:
    match = _DMY_DOT_2DIGIT_PATTERN.match(raw)
    if match is None:
        return None
    two_digit = int(match.group("year"))
    year = 2000 + two_digit if two_digit <= 49 else 1900 + two_digit
    month = int(match.group("month"))
    day = int(match.group("day"))
    if not _valid_date(year, month, day):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}", PRECISION_DAY


def _parse_dmy_dot_2digit_or_excel_serial(raw: str) -> tuple[str, str] | None:
    return _parse_dmy_dot_2digit(raw) or _parse_excel_serial_day(raw)


_PARSERS = {
    "iso8601": _parse_iso8601,
    "dmy_slash": _parse_dmy_slash,
    "mdy_slash_2digit": _parse_mdy_slash_2digit,
    "year": _parse_year,
    "year_range_slash": _parse_year_range_slash,
    "excel_serial_day": _parse_excel_serial_day,
    "dmy_dot_2digit_or_excel_serial": _parse_dmy_dot_2digit_or_excel_serial,
}


def normalize_sampling_time(source_id: str, raw: str | None) -> dict[str, str | None]:
    """Normalize one raw ``sampled_at`` value under the per-source contract.

    Returns the three derived database fields.  The raw value itself is
    preserved separately in ``sampled_at`` and never rewritten.
    """
    declaration = SOURCE_SAMPLING_TIME.get(source_id)
    text = (raw or "").strip()
    if declaration is None or "raw_format" not in declaration:
        if text:
            # The source declares no sampling-time semantics, so a raw
            # value cannot be interpreted as a collection moment.
            return {
                "sampling_time": None,
                "sampling_time_precision": None,
                "sampling_time_status": STATUS_UNPARSEABLE,
            }
        return {
            "sampling_time": None,
            "sampling_time_precision": None,
            "sampling_time_status": STATUS_NOT_REPORTED,
        }
    if not text:
        return {
            "sampling_time": None,
            "sampling_time_precision": None,
            "sampling_time_status": STATUS_NOT_REPORTED,
        }
    parsed = _PARSERS[declaration["raw_format"]](text)
    if parsed is None:
        return {
            "sampling_time": None,
            "sampling_time_precision": None,
            "sampling_time_status": STATUS_UNPARSEABLE,
        }
    normalized, precision = parsed
    return {
        "sampling_time": normalized,
        "sampling_time_precision": precision,
        "sampling_time_status": STATUS_REPORTED,
    }
