import unittest

from google.transit import gtfs_realtime_pb2

import app
from transit import route_ids, trip_route, vehicles_to_geojson


def make_feed():
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.timestamp = 123

    entity = feed.entity.add(id="entity-1")
    entity.vehicle.vehicle.id = "bus-1"
    entity.vehicle.trip.route_id = "1"
    entity.vehicle.position.latitude = 44.65
    entity.vehicle.position.longitude = -63.57
    entity.vehicle.position.bearing = 90
    entity.vehicle.position.odometer = 3315.24864
    entity.vehicle.position.speed = 13.4112
    entity.vehicle.occupancy_percentage = 20
    return feed


class TransitTests(unittest.TestCase):
    def test_map_requests_location_with_center_fallback(self):
        page = app.app.test_client().get("/").get_data(as_text=True)
        location_code = app.location_script("map_instance")

        self.assertIn("navigator.geolocation.getCurrentPosition", page)
        self.assertIn("enableHighAccuracy: false", page)
        self.assertIn("map.setView", page)
        self.assertIn("fillColor: '#1976d2'", location_code)
        self.assertIn("Your current location", location_code)
        self.assertIn("current-location-control", location_code)
        self.assertIn("position: 'bottomright'", location_code)
        self.assertIn("map.setView(currentLocation, map.getZoom())", location_code)
        self.assertIn("radius: 12", location_code)
        self.assertIn("bus-popup", page)
        self.assertIn("font-size: 20px", page)
        self.assertIn("transform: scale(1.8)", page)
        self.assertIn("font-size: 24px", page)
        self.assertIn("min-height: 44px", page)
        self.assertIn('viewBox=&quot;0 0 72 48&quot;', page)
        self.assertIn("transform: rotate(${bearing - 90}deg)", page)

    def test_route_ids_are_sorted_and_unique(self):
        feed = make_feed()
        second = feed.entity.add(id="entity-2")
        second.vehicle.trip.route_id = "2"

        self.assertEqual(route_ids(feed), ["1", "2"])

    def test_geojson_can_filter_by_bus_or_route(self):
        feed = make_feed()

        by_bus = vehicles_to_geojson(feed, target="bus-1")
        by_route = vehicles_to_geojson(feed, target="1")

        self.assertEqual(len(by_bus["features"]), 1)
        self.assertEqual(by_bus, by_route)
        properties = by_bus["features"][0]["properties"]
        self.assertEqual(properties["occupancy_percentage"], 20)
        self.assertAlmostEqual(properties["odometer"], 3315.24864, places=3)
        self.assertAlmostEqual(properties["speed"], 13.4112, places=3)
        coordinates = by_bus["features"][0]["geometry"]["coordinates"]
        self.assertAlmostEqual(coordinates[0], -63.57, places=5)
        self.assertAlmostEqual(coordinates[1], 44.65, places=5)

    def test_static_trip_route_contains_shape_and_ordered_stops(self):
        route = trip_route("missing-trip", route_id="1")

        self.assertEqual(route["route_id"], "1")
        self.assertEqual(route["shape"]["geometry"]["type"], "LineString")
        self.assertGreater(len(route["shape"]["geometry"]["coordinates"]), 1)
        self.assertGreater(len(route["stops"]["features"]), 1)
        self.assertEqual(route["stops"]["features"][0]["properties"]["sequence"], 1)


if __name__ == "__main__":
    unittest.main()