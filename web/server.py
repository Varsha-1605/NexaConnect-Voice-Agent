import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path

from aiohttp import web
from dotenv import load_dotenv
from livekit import api

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import AGENT_NAME  # noqa: E402

PAGE = Path(__file__).parent / "index.html"


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(PAGE)


async def token(request: web.Request) -> web.Response:
    room = f"web-{uuid.uuid4().hex[:8]}"
    jwt = (
        api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
        .with_identity(f"customer-{uuid.uuid4().hex[:6]}")
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
                can_publish_sources=["microphone"],
            )
        )
        .with_room_config(
            api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME)])
        )
        .with_ttl(timedelta(minutes=10))
        .to_jwt()
    )
    return web.json_response({"url": os.environ["LIVEKIT_URL"], "token": jwt})


app = web.Application()
app.add_routes(
    [
        web.get("/", index),
        web.post("/api/token", token),
        web.static("/static", Path(__file__).parent / "static"),
    ]
)

if __name__ == "__main__":
    # localhost only
    web.run_app(app, host="127.0.0.1", port=8080)
