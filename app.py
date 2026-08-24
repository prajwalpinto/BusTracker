import html
import os
import re
from urllib.parse import quote

import folium
import requests
from flask import Flask, jsonify, request
from folium.plugins import Realtime

from transit import EMPTY_GEOJSON, fetch_feed, route_ids, trip_route, vehicles_to_geojson

app = Flask(__name__)

MAP_CENTER = [44.6488, -63.5752]
TRIP_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")
BUS_MARKER_CSS = """
<style>
.bus-marker-wrapper {
    background: transparent !important;
    border: 0 !important;
}
.bus-marker {
    width: 80px;
    height: 68px;
    display: flex;
    flex-direction: column;
    align-items: center;
    pointer-events: none;
}
.bus-label {
    max-width: 76px;
    overflow: hidden;
    padding: 2px 5px;
    border: 1px solid #1d2939;
    border-radius: 4px;
    background: #ffffff;
    color: #1d2939;
    font: 700 11px/14px sans-serif;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.bus-icon {
    width: 40px;
    height: 48px;
    transform-origin: 20px 24px;
}
</style>
"""
ROUTE_SCRIPT = """
<script>
window.selectedBusRoute = null;
window.showBusRoute = function (map, tripId, routeId, directionId) {
    if (!tripId) return;
    if (window.selectedBusRoute) map.removeLayer(window.selectedBusRoute);

    const query = '?trip_id=' + encodeURIComponent(tripId) +
        '&route_id=' + encodeURIComponent(routeId || '') +
        '&direction_id=' + encodeURIComponent(directionId ?? '');
    fetch('/trip_route' + query)
        .then((response) => response.ok ? response.json() : Promise.reject(response))
        .then((route) => {
            const routeLayer = L.layerGroup();
            L.geoJSON(route.shape, {
                style: { color: '#e63946', weight: 5, opacity: 0.85 }
            }).addTo(routeLayer);
            L.geoJSON(route.stops, {
                pointToLayer: (feature, location) => L.circleMarker(location, {
                    radius: 4, color: '#1d2939', weight: 1, fillColor: '#ffffff', fillOpacity: 1
                }),
                onEachFeature: (feature, layer) => layer.bindTooltip(
                    feature.properties.sequence + '. ' + feature.properties.name
                )
            }).addTo(routeLayer);
            routeLayer.addTo(map);
            window.selectedBusRoute = routeLayer;
        })
        .catch(() => console.warn('Route data is unavailable for this trip.'));
};
</script>
"""


def current_geojson(target=None):
    """Fetch the current feed and convert it to GeoJSON."""
    try:
        return vehicles_to_geojson(fetch_feed(), target)
    except requests.RequestException as error:
        app.logger.error("Error fetching vehicle data: %s", error)
        return EMPTY_GEOJSON.copy()


@app.route("/bus_data.geojson")
def get_geojson_data():
    data = current_geojson(request.args.get("bus"))
    return jsonify(data)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/trip_route")
def get_trip_route():
    trip_id = request.args.get("trip_id", "")
    route_id = request.args.get("route_id") or None
    direction_id = request.args.get("direction_id") or None
    if not trip_id:
        return jsonify({"error": "trip_id is required"}), 400
    if not TRIP_ID_PATTERN.fullmatch(trip_id):
        return jsonify({"error": "invalid trip_id"}), 400
    try:
        return jsonify(trip_route(trip_id, route_id, direction_id))
    except KeyError:
        return jsonify({"error": "trip not found"}), 404
    except OSError as error:
        app.logger.error("Error reading static GTFS data: %s", error)
        return jsonify({"error": "static GTFS data unavailable"}), 503


def route_selector_html(active_routes, target):
    """Build the small route filter rendered above the map."""
    options = ['<option value="/">All Buses</option>']
    for route in active_routes:
        selected = " selected" if target == route else ""
        route_text = html.escape(route)
        route_url = quote(route, safe="")
        options.append(
            f'<option value="/?bus={route_url}"{selected}>{route_text}</option>'
        )

    return (
        '<div style="position:fixed;top:10px;left:70px;z-index:1000;'
        'background:#fff;padding:10px;border:2px solid grey;border-radius:5px;'
        'font-family:sans-serif">'
        '<b>Filter by Route:</b><br>'
        '<select id="route_selector" onchange="window.location.href=this.value">'
        + "".join(options)
        + "</select></div>"
    )


@app.route("/")
def index():
    target = request.args.get("bus")
    data_url = "/bus_data.geojson"
    map_title = "Live Tracking: All Active Buses"
    if target:
        data_url += f"?bus={quote(target, safe='')}"
        map_title = f"Live Tracking: Bus/Route {html.escape(target)}"

    try:
        active_routes = route_ids(fetch_feed())
    except requests.RequestException as error:
        app.logger.error("Error fetching route list: %s", error)
        active_routes = []

    bus_map = folium.Map(location=MAP_CENTER, zoom_start=12)
    Realtime(
        data_url,
        interval=10000,
        point_to_layer=folium.JsCode(
            """function (feature, latlng) {
                const properties = feature.properties || {};
                const busId = String(properties.id || 'Unknown');
                const routeId = String(properties.route_id || 'N/A');
                const tripId = String(properties.trip_id || '');
                const directionId = properties.direction_id;
                const bearing = Number(properties.bearing) || 0;
                const escapeHtml = (value) => value.replace(/[&<>'\"]/g, (char) => ({
                    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
                }[char]));
                const icon = L.divIcon({
                    className: 'bus-marker-wrapper',
                    iconSize: [80, 68],
                    iconAnchor: [40, 34],
                    html: `<div class="bus-marker">
                        <span class="bus-label">${escapeHtml(routeId)}</span>
                        <svg class="bus-icon" viewBox="0 0 40 48" aria-hidden="true"
                             style="transform: rotate(${bearing}deg)">
                            <rect x="8" y="3" width="24" height="40" rx="7" fill="#f4c542" stroke="#1d2939" stroke-width="2"/>
                            <path d="M11 12h18v10H11z" fill="#b9e6f2" stroke="#1d2939" stroke-width="1.5"/>
                            <path d="M12 27h16" stroke="#1d2939" stroke-width="2"/>
                            <circle cx="12" cy="43" r="3" fill="#1d2939"/>
                            <circle cx="28" cy="43" r="3" fill="#1d2939"/>
                            <path d="M20 4v5" stroke="#1d2939" stroke-width="2"/>
                        </svg>
                    </div>`
                });
                const marker = L.marker(latlng, { icon: icon }).bindPopup(
                    '<b>Bus ID:</b> ' + escapeHtml(busId) +
                    '<br><b>Route:</b> ' + escapeHtml(routeId)
                );
                marker.on('click', function () {
                    window.showBusRoute(this._map, tripId, routeId, directionId);
                });
                return marker;
            }"""
        ),
    ).add_to(bus_map)
    folium.Marker(
        location=MAP_CENTER,
        popup=f"Initial Center Point<hr>{map_title}",
        icon=folium.Icon(color="red"),
    ).add_to(bus_map)
    bus_map.get_root().header.add_child(folium.Element(BUS_MARKER_CSS))
    bus_map.get_root().html.add_child(folium.Element(ROUTE_SCRIPT))
    bus_map.get_root().html.add_child(
        folium.Element(route_selector_html(active_routes, target))
    )
    map_html = bus_map._repr_html_()
    return map_html.replace(
        "height:0;padding-bottom:60%;",
        "height:100vh;height:100dvh;padding-bottom:0;",
    )


if __name__ == "__main__":
    print("Starting Flask server. Go to 127.0.0.1")
    print("To track a specific bus, visit 127.0.0.1?bus=BUS_ID_HERE")
    app.run(
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5001")),
        use_reloader=False,
    )