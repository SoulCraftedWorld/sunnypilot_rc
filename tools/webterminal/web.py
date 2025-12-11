#!/usr/bin/env python3

import asyncio
import dataclasses
import json
import logging
import os
import ssl
import subprocess

import pyaudio
import wave
from aiohttp import web
from aiohttp import ClientSession , ClientTimeout

from openpilot.common.basedir import BASEDIR
from openpilot.system.webrtc.webrtcd import StreamRequestBody
from openpilot.common.params import Params

logger = logging.getLogger("webterminal")
logging.basicConfig(level=logging.INFO)

WEBTERMINALDIR = f"{BASEDIR}/tools/webterminal"
WEBRTCD_HOST = "localhost"
WEBRTCD_PORT = 5001

SITE_PORT = 8080
#["driver", "wideRoad", "road"]
# "driver": "livestreamDriverEncodeData",
#     "wideRoad": "livestreamWideRoadEncodeData",
#     "road": "livestreamRoadEncodeData",

#"driver", "wideRoad", "road"


CAMERA_SELECT = "road"  #"road"

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

## ENDPOINTS
async def index(request: 'web.Request'):
  with open(os.path.join(WEBTERMINALDIR, "static", "index.html")) as f:
    content = f.read()
    return web.Response(content_type="text/html", text=content)


async def ping(request: 'web.Request'):
  return web.Response(text="pong")

async def offer(request: 'web.Request'):
  try:
    params = await request.json()
    if "sdp" not in params:
      return web.json_response({"ok": False, "error": f"missing sdp in request: {params}"}, status=400)
  except Exception as e:
    return web.json_response({"ok": False, "error": f"bad request: {e}; {request} "}, status=400)

  body = StreamRequestBody(params["sdp"], [CAMERA_SELECT], ["testJoystick"], ["carState"])  #"testJoystick""carState"
  # body_json = json.dumps(dataclasses.asdict(body))
  body_json = dataclasses.asdict(body)
  # body_json = {'sdp': params["sdp"], 'cameras': [CAMERA_SELECT], 'bridge_services_in': [], 'bridge_services_out': ["carState"]}
  webrtcd_url = f"http://{WEBRTCD_HOST}:{WEBRTCD_PORT}/stream"


  try:
    # cloudlog.info("Sending offer to webrtcd...")
    timeout = ClientTimeout(total=15)
    async with ClientSession(timeout=timeout) as session:
      async with session.post(webrtcd_url, json=body_json) as resp:
        text = await resp.text()
        if resp.status != 200:

          logger.warning(f"Offer failed, sending offer to webrtcd... Status: {resp.status}, Body: {text}. request: {params}")
          # Проксируем ошибку как JSON, чтобы фронт красиво её показал
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

  # body_json = json.dumps(dataclasses.asdict(body))
  #
  # logger.info("Sending offer to webrtcd...")
  # webrtcd_url = f"http://{WEBRTCD_HOST}:{WEBRTCD_PORT}/stream"
  # async with ClientSession() as session, session.post(webrtcd_url, data=body_json) as resp:
  #   assert resp.status == 200
  #   answer = await resp.json()
  #   return web.json_response(answer)


def main():
  # Enable joystick debug mode
  simulation_start()
  Params().put_bool("JoystickDebugMode", False)  # True
  # Params().put_bool("RemoteControlMode", True)  # True

  # App needs to be HTTPS for microphone and audio autoplay to work on the browser
  ssl_context = create_ssl_context()

  app = web.Application()
  app.router.add_get("/", index)
  app.router.add_get("/ping", ping, allow_head=True)
  app.router.add_post("/offer", offer)
  app.router.add_static('/static', os.path.join(WEBTERMINALDIR, 'static'))
  web.run_app(app, access_log=None, host="0.0.0.0", port=SITE_PORT, ssl_context=ssl_context)


if __name__ == "__main__":
  main()
