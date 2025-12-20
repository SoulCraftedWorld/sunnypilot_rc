#!/usr/bin/env python3

import asyncio
import dataclasses
import json
import logging
import os
import ssl
import subprocess

import signal

import wave
from aiohttp import web, ClientSession , ClientTimeout
import time
from typing import Literal, Dict, Optional, Tuple
from openpilot.common.basedir import BASEDIR
from openpilot.system.webrtc.webrtcd import StreamRequestBody
from openpilot.common.params import Params

from openpilot.tools.webterminal.remote_control_controller import RemoteControlController
from openpilot.tools.webterminal.remote_control_mux import JoystickCommands

logger = logging.getLogger("webterminal")
logging.basicConfig(level=logging.INFO)

WEBTERMINALDIR = f"{BASEDIR}/tools/webterminal"
WEBRTCD_HOST = "localhost"
WEBRTCD_PORT = 5001

WEB_HOST = "0.0.0.0"
WEB_PORT = 80

UDP_LISTEN_PORT = 14550
UDP_TELEMETRY_POPRT = 14551

CameraName = Literal["road", "wideRoad", "driver"]

# текущая камера по умолчанию
CAMERA_SELECT = "wideRoad"  #"driver", "wideRoad", "road"

remote_controller = None

def now_ns() -> int:
  return time.monotonic_ns()

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


## ENDPOINTS
# async def ping(request: 'web.Request'):
#   return web.Response(text="pong")
async def ping(request: 'web.Request') -> web.Response:
  global remote_controller

  # принимать client_id и через header, и через query/body
  client_id = request.headers.get("X-Client-ID") or request.query.get("client_id") or "unknown"
  client_id = str(client_id).strip()[:128]

  # кто пришёл
  peer = request.transport.get_extra_info("peername")
  ip = peer[0] if isinstance(peer, tuple) and len(peer) > 0 else "unknown"

  if remote_controller.on_web_msg(msg=None, client_id=client_id, ip=ip):
    is_master = True
  else:
    is_master = False

  return web.json_response({
    "ok": True,
    "pong": True,
    "client_id": client_id,
    "is_master": is_master
  })

async def ctrl(request: 'web.Request'):
  global remote_controller
  try:
    json_msg = await request.json()
    if "steering_angle_deg" not in json_msg or "brake_and_accel" not in json_msg or "control_enabled" not in json_msg:
      return web.json_response({"ok": False, "error": f"missing steering_angle_deg or brake_and_accel in request: {json_msg}"}, status=400)
  except Exception as e:
    return web.json_response({"ok": False, "error": f"/ctrl bad request: {e}; {request} "}, status=400)

  msg: JoystickCommands = JoystickCommands(
    seq=int(json_msg.get("seq", 0)),
    steering_angle_deg=float(json_msg.get("steering_angle_deg", 0.0)),
    brake_and_accel=float(json_msg.get("brake_and_accel", 0.0)),
    control_enabled=bool(json_msg.get("control_enabled", False)),
    cruise_manual_set=bool(json_msg.get("cruise_manual_set", False)),
    ext_flags=[bool(x) for x in json_msg.get("ext_flags", [False, False, False, False])]
  )

  # принимать client_id и через header, и через query/body
  client_id = request.headers.get("X-Client-ID") or request.query.get("client_id") or "unknown"
  client_id = str(client_id).strip()[:128]
  peer = request.transport.get_extra_info("peername")
  ip = peer[0] if isinstance(peer, tuple) and len(peer) > 0 else "unknown"

  if remote_controller.on_web_msg(msg=msg, client_id=client_id, ip=ip):
    is_master = True
  else:
    is_master = False

  answer = {
    "type": "ctrl_ack",
    "ok": True,
    "is_master": is_master
  }
  return web.json_response(answer)

async def index(request: 'web.Request'):
  with open(os.path.join(WEBTERMINALDIR, "static", "index.html")) as f:
    content = f.read()
    return web.Response(content_type="text/html", text=content)

async def status(request: web.Request) -> web.Response:
  global remote_controller
  snaps: Dict[str, SnapshotInfo] = remote_controller.snapshots()
  snaps['cameras'] = {
    "default": CAMERA_SELECT,
    "available": ["road", "wideRoad", "driver"]
  }
  return web.json_response({"ok": True, **snaps})


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
  sub_chanals = params.get("sub_chanals", [])
  pub_chanals = [x for x in pub_chanals if isinstance(x, str)]
  sub_chanals = [x for x in sub_chanals if isinstance(x, str)]

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


def main():
  global remote_controller
  # joystick debug mode for remote control mode
  Params().put_bool("JoystickDebugMode", False)  # True

  remote_controller = RemoteControlController(
    listen_host=WEB_HOST,
    listen_port=UDP_LISTEN_PORT,
    # target_host=None, # (WEB_HOST, UDP_TELEMETRY_POPRT)
    send_port=UDP_TELEMETRY_POPRT,
    # udp_publish_rate=UDP_PUBLISH_HZ,
    # cereal_publish_rate=CEREAL_PUBLISH_HZ,
    on_control_mode_change_p=on_control_mode_change,
    logger=logger.error
  )
  remote_controller.start()

  # App needs to be HTTPS for microphone and audio autoplay to work on the browser
  ssl_context = create_ssl_context()

  app = web.Application()
  app.router.add_get("/", index)
  app.router.add_get("/ping", ping, allow_head=True)
  app.router.add_get("/status", status)
  app.router.add_post("/offer", offer)
  app.router.add_post("/ctrl", ctrl)
  app.router.add_static('/static', os.path.join(WEBTERMINALDIR, 'static'))
  web.run_app(app, access_log=None, host=WEB_HOST, port=WEB_PORT, ssl_context=ssl_context)


if __name__ == "__main__":
  main()
