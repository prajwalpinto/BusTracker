# Bus Tracker

Live Halifax Transit vehicle positions on a Folium map.

## Run

Install the dependencies, then start the Flask app locally:

```sh
python3 -m pip install -r requirements.txt
python3 app.py
```

Open `http://127.0.0.1:5000`. Add `?bus=ROUTE_OR_BUS_ID` to filter the map.

The map asks the browser for location permission and centers on the device when
permission is granted. Otherwise it stays centered on Halifax. Location access
requires HTTPS when deployed; `localhost` works during local development.

## Deploy on Render

Create a Web Service with:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn --bind 0.0.0.0:$PORT app:app`
- Health check path: `/health`

The static GTFS files in `data/` are required for route shapes and stops. Render's
filesystem is ephemeral, so live GeoJSON is kept in memory rather than written on
each request.

To save the complete upstream feed as JSON, run `python3 data_dump.py`.
