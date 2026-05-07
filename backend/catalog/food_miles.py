from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, radians, sin, sqrt

from django.core.exceptions import ObjectDoesNotExist

from accounts.postcodes import PostcodeLookupUnavailable, lookup_postcode, normalize_uk_postcode

EARTH_RADIUS_MILES = 3958.8
LOCAL_RADIUS_MILES = 20


@dataclass(frozen=True)
class FoodMilesResult:
    miles: float
    miles_display: str
    impact_class: str
    within_local_radius: bool
    local_radius_message: str


@dataclass(frozen=True)
class FoodMilesSummary:
    total_miles: float
    total_miles_display: str
    measured_count: int
    unavailable_count: int
    all_within_local_radius: bool
    message: str


def _postcode_coordinates(postcode: str | None):
    normalized = normalize_uk_postcode(postcode)
    if not normalized:
        return None

    try:
        lookup_result = lookup_postcode(normalized)
    except PostcodeLookupUnavailable:
        return None

    if lookup_result is not None:
        latitude = lookup_result.get("latitude")
        longitude = lookup_result.get("longitude")
        if latitude is not None and longitude is not None:
            return latitude, longitude

    return None


def _producer_postcode_for_product(product) -> str:
    producer = getattr(product, "producer", None)
    if producer is None:
        return ""

    try:
        producer_profile = producer.producer_profile
    except ObjectDoesNotExist:
        return ""

    return getattr(producer_profile, "postcode", "")


def _impact_class_for_miles(miles: float):
    if miles <= 5:
        return "food-miles-low"
    if miles <= LOCAL_RADIUS_MILES:
        return "food-miles-medium"
    return "food-miles-high"


def calculate_food_miles(customer_postcode: str | None, producer_postcode: str | None):
    origin = _postcode_coordinates(customer_postcode)
    destination = _postcode_coordinates(producer_postcode)

    if origin is None or destination is None:
        return None

    lat1, lon1 = origin
    lat2, lon2 = destination

    lat1_rad = radians(lat1)
    lon1_rad = radians(lon1)
    lat2_rad = radians(lat2)
    lon2_rad = radians(lon2)

    delta_lat = lat2_rad - lat1_rad
    delta_lon = lon2_rad - lon1_rad

    a = (
        sin(delta_lat / 2) ** 2
        + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2) ** 2
    )
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    miles = round(EARTH_RADIUS_MILES * c, 1)

    impact_class = _impact_class_for_miles(miles)
    within_local_radius = miles <= LOCAL_RADIUS_MILES

    return FoodMilesResult(
        miles=miles,
        miles_display=f"{miles:.1f}",
        impact_class=impact_class,
        within_local_radius=within_local_radius,
        local_radius_message=(
            "Within 20-mile radius"
            if within_local_radius
            else "Outside 20-mile radius"
        ),
    )


def food_miles_for_product(product, customer_postcode: str | None):
    return calculate_food_miles(customer_postcode, _producer_postcode_for_product(product))


def summarize_food_miles(results, expected_count: int | None = None):
    measured = [result for result in results if result is not None]
    measured_count = len(measured)
    unavailable_count = max((expected_count or len(results)) - measured_count, 0)

    if measured_count == 0:
        return None

    total_miles = round(sum(result.miles for result in measured), 1)
    all_within_local_radius = all(result.within_local_radius for result in measured)

    if unavailable_count:
        message = (
            f"{measured_count} product line(s) measured; "
            f"{unavailable_count} line(s) missing postcode data."
        )
    elif all_within_local_radius:
        message = "All measured items are within 20-mile radius."
    else:
        message = (
            f"{sum(result.within_local_radius for result in measured)} of "
            f"{measured_count} product line(s) are within 20-mile radius."
        )

    return FoodMilesSummary(
        total_miles=total_miles,
        total_miles_display=f"{total_miles:.1f} miles",
        measured_count=measured_count,
        unavailable_count=unavailable_count,
        all_within_local_radius=all_within_local_radius,
        message=message,
    )
