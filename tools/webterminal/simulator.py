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
        try:
          pm.send('carState', msg)
        except Exception as e:
          print(f"simulation_task: pm.send carState exception {e}")

        steeringAngleTurn.update()
        brakeTurn.update()
        vEgoTurn.update()
        fuelGaugeTurn.update()

        time.sleep(0.1)

      time.sleep(1)

def main():
  # Enable joystick debug mode
  Params().put_bool("JoystickDebugMode", False)  # True
  threading.Thread(target=fake_board, daemon=True).start()
  threading.Thread(target=simulation_task, daemon=True).start()


if __name__ == "__main__":
  main()
