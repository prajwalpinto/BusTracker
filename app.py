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
    font-size:25px;
}
.route-filter {
    position: fixed;
    top: 14px;
    left: 70px;
    z-index: 1000;
    padding: 12px 14px;
    border: 1px solid rgba(23, 43, 77, 0.28);
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.96);
    box-shadow: 0 3px 12px rgba(23, 43, 77, 0.2);
    color: #172b4d;
    font: 700 16px/1.3 sans-serif;
}
.route-filter select {
    display: block;
    min-width: 150px;
    margin-top: 6px;
    padding: 5px 8px;
    border: 1px solid #9aa9bf;
    border-radius: 8px;
    background: #ffffff;
    color: #172b4d;
    font: inherit;
}
.bus-marker {
    width: 100px;
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
    width: 72px;
    height: 48px;
    transform-origin: 36px 24px;
    filter: drop-shadow(0 2px 2px rgba(0, 0, 0, 0.35));
}
.bus-popup .leaflet-popup-content {
    margin: 16px 18px;
    font-size: 18px;
    line-height: 1.6;
}
.current-location-control {
    width: 48px;
    height: 48px;
    border: 2px solid #0757c9 !important;
    border-radius: 8px !important;
    background: #ffffff;
    color: #0757c9;
    cursor: pointer;
    font-size: 30px;
    line-height: 42px;
    text-align: center;
}
.current-location-control:hover {
    background: #e8f1ff;
}
@media (max-width: 600px) {
    .bus-marker {
        transform: scale(1.8);
        transform-origin: center center;
    }
    .bus-label {
        max-width: 106px;
        padding: 4px 8px;
        border-width: 2px;
        font-size: 20px;
        line-height: 24px;
    }
    .bus-popup .leaflet-popup-content {
        margin: 18px 20px;
        font-size: 24px;
        line-height: 1.55;
    }
    .current-location-control {
        width: 58px;
        height: 58px;
        font-size: 36px;
        line-height: 50px;
    }
    #route_selector {
        min-height: 44px;
        padding: 6px 10px;
        font-size: 20px;
    }
    .route-filter {
        top: 10px;
        left: 52px;
        padding: 10px 12px;
        font-size: 20px;
    }
    .route-filter select {
        min-width: 190px;
        min-height: 48px;
        margin-top: 8px;
        padding: 6px 10px;
        font-size: 22px;
    }
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


def location_script(map_name):
    """Return a client-side location helper for the rendered map."""
    return f"""
    <script>
    window.addEventListener('load', function () {{
        const map = {map_name};
        let currentLocation = null;
        let currentLocationMarker = null;

        const locationControl = L.control({{ position: 'bottomright' }});
        locationControl.onAdd = function () {{
            const button = L.DomUtil.create(
                'button', 'current-location-control leaflet-bar'
            );
            button.type = 'button';
            button.title = 'Center on my location';
            button.setAttribute('aria-label', 'Center on my location');
            button.innerHTML = '&#8853;';
            L.DomEvent.disableClickPropagation(button);
            L.DomEvent.on(button, 'click', function () {{
                if (currentLocation) {{
                    map.setView(currentLocation, map.getZoom());
                }} else if (navigator.geolocation) {{
                    navigator.geolocation.getCurrentPosition(updateLocation);
                }}
            }});
            return button;
        }};
        locationControl.addTo(map);

        function updateLocation(position) {{
            currentLocation = [
                position.coords.latitude,
                position.coords.longitude
            ];
            map.setView(currentLocation, map.getZoom());
            if (currentLocationMarker) map.removeLayer(currentLocationMarker);
            currentLocationMarker = L.circleMarker(currentLocation, {{
                radius: 12,
                color: '#ffffff',
                weight: 4,
                fillColor: '#1976d2',
                fillOpacity: 1
            }}).addTo(map).bindPopup('Your current location');
        }}

        if (!navigator.geolocation) return;

        navigator.geolocation.getCurrentPosition(
            updateLocation,
            function () {{
                // Permission denied or unavailable: keep the Halifax map center.
            }},
            {{ enableHighAccuracy: false, timeout: 8000, maximumAge: 300000 }}
        );
    }}, {{ once: true }});
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
        '<div class="route-filter">'
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

    bus_map = folium.Map(location=MAP_CENTER, zoom_start=14, zoom_control=False)
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
                const occupancy = properties.occupancy_percentage == null
                    ? 'Unavailable' : properties.occupancy_percentage + '%';
                const occupancyStatus = properties.occupancy_status
                    ? String(properties.occupancy_status).replaceAll('_', ' ')
                    : 'Unavailable';
                const odometer = properties.odometer == null
                    ? 'Unavailable' : (properties.odometer).toFixed(1) + ' km';
                const speed = properties.speed == null
                    ? 'Unavailable' : (properties.speed).toFixed(1) + ' km/h';
                const escapeHtml = (value) => value.replace(/[&<>'\"]/g, (char) => ({
                    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
                }[char]));
                const icon = L.divIcon({
                    className: 'bus-marker-wrapper',
                    iconSize: [100, 68],
                    iconAnchor: [50, 34],
                    html: `<div class="bus-marker">
                        <span class="bus-label">${escapeHtml(routeId)}</span>
                        <svg class="bus-icon" viewBox="0 0 72 48" aria-hidden="true"
                             style="transform: rotate(${bearing - 90}deg)">
                            <path d="M7 14c0-4 3-7 7-7h43c4 0 7 3 8 7l3 19c.4 3-2 6-5 6H11c-2 0-4-2-4-4V14z" fill="#f6c945" stroke="#172b4d" stroke-width="2.5"/>
                            <path d="M13 11h41c2.5 0 4.5 1.8 5 4.2L60 24H13V11z" fill="#9ed9e8" stroke="#172b4d" stroke-width="2"/>
                            <path d="M22 11v13M32 11v13M42 11v13M52 11v13" stroke="#172b4d" stroke-width="1.5"/>
                            <path d="M60 12c2.5 1 4 3 4.5 5.5L66 24H60V12z" fill="#d8f2f6" stroke="#172b4d" stroke-width="2"/>
                            <rect x="25" y="28" width="22" height="6" rx="1.5" fill="#fff3a6" stroke="#172b4d" stroke-width="1.5"/>
                            <path d="M9 28h8M52 28h12" stroke="#172b4d" stroke-width="2"/>
                            <circle cx="19" cy="39" r="7" fill="#172b4d"/>
                            <circle cx="19" cy="39" r="3.5" fill="#6aa0bf"/>
                            <circle cx="55" cy="39" r="7" fill="#172b4d"/>
                            <circle cx="55" cy="39" r="3.5" fill="#6aa0bf"/>
                        </svg>
                    </div>`
                });
                const marker = L.marker(latlng, { icon: icon });
                marker.on('click', function () {
                    window.showBusRoute(this._map, tripId, routeId, directionId);
                });
                marker.bindPopup(
                    '<b>Bus ID:</b> ' + escapeHtml(busId) +
                    '<br><b>Route:</b> ' + escapeHtml(routeId) +
                    '<br><b>Occupancy:</b> ' + occupancy +
                    '<br><b>Occupancy status:</b> ' + escapeHtml(occupancyStatus) +
                    '<br><b>Odometer:</b> ' + odometer +
                    '<br><b>Speed:</b> ' + speed
                    , { className: 'bus-popup' }
                );
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
        folium.Element(location_script(bus_map.get_name()))
    )
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