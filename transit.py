"""Shared Halifax Transit feed helpers."""

import csv
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

import requests
from google.transit import gtfs_realtime_pb2

FEED_URL = "https://gtfs.halifax.ca/realtime/Vehicle/VehiclePositions.pb"
REQUEST_TIMEOUT = 5
EMPTY_GEOJSON = {"type": "FeatureCollection", "features": []}
GTFS_PATH = Path(__file__).parent / "data"


def fetch_feed(timeout=REQUEST_TIMEOUT):
    """Fetch and parse the current vehicle positions feed."""
    response = requests.get(FEED_URL, timeout=timeout)
    response.raise_for_status()

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)
    return feed


def route_ids(feed):
    """Return sorted route IDs present in a feed."""
    return sorted(
        {
            entity.vehicle.trip.route_id
            for entity in _vehicles(feed)
            if entity.vehicle.HasField("trip")
            and entity.vehicle.trip.HasField("route_id")
        }
    )


def vehicles_to_geojson(feed, target=None):
    """Convert positioned vehicles to GeoJSON, optionally filtering by ID/route."""
    features = []
    for entity in _vehicles(feed):
        vehicle = entity.vehicle
        if not vehicle.HasField("position"):
            continue

        bus_id = (
            vehicle.vehicle.id
            if vehicle.HasField("vehicle") and vehicle.vehicle.HasField("id")
            else entity.id
        )
        route_id = (
            vehicle.trip.route_id
            if vehicle.HasField("trip") and vehicle.trip.HasField("route_id")
            else "N/A"
        )
        if target is not None and target not in (bus_id, route_id):
            continue

        position = vehicle.position
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "id": bus_id,
                    "route_id": route_id,
                    "trip_id": (
                        vehicle.trip.trip_id
                        if vehicle.HasField("trip") and vehicle.trip.HasField("trip_id")
                        else ""
                    ),
                    "direction_id": (
                        vehicle.trip.direction_id
                        if vehicle.HasField("trip")
                        and vehicle.trip.HasField("direction_id")
                        else None
                    ),
                    "stop_id": vehicle.stop_id if vehicle.HasField("stop_id") else "",
                    "stop_sequence": (
                        vehicle.current_stop_sequence
                        if vehicle.HasField("current_stop_sequence")
                        else 0
                    ),
                    "occupancy_percentage": (
                        vehicle.occupancy_percentage
                        if vehicle.HasField("occupancy_percentage")
                        else None
                    ),
                    "odometer": (
                        position.odometer
                        if position.HasField("odometer")
                        else None
                    ),
                    "speed": (
                        position.speed if position.HasField("speed") else None
                    ),
                    "bearing": position.bearing,
                    "timestamp": feed.header.timestamp,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [position.longitude, position.latitude],
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}


@lru_cache(maxsize=1)
def static_gtfs():
    """Load the static GTFS relationships needed to draw a trip."""
    trips = {}
    with (GTFS_PATH / "trips.txt").open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            trips[row["trip_id"]] = (
                row["route_id"],
                row["shape_id"],
                row["direction_id"],
            )

    trip_stops = {}
    with (GTFS_PATH / "stop_times.txt").open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            trip_stops.setdefault(row["trip_id"], []).append(
                (int(row["stop_sequence"]), row["stop_id"])
            )
    for stops in trip_stops.values():
        stops.sort()

    stop_locations = {}
    with (GTFS_PATH / "stops.txt").open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            stop_locations[row["stop_id"]] = {
                "name": row["stop_name"],
                "coordinates": [float(row["stop_lon"]), float(row["stop_lat"])],
            }

    shapes = {}
    with (GTFS_PATH / "shapes.txt").open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            shapes.setdefault(row["shape_id"], []).append(
                (
                    int(row["shape_pt_sequence"]),
                    [float(row["shape_pt_lon"]), float(row["shape_pt_lat"])],
                )
            )
    for points in shapes.values():
        points.sort()

    return trips, trip_stops, stop_locations, shapes


def trip_route(trip_id, route_id=None, direction_id=None):
    """Return a trip's route shape and ordered stop features."""
    trips, trip_stops, stop_locations, shapes = static_gtfs()
    trip = trips.get(trip_id)
    if trip is None and route_id is not None:
        trip_id, trip = _fallback_trip(trips, route_id, direction_id)
    if trip is None:
        raise KeyError(trip_id)
    route_id, shape_id, _ = trip
    stops = []
    for sequence, stop_id in trip_stops.get(trip_id, []):
        stop = stop_locations.get(stop_id)
        if stop is None:
            continue
        stops.append(
            {
                "type": "Feature",
                "properties": {
                    "id": stop_id,
                    "name": stop["name"],
                    "sequence": sequence,
                },
                "geometry": {"type": "Point", "coordinates": stop["coordinates"]},
            }
        )

    return {
        "trip_id": trip_id,
        "route_id": route_id,
        "shape": {
            "type": "Feature",
            "properties": {"route_id": route_id},
            "geometry": {
                "type": "LineString",
                "coordinates": [point for _, point in shapes.get(shape_id, [])],
            },
        },
        "stops": {"type": "FeatureCollection", "features": stops},
    }


def _fallback_trip(trips, route_id, direction_id):
    """Find a current snapshot trip when realtime IDs are from another feed version."""
    for trip_id, trip in trips.items():
        if trip[0] == route_id and (
            direction_id is None or trip[2] == str(direction_id)
        ):
            return trip_id, trip
    return None, None


def _vehicles(feed) -> Iterable:
    """Yield entities that contain vehicle data."""
    return (entity for entity in feed.entity if entity.HasField("vehicle"))