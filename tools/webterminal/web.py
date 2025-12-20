#!/usr/bin/env python3

import asyncio
import dataclasses
import json
import logging
import os
import ssl
import subprocess

import signal
import threading
import threading
import functools
from openpilot.common.realtime import Ratekeeper

import wave
from aiohttp import web
from aiohttp import ClientSession , ClientTimeout
import time
from typing import Literal, Dict, Optional, Tuple
from openpilot.common.basedir import BASEDIR
from openpilot.system.webrtc.webrtcd import StreamRequestBody
from openpilot.common.params import Params

from openpilot.tools.webterminal.udp_bridge import UdpJoyTelemetryBridge
from openpilot.tools.webterminal.remote_control_mux import RemoteControlMux
from openpilot.tools.webterminal.web_client_handler import ClientRegistry, ClientLease

logger = logging.getLogger("webterminal")
logging.basicConfig(level=logging.INFO)

WEBTERMINALDIR = f"{BASEDIR}/tools/webterminal"
WEBRTCD_HOST = "localhost"
WEBRTCD_PORT = 5001

SITE_PORT = 80

UDP_LISTEN_PORT = 14550
UDP_TELEMETRY_POPRT = 14551

CameraName = Literal["road", "wideRoad", "driver"]

# текущая камера по умолчанию
CAMERA_SELECT = "wideRoad"  #"driver", "wideRoad", "road"


registry = ClientRegistry(timeout_ms=1200)
# этот флаг ты дальше используешь в mux логике
web_control_connected: bool = False
any_control_connected: bool = False

def now_ns() -> int:
  return time.monotonic_ns()

def rk_loop(function, hz, exit_event: threading.Event):
  rk = Ratekeeper(hz, None)
  while not exit_event.is_set():
    function()
    rk.keep_time()

## SSL
def create_ssl_cert(cert_path: str, key_path: str):
  try:
    proc = subprocess.run(f'openssl req -x509 -newkey rsa:4096 -nodes -out {cert_path} -keyout {key_path} \
                          -days 365 -subj "/C=US/ST=California/O=terminal/OU=web"',
                          capture_output=True, shell=True)
    proc.check_returncode()
  except subprocess.CalledProcessError as ex:
    raise ValueError(f"Error creating SSL certificate:\n[stdout]\n{proc.stdout.decode()}\n[stderr]\n{proc.stderr.decode()}") from ex


def create_ssl_context():
  cert_path = os.path.join(WEBTERMINALDIR, "cert.pem")
  key_path = os.path.join(WEBTERMINALDIR, "key.pem")
  if not os.path.exists(cert_path) or not os.path.exists(key_path):
    logger.info("Creating certificate...")
    create_ssl_cert(cert_path, key_path)
  else:
    logger.info("Certificate exists!")
  ssl_context = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_SERVER)
  ssl_context.load_cert_chain(cert_path, key_path)

  return ssl_context


def on_control_mode_change(enabled: bool):
  Params().put_bool("JoystickDebugMode", enabled)

async def update_debug_flag(is_connected: bool):
  global any_control_connected
  if any_control_connected != is_connected:
    any_control_connected = is_connected
    current_control_source = registry.get_current_control_source()
    if current_control_source is not None:
      source_name = current_control_source.kind
    else:
      source_name = "none"
    logger.info(f"Any control connected: {any_control_connected}. Current source: {source_name}")
    on_control_mode_change(any_control_connected)

## ENDPOINTS
# async def ping(request: 'web.Request'):
#   return web.Response(text="pong")
async def ping(request: 'web.Request') -> web.Response:
  global web_control_connected

  # принимать client_id и через header, и через query/body
  client_id = request.headers.get("X-Client-ID") or request.query.get("client_id") or "unknown"
  client_id = str(client_id).strip()[:128]

  # кто пришёл
  peer = request.transport.get_extra_info("peername")
  ip = peer[0] if isinstance(peer, tuple) and len(peer) > 0 else "unknown"
  ua = request.headers.get("User-Agent", "")
  kind = "web" #  request.headers.get("X-Client-Kind", request.query.get("kind", "unknown"))
  want_master = (request.headers.get("X-Want-Master", "0") == "1") or (request.query.get("master", "0") == "1")

  lease = registry.touch(client_id=client_id, ip=ip, user_agent=ua, kind=str(kind), want_master=bool(want_master))

  update_debug_flag(True)
  # обновляем флаг
  web_control_connected = registry.has_live_master()
  return web.json_response({
    "ok": True,
    "pong": True,
    "client_id": lease.client_id,
    "is_master": lease.is_master,
    "web_control_connected": web_control_connected,
  })

async def index(request: 'web.Request'):
  with open(os.path.join(WEBTERMINALDIR, "static", "index.html")) as f:
    content = f.read()
    return web.Response(content_type="text/html", text=content)

async def status(request: web.Request) -> web.Response:
  global web_control_connected, any_control_connected
  snap = registry.snapshot()
  web_control_connected = registry.has_live_master()
  snap["web_control_connected"] = web_control_connected
  snap["any_control_connected"] = any_control_connected
  return web.json_response({"ok": True, **snap})

def watchdog_loop():
  while True:
    registry.purge_dead()
    is_connected = registry.has_live_master()
    update_debug_flag(is_connected)
    asyncio.sleep(0.1)


async def offer(request: 'web.Request'):
  global CAMERA_SELECT
  try:
    params = await request.json()
    if "sdp" not in params:
      return web.json_response({"ok": False, "error": f"missing sdp in request: {params}"}, status=400)
  except Exception as e:
    return web.json_response({"ok": False, "error": f"bad request: {e}; {request} "}, status=400)

  # camera selection
  camera_name = params.get("camera", CAMERA_SELECT)
  camera_name = str(camera_name).strip()
  if camera_name not in ("road", "wideRoad", "driver"):
    logger.warning(f"bad camera selected: {camera_name}. Using default {CAMERA_SELECT}")
    camera_name = CAMERA_SELECT

  pub_chanals = params.get("pub_chanals", [])
  if not isinstance(pub_chanals, list):
    pub_chanals = []
  else:
    for pub_chanal in pub_chanals:
      if not isinstance(pub_chanal, str):
        logger.warning(f"bad pub_chanal type: {pub_chanal} ({type(pub_chanal)}). Removing it.")
        pub_chanals.remove(pub_chanal)

  sub_chanals = params.get("sub_chanals", [])
  if not isinstance(sub_chanals, list) or len(sub_chanals) == 0:
    sub_chanals = ["carState"]
  else:
    for sub_chanal in sub_chanals:
      if not isinstance(sub_chanal, str):
        logger.warning(f"bad sub_chanal type: {sub_chanal} ({type(sub_chanal)}). Removing it.")
        sub_chanals.remove(sub_chanal)
    if len(sub_chanals) == 0:
      sub_chanals = ["carState"]

  body = StreamRequestBody(params["sdp"], [camera_name], pub_chanals, sub_chanals)  #["testJoystick"] ["carState"]
  body_json = dataclasses.asdict(body)
  webrtcd_url = f"http://{WEBRTCD_HOST}:{WEBRTCD_PORT}/stream"

  try:
    # cloudlog.info("Sending offer to webrtcd...")
    timeout = ClientTimeout(total=15)
    async with ClientSession(timeout=timeout) as session:
      async with session.post(webrtcd_url, json=body_json) as resp:
        text = await resp.text()
        if resp.status != 200:

          logger.warning(f"Offer failed, sending offer to webrtcd... Status: {resp.status}, Body: {text}. request: {params}")
          # пробрасываем ошибку как JSON, чтобы фронт красиво её показал
          return web.json_response({
            "ok": False,
            "upstream": webrtcd_url,
            "status": resp.status,
            "body": text[:500]
          }, status=502)
        # webrtcd должен вернуть JSON с {'type':'answer','sdp':'...'}
        try:
          answer = await resp.json(content_type=None)
          logger.warning(f"Offer answer: {answer}")
        except Exception:
          # если пришёл JSON, но с кривым content-type
          answer = json.loads(text)
          logger.warning(f"Offer answer error: {answer}")
  except Exception as e:
    logger.warning(f"Offer answer Exception: {e}; Body {body}")
    return web.json_response({"ok": False, "error": f"webrtcd request failed: {e}"}, status=502)

  if not isinstance(answer, dict) or "sdp" not in answer:
    logger.warning(f"Offer hasn't isinstance or sdp not in answer: {answer}")
    return web.json_response({"ok": False, "error": f"invalid answer from webrtcd: {answer}"}, status=502)
  if "type" not in answer:
    answer["type"] = "answer"

  return web.json_response(answer)

remote_mux = None
udp_bridge_thread = None
udp_bridge = None

def on_udp_rx(request: 'web.Request') -> web.Response:

  # принимать client_id и через header, и через query/body
  client_id = request.headers.get("X-Client-ID") or request.query.get("client_id") or "unknown"
  client_id = str(client_id).strip()[:128]

  # кто пришёл
  peer = request.transport.get_extra_info("peername")
  ip = peer[0] if isinstance(peer, tuple) and len(peer) > 0 else "unknown"
  ua = request.headers.get("User-Agent", "")
  kind = "udp"
  want_master = (request.headers.get("X-Want-Master", "0") == "1") or (request.query.get("master", "0") == "1")

  lease = registry.touch(client_id=client_id, ip=ip, user_agent=ua, kind=str(kind), want_master=bool(want_master))

  update_debug_flag(True)
  # обновляем флаг
  web_control_connected = registry.has_live_master()
  return web.json_response({
    "ok": True,
    "pong": True,
    "client_id": lease.client_id,
    "is_master": lease.is_master,
    "web_control_connected": web_control_connected,
  })

async def udp_bridge_process():
  global remote_mux, udp_bridge
  await udp_bridge.start()
  remote_mux = RemoteControlMux(udp_bridge)

def udp_bridge_start():
  global udp_bridge_thread
  _exit_event = threading.Event()
  udp_bridge_thread = threading.Thread(target=rk_loop,
                                               args=(functools.partial(udp_bridge_process),
                                                     10, _exit_event))
  udp_bridge_thread.start()
  # udp_bridge_thread = threading.Thread(target=udp_bridge_process, daemon=True)
  # udp_bridge_thread.start()

def main():
  # Enable joystick debug mode
  Params().put_bool("JoystickDebugMode", False)  # True
  # Params().put_bool("RemoteControlMode", True)  # True
  global udp_bridge
  udp_bridge = UdpJoyTelemetryBridge(listen_port=UDP_LISTEN_PORT)
  udp_bridge_start()

  # App needs to be HTTPS for microphone and audio autoplay to work on the browser
  ssl_context = create_ssl_context()

  app = web.Application()
  app.router.add_get("/", index)
  app.router.add_get("/ping", ping, allow_head=True)
  app.router.add_post("/offer", offer)
  app.router.add_post("/status", status)
  app.router.add_static('/static', os.path.join(WEBTERMINALDIR, 'static'))
  watchdog_thread = threading.Thread(target=watchdog_loop, daemon=True)
  watchdog_thread.start()
  web.run_app(app, access_log=None, host="0.0.0.0", port=SITE_PORT, ssl_context=ssl_context)


if __name__ == "__main__":
  main()
