import asyncio
import threading
import time
import cereal.messaging as messaging
from typing import Optional, Tuple, List, Dict, Any, Callable

from openpilot.tools.webterminal.udp_bridge import UdpJoyTelemetryBridge
from openpilot.tools.webterminal.web_client_handler import ClientRegistry, SnapshotInfo, SnapshotClientInfo
from openpilot.tools.webterminal.remote_control_mux import RemoteControlMux, JoystickCommands, MuxedJoystick

CEREAL_PUBLISH_HZ = 40  # 25 ms
UDP_PUBLISH_HZ = 5  # 200ms


GearShifterNames =[
    "unknown",
    "park",
    "drive",
    "neutral",
    "reverse",
    "sport",
    "low",
    "brake",
    "eco",
    "manumatic",
    "undefined_10",
    "undefined_11",
    "undefined_12",
    "undefined_13",
    "undefined_14",
    "undefined_15"
  ]



def monotonic_ns() -> int:
  return time.monotonic_ns()

class RemoteControlController:

  def __init__(self,
               listen_host="0.0.0.0",
               listen_port=14550,
               target_host=None,
               send_port=14551,
               udp_publish_rate: int =UDP_PUBLISH_HZ,
               cereal_publish_rate: int =CEREAL_PUBLISH_HZ,
               on_control_mode_change_p: Optional[Callable[[bool], None]] = None,
               logger=print
               ) -> None:
    self.webClientRegistry = ClientRegistry(timeout_ms=800, kind='web')
    self.udpClientRegistry = ClientRegistry(timeout_ms=500, kind='udp')

    # 1) Mux (если web тоже обновляет команды — дергай mux.update_from_web(...))
    self.mux = RemoteControlMux(udp_timeout_ms=200, web_timeout_ms=500, on_control_mode_change_p = on_control_mode_change_p)

    self.logger = logger

    if target_host is not None and target_host != "0.0.0.0" and target_host != "":
      use_last_sender_as_peer = False
      telemetry_peer: Tuple[str, int] = (target_host, send_port)
    else:
      use_last_sender_as_peer = True
      telemetry_peer = None

    # 2) UDP bridge (socket + protocol)
    self.udp = UdpJoyTelemetryBridge(
      listen_host=listen_host,
      listen_port=listen_port,
      send_port=send_port,
      publisher_p=self.on_udp_msg,
      telemetry_peer=telemetry_peer,
      use_last_sender_as_peer=use_last_sender_as_peer,
      logger=logger
    )

    # 3) cereal pub/sub
    self.pm = messaging.PubMaster(["testJoystick"])
    self.sm = messaging.SubMaster(["carState", "controlsState", "carControl"], ignore_avg_freq=True)

    self.loop_period = 1.0 / float(cereal_publish_rate)
    self.udp_publish_period_ns = int(1e9 / float(udp_publish_rate))
    self.udp_publish_timestamp_ns = 0

    self.last_mj = None

    self._thread = None
    self._stop = threading.Event()


  def _log(self, msg: str) -> None:
    if self.logger:
      self.logger(msg)

  def on_udp_msg(self,  msg: Optional[JoystickCommands], client_id: str)-> bool:
    # Only if message by master
    if self.udpClientRegistry.touch(client_id=client_id, ip=client_id):
      if msg is not None:
        self.mux.update_from_udp(msg)
      return True
    return False

  def on_web_msg(self,  msg: Optional[JoystickCommands], client_id: str, ip: str)-> bool:
    if self.webClientRegistry.touch(client_id=client_id, ip=ip):
      if msg is not None:
        self.mux.update_from_web(msg)
      return True
    return False

  def start(self) -> None:
    self._thread = threading.Thread(target=lambda: asyncio.run(self.run()), daemon=True)
    self._thread.start()

  def stop(self) -> None:
    self._stop.set()
    if self._thread is not None:
      self._thread.join(timeout=2.0)
      self._thread = None

  async def run(self) -> None:
    # Start UDP socket
    await self.udp.start()

    while not self._stop.is_set():
      try:

        # --- mux select ---
        mj: Optional[MuxedJoystick] = self.mux.get()

        if mj is not None:
          # --- publish to testJoystick ---
          msg = messaging.new_message("testJoystick")
          msg.testJoystick.axes = mj.axes
          msg.testJoystick.buttons = mj.buttons
          self.pm.send("testJoystick", msg)
          self.last_mj = msg
        elif self.last_mj is not None:
          # --- republish last ---
          msg = messaging.new_message("testJoystick")
          msg.testJoystick.axes = [0.0, 0.0]
          msg.testJoystick.buttons = [False, False, False, False, False, False, False]
          self.pm.send("testJoystick", msg)
          self.last_mj = None

        now_ns = monotonic_ns()

        if (now_ns - self.udp_publish_timestamp_ns) >= self.udp_publish_period_ns:
          self.udp_publish_timestamp_ns = now_ns

          # --- purge dead clients and check if any alive---
          if self.udpClientRegistry.has_live_master() or self.webClientRegistry.has_live_master():
            # --- collect and send telemetry ---
            telemetry = self.collect_telemetry(now_ns)
            if telemetry  is not None:
              self.udp.send_telemetry(telemetry)

        await asyncio.sleep(self.loop_period)

      except Exception as e:
        self._log(f"rc_controller:run() exception: {e}")
        await asyncio.sleep(self.loop_period * 4)

  def collect_telemetry(self, now_ns: int)-> Optional[Dict]:
      # --- telemetry out ---
      self.sm.update(0)
      # if not self.sm.updated.get("carState", False):
      #   return None

      # Remote control state for debud use 'controlsState'
      ctrl_s = self.sm["controlsState"]
      car_ctrl = self.sm["carControl"]
      cs = self.sm["carState"]

      telemetry: Dict[str, Any]= {
        "type": "telemetry",
        "t_ns": now_ns,
        "vEgo": float(cs.vEgo),  # best estimate of speed

        "steeringAngleDeg": float(cs.steeringAngleDeg),
        "steering_drv_torque": float(cs.steeringTorque),  # Native CAN units - check for driver applied torque
        "steering_flags": {
          "pressed": bool(cs.steeringPressed),  # is the user overring the steering wheel?
          "disengage": bool(cs.steeringDisengage),
          # more force than steeringPressed, disengages for applicable brands
          "fault_temp": bool(cs.steerFaultTemporary),  # temporary fault in steering
          "fault_perm": bool(cs.steerFaultPermanent)  # permanent fault in steering
        },
        "drv_brake": float(cs.brake),  # this is user pedal only
        "standstill": bool(cs.standstill),  # is vehicle standstill
        "gasPressed": bool(cs.gasPressed),  # this is user pedal only
        "brakePressed": bool(cs.brakePressed),  # this is user pedal only
        "brakeHoldActive": bool(cs.brakeHoldActive),
        "parkingBrake": bool(cs.parkingBrake),
        "cruiseState": {
          "speed": float(cs.cruiseState.speed),
          "enabled": bool(cs.cruiseState.enabled),
          "available": bool(cs.cruiseState.available),
          "standstill": bool(cs.cruiseState.standstill),
          "nonAdaptive": bool(cs.cruiseState.nonAdaptive),
          "speedCluster": float(cs.cruiseState.speedCluster)  # Set speed as shown on instrument cluster
        },

        "canValid": bool(cs.canValid),
        "canTimeout": bool(cs.canTimeout),

        "fuelGauge": float(cs.fuelGauge),  # battery or fuel tank level from [0.0, 1.0]
        "charging": bool(cs.charging),  # is EV currently charging

        "espDisabled": bool(cs.espDisabled),  # is ESP currently disabled
        "accFaulted": bool(cs.accFaulted),  # is ACC faulted
        "carFaultedNonCritical": bool(cs.carFaultedNonCritical),  # some ECU is faulted, but car remains controllable
        "espActive": bool(cs.espActive),  # is ESP currently active
        "vehicleSensorsInvalid": bool(cs.vehicleSensorsInvalid),  # invalid steering angle readings, etc.
        "lowSpeedAlert": bool(cs.lowSpeedAlert),  # lost steering control due to a dynamic min steering speed
        "blockPcmEnable": bool(cs.blockPcmEnable),  # whether to allow PCM to enable this frame

        # "aEgo": float(cs.aEgo),  # best estimate of aCAN cceleration
        # "vCruise": float(cs.vCruise),  # actual set speed
        # "yawRate": float(cs.yawRate),  # best estimate of yaw rate
        # "wheelSpeeds": float(cs.wheelSpeeds),  # [ fl, fr, rl, rr ] in m/s

        # cruiseState @ 10: CruiseState;
        # gearShifter @ 14: GearShifter;
        # # button presses
        # buttonEvents @ 11: List(ButtonEvent);
        # buttonEnable @ 57: Bool;  # user is requesting enable, usually one frame. set if pcmCruise=False
        # leftBlinker @ 20: Bool;
        # rightBlinker @ 21: Bool;
        # genericToggle @ 23: Bool;

        # lock info
        # doorOpen @ 24: Bool;  # ideally includes all doors
        # seatbeltUnlatched @ 25: Bool;  # driver seatbelt -- HARD OFF FOR VOLKSWAGEN

        # blindspot sensors
        # leftBlindspot @ 33: Bool;  # Is there something blocking the left lane change
        # rightBlindspot @ 34: Bool;  # Is there something blocking the right lane change

        "ctrl_state_steerAngleDeg": float(car_ctrl.actuators.steeringAngleDeg),
        "ctrl_state_accel": float(car_ctrl.actuators.accel),  # m/s^2
        "ctrl_state_gas": float(car_ctrl.actuators.gas),  # [0.0, 1.0]
        "ctrl_state_brake": float(car_ctrl.actuators.brake),  # [0.0, 1.0]
        "ctrl_state_torque": float(car_ctrl.actuators.torque),  # [0.0, 1.0]
        "ctrl_state_torqueOutputCan": float(car_ctrl.actuators.torqueOutputCan),  # value sent over can to the car
        "ctrl_state_speed": float(car_ctrl.actuators.speed),  # m/s

        "rc_state_enabled": bool(ctrl_s.enabledDEPRECATED),
        "rc_state_active": bool(ctrl_s.activeDEPRECATED),
        "rc_src": str(self.mux.source_control),  # remote control "udp" | "web" | "none"
        "rc_enabled": bool(self.mux.source_controlled),  # is remote control currently enabled
      }
      gear = getattr(cs.gearShifter, "name", None)
      telemetry["gear"] = gear if gear is not None else str(cs.gearShifter)

      return telemetry

  def snapshots(self) -> Dict[str, SnapshotInfo]:
    web_sp: SnapshotInfo = self.webClientRegistry.snapshot()
    udp_sp: SnapshotInfo = self.udpClientRegistry.snapshot()

    return {
      "web": web_sp,
      "udp": udp_sp}

  def get_source_control(self):
    return self.mux.get_source_control()

async def main() -> None:
  controller = RemoteControlController()
  try:
    await controller.run()
  except asyncio.CancelledError:
    pass


if __name__ == "__main__":
  try:
    asyncio.run(main())
  except KeyboardInterrupt:
    pass
