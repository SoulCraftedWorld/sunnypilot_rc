#!/usr/bin/env python3
import time
import cereal.messaging as messaging
from openpilot.common.params import Params


#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import socket
import struct
import threading
import time
from typing import List, Tuple

from cereal import messaging, log
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog

# ---------- Константы / параметры ----------
PUB_HZ_PANDA = 10.0          # Гц: pandaStates + peripheralState
PUB_HZ_DEVICE = 3.0         # Гц: deviceState
PUB_HZ_CAN = 100.0          # Гц: пульс/кадры в 'can'

DEFAULT_BUS = 0
UDP_INJECT_BIND = ("0.0.0.0", 29092)  # UDP-json для внешней инъекции CAN

# Поведение по умолчанию
LOOPBACK_SENDCAN_DEFAULT = True       # дублировать sendcan в can
PRINT_SENDCAN_DEFAULT = False
PRINT_INJECT_DEFAULT = False
TEST_PATTERN_DEFAULT = False          # шлём тестовый кадр-счётчик

# ---------- Утилиты ----------

def _pack_can_frame(addr: int, data_bytes: bytes, bus: int) -> log.CanData:
  cd = log.CanData.new_message()
  cd.address = int(addr)
  cd.dat = data_bytes
  cd.src = int(bus)
  # busTimeDEPRECATED присутствует, но его можно не трогать — Cap'n Proto подставит 0
  return cd


def _decode_sendcan(sm_sendcan: log.Event) -> List[log.CanData]:
  out = []
  for pkt in sm_sendcan.sendcan:
    cd = log.CanData.new_message()
    cd.address = getattr(pkt, "address", 0)
    raw = getattr(pkt, "dat", b"") or getattr(pkt, "data", b"")
    cd.dat = raw if isinstance(raw, (bytes, bytearray)) else bytes(raw)
    cd.src = getattr(pkt, "src", DEFAULT_BUS)
    out.append(cd)
  return out


# ---------- UDP-инъекция CAN ----------

def _udp_inject_loop(pm: messaging.PubMaster, bind: Tuple[str, int], print_inject: bool):
  sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  sock.bind(bind)
  cloudlog.info(f"[fake_boardd2] UDP inject listening on udp://{bind[0]}:{bind[1]}")
  while True:
    data, _ = sock.recvfrom(65535)
    try:
      obj = json.loads(data.decode("utf-8").strip())
    except Exception as e:
      cloudlog.error(f"[fake_boardd2] UDP inject parse error: {e}")
      continue

    frames: List[log.CanData] = []
    try:
      if isinstance(obj, dict) and "frames" in obj and isinstance(obj["frames"], list):
        for f in obj["frames"]:
          a = int(f["addr"])
          b = int(f.get("bus", DEFAULT_BUS))
          raw = bytes.fromhex(str(f["data"]))
          frames.append(_pack_can_frame(a, raw, b))
      elif isinstance(obj, dict) and "addr" in obj and "data" in obj:
        a = int(obj["addr"])
        b = int(obj.get("bus", DEFAULT_BUS))
        raw = bytes.fromhex(str(obj["data"]))
        frames.append(_pack_can_frame(a, raw, b))
    except Exception as e:
      cloudlog.error(f"[fake_boardd2] bad frame in UDP payload: {e}")
      frames = []

    if frames:
      if print_inject:
        cloudlog.info(f"[fake_boardd2] UDP inject -> {len(frames)} frames")
      msg = messaging.new_message("can", len(frames))
      msg.can = frames
      pm.send("can", msg)

# ---------- Главный эмулятор ----------

def run_fake_boardd2(test_pattern: bool, loopback_sendcan: bool, print_sendcan: bool, print_inject: bool):
  pm = messaging.PubMaster(["pandaStates", "peripheralState",  "can"]) # "deviceState",
  sm = messaging.SubMaster(["sendcan"])

  # UDP-инъектор в отдельном потоке
  # threading.Thread(target=_udp_inject_loop, args=(pm, UDP_INJECT_BIND, print_inject), daemon=True).start()

  rk_panda = Ratekeeper(PUB_HZ_PANDA, print_delay_threshold=None)
  rk_device = Ratekeeper(PUB_HZ_DEVICE, print_delay_threshold=None)
  rk_can = Ratekeeper(PUB_HZ_CAN, print_delay_threshold=None)

  counter = 0
  last_panda = 0.0
  last_device = 0.0
  last_can = 0.0

  cloudlog.info("[fake_boardd2] starting")
  while True:
    # ---- приём sendcan, опциональный loopback ----
    sm.update(0)
    if sm.updated.get("sendcan", False):
      frames = _decode_sendcan(sm["sendcan"])
      if print_sendcan:
        cloudlog.info(f"[fake_boardd2] sendcan {len(frames)} frames")
      if loopback_sendcan and frames:
        msg = messaging.new_message("can", len(frames))
        msg.can = frames
        pm.send("can", msg)

    now = time.monotonic()

    # ---- pandaStates + peripheralState ----
    if now - last_panda >= 1.0 / PUB_HZ_PANDA:
      pst_msg = messaging.new_message("pandaStates", 1)
      ps = pst_msg.pandaStates[0]

      # Тип/модель
      ps.pandaType = log.PandaState.PandaType.whitePanda
      ps.harnessStatus = log.PandaState.HarnessStatus.normal

      # Питание (UInt32 в МИЛЛИ-единицах!)
      # 12.3 В -> 12300 мВ, 200 мА -> 200
      ps.voltage = 12300
      ps.current = 200

      # Зажигание и разрешения
      ps.ignitionLine = True
      ps.ignitionCan = True
      ps.controlsAllowed = True

      # Состояния/флаги
      ps.faultStatus = log.PandaState.FaultStatus.none
      ps.powerSaveEnabled = False
      ps.heartbeatLost = False
      ps.uptime = int(time.time())

      # CAN health по трём шинам
      for idx, can_state in enumerate([ps.canState0, ps.canState1, ps.canState2]):
        can_state.busOff = False
        can_state.busOffCnt = 0
        can_state.errorWarning = False
        can_state.errorPassive = False
        can_state.lastError = log.PandaState.PandaCanState.LecErrorCode.noError
        can_state.lastStoredError = log.PandaState.PandaCanState.LecErrorCode.noError
        can_state.lastDataError = log.PandaState.PandaCanState.LecErrorCode.noError
        can_state.lastDataStoredError = log.PandaState.PandaCanState.LecErrorCode.noError
        can_state.receiveErrorCnt = 0
        can_state.transmitErrorCnt = 0
        can_state.totalErrorCnt = 0
        can_state.totalTxLostCnt = 0
        can_state.totalRxLostCnt = 0
        can_state.totalTxCnt = 0
        can_state.totalRxCnt = 0
        can_state.totalFwdCnt = 0
        can_state.canSpeed = 500  # kbit/s (типично 500 для CAN классики)
        can_state.canDataSpeed = 0
        can_state.canfdEnabled = False
        can_state.brsEnabled = False
        can_state.canfdNonIso = False
        can_state.irq0CallRate = 0
        can_state.irq1CallRate = 0
        can_state.irq2CallRate = 0
        can_state.canCoreResetCnt = 0

      # Переферийное состояние (многие модули его читают)
      per_msg = messaging.new_message("peripheralState")
      per_msg.peripheralState.pandaType = log.PandaState.PandaType.whitePanda
      per_msg.peripheralState.voltage = 12300     # мВ
      per_msg.peripheralState.current = 200       # мА
      per_msg.peripheralState.fanSpeedRpm = 0     # UInt16

      pm.send("pandaStates", pst_msg)
      pm.send("peripheralState", per_msg)

      last_panda = now
      rk_panda.keep_time()

    # ---- deviceState (минимально достаточный набор) ----
    if 1 == 0 and now - last_device >= 1.0 / PUB_HZ_DEVICE:
      ds = messaging.new_message("deviceState")
      ds.deviceState.started = True
      ds.deviceState.startedMonoTime = int(time.time() * 1e9)
      ds.deviceState.freeSpacePercent = 70.0
      ds.deviceState.memoryUsagePercent = 40
      ds.deviceState.gpuUsagePercent = 10
      ds.deviceState.cpuUsagePercent = [5, 7, 4, 8]
      ds.deviceState.thermalStatus = log.DeviceState.ThermalStatus.green
      ds.deviceState.fanSpeedPercentDesired = 0
      ds.deviceState.powerDrawW = 5.0
      ds.deviceState.somPowerDrawW = 3.0
      # сеть — «нет»
      ds.deviceState.networkType = log.DeviceState.NetworkType.none
      ds.deviceState.networkStrength = log.DeviceState.NetworkStrength.unknown
      pm.send("deviceState", ds)

      last_device = now
      rk_device.keep_time()

    # ---- can (пульс/тестовый кадр) ----
    if now - last_can >= 1.0 / PUB_HZ_CAN:
      frames: List[log.CanData] = []
      if test_pattern:
        counter = (counter + 1) & 0xFFFFFFFF
        payload = struct.pack("<I4x", counter)  # 4 байта счётчика + паддинг
        frames.append(_pack_can_frame(0x100, payload, DEFAULT_BUS))

      # Даже пустая публикация полезна как пульс для некоторых подписчиков
      msg = messaging.new_message("can", len(frames))
      msg.can = frames
      pm.send("can", msg)

      last_can = now
      rk_can.keep_time()

class TurnCounter:
  def __init__(self, lower: float, upper: float, step: float, initial_bottom=True):
    self.lower = lower
    self.upper = upper
    self.step = step
    self.value = lower
    self.direction = 1.0
    if not initial_bottom:
      self.value = upper
      self.direction = -1.0

  def update(self) -> float:
    self.value += self.step * self.direction
    if self.value > self.upper:
      self.direction = -1.0
    elif self.value < self.lower:
      self.value = self.lower
      self.direction = 1.0
    return self.value

  def reset(self):
    self.value = self.lower
    self.direction = 1.0

  def get_value(self) -> float:
    return self.value

def fake_board():
  ap = argparse.ArgumentParser(description="Fake boardd/panda for Openpilot (pandaStates/peripheralState/deviceState + CAN)")
  ap.add_argument("--test-pattern", action="store_true", default=TEST_PATTERN_DEFAULT,
                  help="Публиковать тестовый счётчик в CAN (ID 0x100, bus 0)")
  ap.add_argument("--no-loopback", action="store_true",
                  help="Не лупбечить sendcan обратно в can")
  ap.add_argument("--print-sendcan", action="store_true", default=PRINT_SENDCAN_DEFAULT,
                  help="Печатать содержимое sendcan")
  ap.add_argument("--print-inject", action="store_true", default=PRINT_INJECT_DEFAULT,
                  help="Печатать инъекции по UDP")
  args = ap.parse_args()

  run_fake_boardd2(
    test_pattern=bool(args.test_pattern),
    loopback_sendcan=not args.no_loopback,
    print_sendcan=bool(args.print_sendcan),
    print_inject=bool(args.print_inject),
  )

def simulation_task():
  while True:
    pm = messaging.PubMaster(['carParams', 'carState', 'peripheralState', 'pandaStates'])
    sm = messaging.SubMaster(['carParams','carControl', 'controlsState', "testJoystick", "selfdriveState"])
    batt = 1.
    params = Params()

    """
    vEgo @1 :Float32;            # best estimate of speed
  aEgo @16 :Float32;           # best estimate of aCAN cceleration
  vEgoRaw @17 :Float32;        # unfiltered speed from wheel speed sensors
  vEgoCluster @44 :Float32;    # best estimate of speed shown on car's instrument cluster, used for UI

  vCruise @53 :Float32;        # actual set speed
  vCruiseCluster @54 :Float32; # set speed to display in the UI

  yawRate @22 :Float32;     # best estimate of yaw rate
  standstill @18 :Bool;
  wheelSpeeds @2 :WheelSpeeds;

  gasPressed @4 :Bool;    # this is user pedal only

  # brake pedal, 0.0-1.0
  brake @5 :Float32;      # this is user pedal only
  brakePressed @6 :Bool;  # this is user pedal only
  regenBraking @45 :Bool; # this is user pedal only
  parkingBrake @39 :Bool;
  brakeHoldActive @38 :Bool;

  # steering wheel
  steeringAngleDeg @7 :Float32;
  steeringAngleOffsetDeg @37 :Float32; # Offset between sensors in case there multiple
  steeringRateDeg @15 :Float32;    # optional
  steeringTorque @8 :Float32;      # Native CAN units, only needed on cars where it's used for control
  steeringTorqueEps @27 :Float32;  # Native CAN units, only needed on cars where it's used for control
  steeringPressed @9 :Bool;        # is the user overring the steering wheel?
  steeringDisengage @58 :Bool;     # more force than steeringPressed, disengages for applicable brands
  steerFaultTemporary @35 :Bool;
  steerFaultPermanent @36 :Bool;

  invalidLkasSetting @55 :Bool;    # stock LKAS is incorrectly configured (i.e. on or off)
  stockAeb @30 :Bool;
  stockLkas @59 :Bool;
  stockFcw @31 :Bool;
  espDisabled @32 :Bool;
  accFaulted @42 :Bool;
  carFaultedNonCritical @47 :Bool;  # some ECU is faulted, but car remains controllable
  espActive @51 :Bool;
  vehicleSensorsInvalid @52 :Bool;  # invalid steering angle readings, etc.
  lowSpeedAlert @56 :Bool;  # lost steering control due to a dynamic min steering speed
  blockPcmEnable @60 :Bool;  # whether to allow PCM to enable this frame

  # cruise state
  cruiseState @10 :CruiseState;
    """


    steeringAngleTurn = TurnCounter(-540.0, 540.0, 5.0)
    brakeTurn = TurnCounter(0.0, 50.0, 5.0)
    vEgoTurn = TurnCounter(0.0, 100.0, 1.0)
    fuelGaugeTurn = TurnCounter(0.0, 1.0, 0.01, initial_bottom=False)
    #aEgo

    def handle_turn(cur, turn, lower, upper, step):
      cur += step * turn
      if cur > upper:
        turn = -1.0
      elif cur < lower:
        cur = lower
        turn = 1.0
      return cur, turn

    while True:
      params.put("DongleId", "cb38263377b873ee")
      params.put("IsOffroad", True)

      msg = messaging.new_message('carParams')
      msg.carParams.brand = "volkswagen"
      msg.carParams.carFingerprint = "VOLKSWAGEN_GOLF_MK7"
      msg.carParams.notCar = False
      pm.send('carParams', msg)

      sm.update(1)
      testJoystick = sm.recv_frame.get('testJoystick', 0)
      carControl = sm['carControl']

      tj = sm['testJoystick']
      tele_axes = list(tj.axes)
      tele_arm = bool(tj.buttons[0]) if hasattr(tj, 'buttons') and len(tj.buttons) >= 1 else False
      # params.put_bool("JoystickDebugMode", False)

      JoystickDebugMode = params.get_bool("JoystickDebugMode")
      #RemoteControlMode = params.get_bool("RemoteControlMode")
      CP = sm['carParams']
      notCar = CP.notCar

      #message = f"DebugMode {JoystickDebugMode}, RC_Mode {RemoteControlMode}, notCar {notCar}, joystick ({testJoystick}) axes: {tele_axes}, arm: {tele_arm},  Selfdrive: {sm['selfdriveState'].active}, CC En {carControl.enabled}; steerSet:{carControl.actuators.steeringAngleDeg:.1f}; "
      message = f"DebugMode {JoystickDebugMode}, notCar {notCar}, joystick ({testJoystick}) axes: {tele_axes}, arm: {tele_arm},  Selfdrive: {sm['selfdriveState'].active}, CC En {carControl.enabled}; steerSet:{carControl.actuators.steeringAngleDeg:.1f}; "
      print(message)


      for b in range(30, 0, -1):
        msg = messaging.new_message('carState')
        msg.carState.charging = True if b > 50 else False
        msg.carState.fuelGauge = fuelGaugeTurn.update()
        msg.carState.steeringAngleDeg = steeringAngleTurn.get_value()
        msg.carState.brake = brakeTurn.get_value()
        msg.carState.vEgo = vEgoTurn.update()

        pm.send('carState', msg)

        steeringAngleTurn.update()
        brakeTurn.update()
        vEgoTurn.update()
        fuelGaugeTurn.update()

        time.sleep(0.1)

      time.sleep(1)

def simulation_start():

  # start fake_board thread
  threading.Thread(target=fake_board, daemon=True).start()
  threading.Thread(target=simulation_task, daemon=True).start()








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


## UTILS
async def play_sound(sound: str):
  SOUNDS = {
    "engage": "selfdrive/assets/sounds/engage.wav",
    "disengage": "selfdrive/assets/sounds/disengage.wav",
    "error": "selfdrive/assets/sounds/warning_immediate.wav",
  }
  assert sound in SOUNDS

  chunk = 5120
  with wave.open(os.path.join(BASEDIR, SOUNDS[sound]), "rb") as wf:
    def callback(in_data, frame_count, time_info, status):
      data = wf.readframes(frame_count)
      return data, pyaudio.paContinue

    p = pyaudio.PyAudio()
    stream = p.open(format=p.get_format_from_width(wf.getsampwidth()),
                    channels=wf.getnchannels(),
                    rate=wf.getframerate(),
                    output=True,
                    frames_per_buffer=chunk,
                    stream_callback=callback)
    stream.start_stream()
    while stream.is_active():
      await asyncio.sleep(0)
    stream.stop_stream()
    stream.close()
    p.terminate()

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


async def sound(request: 'web.Request'):
  params = await request.json()
  sound_to_play = params["sound"]

  await play_sound(sound_to_play)
  return web.json_response({"status": "ok"})

async def offer2(request: 'web.Request'):
  params = await request.json()
  body = StreamRequestBody(params["sdp"], [CAMERA_SELECT], ["testJoystick"], ["carState"])
  body_json = dataclasses.asdict(body) #json.dumps(dataclasses.asdict(body))

  logger.info("Sending offer to webrtcd...")
  webrtcd_url = f"http://{WEBRTCD_HOST}:{WEBRTCD_PORT}/stream"
  async with ClientSession() as session, session.post(webrtcd_url, data=body_json) as resp:
    assert resp.status == 200
    answer = await resp.json()
    return web.json_response(answer)

async def offer(request: 'web.Request'):
  try:
    params = await request.json()
    if "sdp" not in params:
      return web.json_response({"ok": False, "error": f"missing sdp in request: {params}"}, status=400)
  except Exception as e:
    return web.json_response({"ok": False, "error": f"bad request: {e}; {request} "}, status=400)

  body = StreamRequestBody(params["sdp"], [CAMERA_SELECT], [], [])  #"testJoystick""carState"
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
          logger.warning("Offer failed, sending offer to webrtcd...")
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
  app.router.add_post("/sound", sound)
  app.router.add_static('/static', os.path.join(WEBTERMINALDIR, 'static'))
  web.run_app(app, access_log=None, host="0.0.0.0", port=SITE_PORT, ssl_context=ssl_context)


if __name__ == "__main__":
  main()





import math
import numpy as np

from cereal import messaging, car
from opendbc.car.vehicle_model import VehicleModel
from openpilot.common.realtime import DT_CTRL, Ratekeeper
from openpilot.common.params import Params


LongCtrlState = car.CarControl.Actuators.LongControlState
MAX_LAT_ACCEL = 3.0


def joystickd_thread():
  params = Params()
  logger.info("joystickd is waiting for CarParams")
  CP = messaging.log_from_bytes(params.get("CarParams", block=True), car.CarParams)
  VM = VehicleModel(CP)

  sm = messaging.SubMaster(['carState', 'onroadEvents', 'liveParameters', 'selfdriveState', 'testJoystick'], frequency=1. / DT_CTRL)
  pm = messaging.PubMaster(['carControl', 'controlsState'])

  rk = Ratekeeper(100, print_delay_threshold=None)
  while 1:
    sm.update(0)

    cc_msg = messaging.new_message('carControl')
    cc_msg.valid = True
    CC = cc_msg.carControl
    CC.enabled = sm['selfdriveState'].enabled
    CC.latActive = sm['selfdriveState'].active and not sm['carState'].steerFaultTemporary and not sm['carState'].steerFaultPermanent
    CC.longActive = CC.enabled and not any(e.overrideLongitudinal for e in sm['onroadEvents']) and CP.openpilotLongitudinalControl
    CC.cruiseControl.cancel = sm['carState'].cruiseState.enabled and (not CC.enabled or not CP.pcmCruise)
    CC.hudControl.leadDistanceBars = 2

    actuators = CC.actuators

    # reset joystick if it hasn't been received in a while
    should_reset_joystick = sm.recv_frame['testJoystick'] == 0 or (sm.frame - sm.recv_frame['testJoystick'])*DT_CTRL > 0.2

    if not should_reset_joystick:
      joystick_axes = sm['testJoystick'].axes
    else:
      joystick_axes = [0.0, 0.0]

    if CC.longActive:
      actuators.accel = 4.0 * float(np.clip(joystick_axes[0], -1, 1))
      actuators.longControlState = LongCtrlState.pid if sm['carState'].vEgo > CP.vEgoStopping else LongCtrlState.stopping

    if CC.latActive:
      max_curvature = MAX_LAT_ACCEL / max(sm['carState'].vEgo ** 2, 5)
      max_angle = math.degrees(VM.get_steer_from_curvature(max_curvature, sm['carState'].vEgo, sm['liveParameters'].roll))

      actuators.torque = float(np.clip(joystick_axes[1], -1, 1))
      actuators.steeringAngleDeg, actuators.curvature = actuators.torque * max_angle, actuators.torque * -max_curvature

    pm.send('carControl', cc_msg)

    cs_msg = messaging.new_message('controlsState')
    cs_msg.valid = True
    controlsState = cs_msg.controlsState
    controlsState.lateralControlState.init('debugState')

    lp = sm['liveParameters']
    steer_angle_without_offset = math.radians(sm['carState'].steeringAngleDeg - lp.angleOffsetDeg)
    controlsState.curvature = -VM.calc_curvature(steer_angle_without_offset, sm['carState'].vEgo, lp.roll)

    pm.send('controlsState', cs_msg)

    rk.keep_time()


def main2():
  joystickd_thread()
