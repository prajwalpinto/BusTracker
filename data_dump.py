from pathlib import Path

from google.protobuf.json_format import MessageToJson

from transit import FEED_URL, fetch_feed

OUTPUT_PATH = Path(__file__).parent / "data" / "full_feed_dump.json"


def dump_full_pb_to_json():
    """Fetch and save the complete protobuf feed as JSON."""
    print(f"Attempting to fetch data from: {FEED_URL}")
    try:
        feed = fetch_feed(timeout=10)
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(MessageToJson(feed, indent=4))
    except OSError as error:
        print(f"ERROR saving file: {error}")
        return
    except Exception as error:
        print(f"ERROR fetching data: {error}")
        return

    print(f"SUCCESS: Full protobuf dump saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    dump_full_pb_to_json()