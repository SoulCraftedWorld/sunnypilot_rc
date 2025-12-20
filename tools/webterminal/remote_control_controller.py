import asyncio
import time
import cereal.messaging as messaging

from openpilot.tools.webterminal.udp_bridge import UdpJoyTelemetryBridge
from openpilot.tools.webterminal.web_client_handler import ClientRegistry
from openpilot.tools.webterminal.remote_control_mux import RemoteControlMux, JoystickCommands

PUBLISH_HZ = 50

def monotonic_ns() -> int:
  return time.monotonic_ns()

async def control_loop(listen_host="0.0.0.0", listen_port=14550, send_port=14551, logger=print):
  # 1) Mux (если web тоже обновляет команды — дергай mux.update_from_web(...))
  mux = RemoteControlMux(udp_timeout_ms=200, web_timeout_ms=500)

  webClientRegistry = ClientRegistry(
    timeout_ms=800,
    kind='web'
  )

  # 2) UDP bridge (socket + protocol)
  udp = UdpJoyTelemetryBridge(listen_host="0.0.0.0",
                              listen_port=14550,
                              send_port=14551,
                              publisher_p=mux.update_from_udp,
                              use_last_sender_as_peer=True,
                              logger=logger
                              )

  loop = asyncio.get_running_loop()
  await loop.create_datagram_endpoint(lambda: udp, local_addr=("0.0.0.0", 14550))

  # 3) cereal pub/sub
  pm = messaging.PubMaster(["testJoystick"])
  sm = messaging.SubMaster(["carState", "controlsState"], ignore_avg_freq=True)

  period = 1.0 / PUBLISH_HZ

  while True:
    # --- пример: берём UDP joystick и кладём в mux.update_from_udp ---
    # (в реальности ты парсишь udp.get_last_joy() и превращаешь в JoystickCommands)
    pkt = udp.get_last_joy()
    if pkt is not None:
      axes = pkt.axes
      buttons = pkt.buttons
      # нормализация
      steering = float(axes[0]) if len(axes) > 0 else 0.0
      brake_accel = float(axes[1]) if len(axes) > 1 else 0.0
      control_enabled = bool(buttons[1]) if len(buttons) > 1 else False
      cruise = bool(buttons[2]) if len(buttons) > 2 else False

      cmd = JoystickCommands(
        steering_and_angle_deg=steering,
        brake_and_accel=brake_accel,
        control_enabled=control_enabled,
        cruise_manual_activation=cruise,
        reserve1=False, reserve2=False, reserve3=False, reserve4=False
      )
      mux.update_from_udp(cmd)

    # --- mux select ---
    mj = mux.get()

    # --- publish to testJoystick ---
    msg = messaging.new_message("testJoystick")
    msg.testJoystick.axes = mj.axes
    msg.testJoystick.buttons = mj.buttons
    pm.send("testJoystick", msg)

    # --- telemetry out ---
    sm.update(0)
    if sm.updated.get("carState", False):
      # Remote control state for debud use 'controlsState'
      ctrl_s  = sm["controlsState"]
      cs = sm["carState"]

      udp.send_telemetry({
        "type": "telemetry",
        "t_ns": monotonic_ns(),
        "vEgo": float(cs.vEgo), # best estimate of speed

        "steeringAngleDeg": float(cs.steeringAngleDeg),
        "steering_drv_torque": float(cs.steeringTorque), # Native CAN units - check for driver applied torque
        "steering_flags": {
          "pressed": bool(cs.steeringPressed), # is the user overring the steering wheel?
          "disengage": bool(cs.steeringDisengage), # more force than steeringPressed, disengages for applicable brands
          "fault_temp": bool(cs.steerFaultTemporary), # temporary fault in steering
          "fault_perm": bool(cs.steerFaultPermanent) # permanent fault in steering
        },
        "drv_accel": float(cs.vEgo),
        "drv_brake": float(cs.brake),  # this is user pedal only
        "standstill": bool(cs.standstill), # is vehicle standstill
        "gasPressed": bool(cs.gasPressed), # this is user pedal only
        "brakePressed": bool(cs.brakePressed), # this is user pedal only
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

        "espDisabled": bool(cs.espDisabled), # is ESP currently disabled
        "accFaulted": bool(cs.accFaulted), # is ACC faulted
        "carFaultedNonCritical": bool(cs.carFaultedNonCritical), # some ECU is faulted, but car remains controllable
        "espActive": bool(cs.espActive), # is ESP currently active
        "vehicleSensorsInvalid": bool(cs.vehicleSensorsInvalid), # invalid steering angle readings, etc.
        "lowSpeedAlert": bool(cs.lowSpeedAlert), # lost steering control due to a dynamic min steering speed
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


        "rc_state_enabled": ctrl_s.enabledDEPRECATED,
        "rc_state_active": ctrl_s.activeDEPRECATED,
        "ctrl_state_steerAngleDeg": ctrl_s.actuators.steeringAngleDeg,
        "ctrl_state_accel": ctrl_s.actuators.accel,  # m/s^2
        "ctrl_state_gas": ctrl_s.actuators.gas, # [0.0, 1.0]
        "ctrl_state_brake": ctrl_s.actuators.brake, # [0.0, 1.0]
        "ctrl_state_torque": ctrl_s.actuators.torque, # [0.0, 1.0]
        "ctrl_state_torqueOutputCan": ctrl_s.actuators.torqueOutputCan,# value sent over can to the car
        "ctrl_state_speed": ctrl_s.actuators.speed, # m/s

        "src": mux.source_control,
        "enabled": bool(mux.source_controled),
      })

    await asyncio.sleep(period)

if __name__ == "__main__":
  asyncio.run(control_loop())
