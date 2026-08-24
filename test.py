import unittest

from google.transit import gtfs_realtime_pb2

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
    return feed


class TransitTests(unittest.TestCase):
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