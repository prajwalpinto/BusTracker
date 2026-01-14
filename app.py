from flask import Flask, jsonify, request, render_template_string
import requests
from google.transit import gtfs_realtime_pb2
import pandas as pd
import time
import os
import json

app = Flask(__name__)

# --- Configuration ---
FEED_URL = 'https://gtfs.halifax.ca/realtime/Vehicle/VehiclePositions.pb'
DATA_FOLDER = 'data'
GEOJSON_FILENAME = 'bus_positions.geojson'

# Ensure the data folder exists
if not os.path.exists(DATA_FOLDER):
    os.makedirs(DATA_FOLDER)

def fetch_and_convert_to_geojson(target_bus_id=None):
    """
    Fetches the PB data, parses it, and returns GeoJSON,
    optionally filtered by a target_bus_id.
    """
    feed = gtfs_realtime_pb2.FeedMessage()
    try:
        response = requests.get(FEED_URL, allow_redirects=True, timeout=5)
        response.raise_for_status()
        feed.ParseFromString(response.content)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        return {"type": "FeatureCollection", "features": []}

    features = []
    for entity in feed.entity:
        if entity.HasField('vehicle'):
            vehicle = entity.vehicle
            if vehicle.HasField('position'):
                # Extracting ID, defaulting to entity ID if vehicle ID is missing
                bus_id = vehicle.vehicle.id if vehicle.HasField('vehicle') and vehicle.vehicle.HasField('id') else entity.id
                route_id = vehicle.trip.route_id if vehicle.HasField('trip') and vehicle.trip.HasField('route_id') else 'N/A'
                
                # Filter if a specific target is set and matches either bus_id or route_id
                if target_bus_id is None or bus_id == target_bus_id or route_id == target_bus_id:
                    feature = {
                        "type": "Feature",
                        "properties": {
                            "id": bus_id,
                            "route_id": route_id,
                            "bearing": vehicle.position.bearing,
                            "timestamp": feed.header.timestamp
                        },
                        "geometry": {
                            "type": "Point",
                            "coordinates": [vehicle.position.longitude, vehicle.position.latitude]
                        }
                    }
                    features.append(feature)

    return {"type": "FeatureCollection", "features": features}

@app.route('/bus_data.geojson')
def get_geojson_data():
    """
    API endpoint that returns fresh GeoJSON data, and saves it to a file.
    Reads 'bus' parameter from the URL query string.
    """
    target_bus = request.args.get('bus', None)
    
    geojson_data = fetch_and_convert_to_geojson(target_bus_id=target_bus)
    
    # --- NEW: Save the generated GeoJSON data to a file ---
    file_path = os.path.join(DATA_FOLDER, GEOJSON_FILENAME)
    try:
        with open(file_path, 'w') as f:
            json.dump(geojson_data, f, indent=4)
        print(f"Saved current GeoJSON data to {file_path}")
    except IOError as e:
        print(f"Error saving GeoJSON file: {e}")
    # --- END NEW ---

    return jsonify(geojson_data), 200, {'Content-Type': 'application/json'}

@app.route('/')
def index():
    """
    Generates the initial HTML page with the real-time map.
    Reads 'bus' parameter from the URL to determine which bus(es) to show.
    """
    import folium
    from folium.plugins import Realtime

    target_bus = request.args.get('bus', None)

    data_url = '/bus_data.geojson'
    if target_bus:
        data_url = f'/bus_data.geojson?bus={target_bus}'
        map_title = f"Live Tracking: Bus/Route {target_bus}"
    else:
        map_title = "Live Tracking: All Active Buses"

    m = folium.Map(location=[44.6488, -63.5752], zoom_start=12) 

    Realtime(
        data_url,  # This is the required positional 'source' argument
        interval=10000,
        point_to_layer=folium.JsCode("""
            function (feature, latlng) {
                return L.marker(latlng).bindPopup(
                    '<b>Bus ID:</b> ' + feature.properties.id + 
                    '<br><b>Route:</b> ' + feature.properties.route_id
                );
            }
        """)
    ).add_to(m)

    folium.Marker(
        location=[44.6488, -63.5752],
        popup=f"Initial Center Point<hr>{map_title}",
        icon=folium.Icon(color='red')
    ).add_to(m)

    return m._repr_html_()

if __name__ == '__main__':
    print(f"Starting Flask server. Go to 127.0.0.1")
    print(f"To track a specific bus, visit 127.0.0.1?bus=BUS_ID_HERE")
    app.run(debug=True, use_reloader=False)
