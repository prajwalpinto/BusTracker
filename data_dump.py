import requests
import os
import json
from google.transit import gtfs_realtime_pb2
# Import the specific module for converting protobuf message to JSON
from google.protobuf.json_format import MessageToJson 

# --- Configuration ---
FEED_URL = 'https://gtfs.halifax.ca/realtime/Vehicle/VehiclePositions.pb'
DATA_FOLDER = 'data'
FULL_JSON_FILENAME = 'full_feed_dump.json'

def dump_full_pb_to_json():
    """Fetches the raw PB data and saves the complete protobuf structure as JSON."""
    
    # Ensure the data folder exists
    if not os.path.exists(DATA_FOLDER):
        os.makedirs(DATA_FOLDER)
        print(f"Created directory: {DATA_FOLDER}")

    feed = gtfs_realtime_pb2.FeedMessage()
    print(f"Attempting to fetch data from: {FEED_URL}")

    try:
        response = requests.get(FEED_URL, allow_redirects=True, timeout=10)
        response.raise_for_status() # Check for bad responses (404, 403, etc.)
        feed.ParseFromString(response.content)
        
        # Convert the entire FeedMessage object to a JSON string
        # Removed 'including_default_value_fields=True' for compatibility with older libraries
        full_json_string = MessageToJson(feed, indent=4) 
        
        file_path = os.path.join(DATA_FOLDER, FULL_JSON_FILENAME)
        
        with open(file_path, 'w') as f:
            f.write(full_json_string)
        
        print("-" * 40)
        print(f"SUCCESS: Full protobuf dump saved to: {file_path}")
        print(f"You can now open '{file_path}' to review all parameters.")
        print("-" * 40)

    except requests.exceptions.RequestException as e:
        print(f"ERROR fetching data: {e}")
    except IOError as e:
        print(f"ERROR saving file: {e}")


if __name__ == '__main__':
    dump_full_pb_to_json()
