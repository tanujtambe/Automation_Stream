import os
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse
import requests

app = FastAPI()

FB_VERIFY_TOKEN = os.getenv("FB_VERIFY_TOKEN", "your-verify-token")
FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN", "")
MAKE_WEBHOOK_URL = os.getenv("MAKE_WEBHOOK_URL", "")

GRAPH_BASE = "https://graph.facebook.com/v21.0"


@app.get("/")
async def root():
    return {"status": "ok", "message": "Facebook Webhook Receiver running"}


# 1) FACEBOOK WEBHOOK VERIFICATION (GET)
@app.get("/fb-webhook")
async def verify_fb_webhook(
    hub_mode: str = None,
    hub_verify_token: str = None,
    hub_challenge: str = None
):
    """
    Facebook sends a GET request here when you first set up the webhook.
    We must echo back the hub_challenge if the verify_token matches.
    """
    if hub_mode == "subscribe" and hub_verify_token == FB_VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge or "")
    return PlainTextResponse("Verification failed", status_code=403)


# 2) FACEBOOK WEBHOOK EVENTS (POST)
@app.post("/fb-webhook")
async def receive_fb_webhook(request: Request):
    """
    Facebook sends POSTs here whenever there is an update (e.g., Page live started/ended).
    We parse it, detect live_video changes, then call Graph API and forward to Make.com.
    """
    data = await request.json()
    print("Received FB webhook:", data)

    # Basic validation
    if data.get("object") != "page":
        return JSONResponse({"status": "ignored", "reason": "not a page object"})

    # data["entry"] is a list of page updates
    entries = data.get("entry", [])
    for entry in entries:
        page_id = entry.get("id")
        changes = entry.get("changes", [])

        for change in changes:
            field = change.get("field")
            value = change.get("value", {})

            # We’re interested in live videos
            # Depending on setup, field might be "live_videos" or "feed" with a live_post
            if field == "live_videos":
                live_video_id = value.get("id")
                status = value.get("status")  # e.g. LIVE, LIVE_STOPPED, etc.
                event_type = value.get("event")  # optional

                print(f"Live video event: id={live_video_id}, status={status}, event={event_type}")

                if live_video_id:
                    handle_live_video_event(page_id, live_video_id, status)

            # Optional: handle "feed" if live is announced via feed posts
            # elif field == "feed":
            #     # Handle other types if you want

    return JSONResponse({"status": "ok"})


def handle_live_video_event(page_id: str, live_video_id: str, status: str):
    """
    Called whenever we get a live_video webhook event.
    We’ll:
      1. Call Graph API for more details (permalink_url, title, etc.)
      2. Post to Make.com webhook with structured payload.
    """
    if not FB_PAGE_ACCESS_TOKEN:
        print("FB_PAGE_ACCESS_TOKEN is not set!")
        return

    # 1) Fetch additional info from Graph
    url = f"{GRAPH_BASE}/{live_video_id}"
    params = {
        "fields": "id,status,title,description,permalink_url,creation_time",
        "access_token": FB_PAGE_ACCESS_TOKEN,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        live_data = resp.json()
    except Exception as e:
        print("Error calling Graph API:", e)
        live_data = {}

    print("Live video details from Graph:", live_data)

    permalink_url = live_data.get("permalink_url")
    title = live_data.get("title")
    description = live_data.get("description")
    creation_time = live_data.get("creation_time")

    # 2) Build payload for Make.com
    payload = {
        "page_id": page_id,
        "live_video_id": live_video_id,
        "status": status,
        "permalink_url": permalink_url,
        "title": title,
        "description": description,
        "creation_time": creation_time,
    }

    # 3) Send to Make.com webhook (if configured)
    if MAKE_WEBHOOK_URL:
        try:
            r = requests.post(MAKE_WEBHOOK_URL, json=payload, timeout=10)
            print("Posted to Make.com:", r.status_code, r.text)
        except Exception as e:
            print("Error posting to Make.com:", e)
    else:
        print("MAKE_WEBHOOK_URL not set, skipping Make.com forward")
