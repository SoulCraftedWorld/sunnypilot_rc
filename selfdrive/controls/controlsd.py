#!/usr/bin/env python3
import math
import threading
import time
from numbers import Number

from cereal import car, log
import cereal.messaging as messaging
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.common.realtime import config_realtime_process, Priority, Ratekeeper
from openpilot.common.swaglog import cloudlog

from opendbc.car.car_helpers import interfaces
from opendbc.car.vehicle_model import VehicleModel
from openpilot.selfdrive.controls.lib.drive_helpers import clip_curvature
from openpilot.selfdrive.controls.lib.latcontrol import LatControl
from openpilot.selfdrive.controls.lib.latcontrol_pid import LatControlPID
from openpilot.selfdrive.controls.lib.latcontrol_angle import LatControlAngle, STEER_ANGLE_SATURATION_THRESHOLD
from openpilot.selfdrive.controls.lib.latcontrol_torque import LatControlTorque
from openpilot.selfdrive.controls.lib.longcontrol import LongControl
from openpilot.selfdrive.locationd.helpers import PoseCalibrator, Pose

from openpilot.sunnypilot.livedelay.helpers import get_lat_delay
from openpilot.sunnypilot.modeld.modeld_base import ModelStateBase
from openpilot.sunnypilot.selfdrive.controls.controlsd_ext import ControlsExt

State = log.SelfdriveState.OpenpilotState
LaneChangeState = log.LaneChangeState
LaneChangeDirection = log.LaneChangeDirection

ACTUATOR_FIELDS = tuple(car.CarControl.Actuators.schema.fields.keys())


class RemoteControl:
  def __init__(self, timeout: float = 1.0) -> None:
    self.steeringAngleDeg = 0.0  # about -540 ..  +540
    self.brakeAndAccel = 0.0  # negative is brake. -1 ..  +1
    self.enabled = False
    self.time_out = False
    self.cruiseManualActivation = False
    self.cruiseManualStep = "None"
    self.cruiseManualStartedTimeout = 0.0
    self.reserveFlag1 = False
    self.reserveFlag2 = False
    self.reserveFlag3 = False
    self.reserveFlag4 = False
    self.timestamp = 0.0
    self.timeout = timeout

    self.is_active = False

    self.target_curvature = 0.0
    self.state_curvature = 0.0
    self.state_cc_enabled = False

    self.comma_model_desiredCurvature = 0.0
    self.comma_cc_enabled = False
    self.comma_latActive = False
    self.comma_longActive = False
    self.steer_limited_by_safety = 0.0

    self.logTimer = time.monotonic()

    self.steerWheelMaxDeg = 540.0  # default value, will be updated in Controls init

  def reset(self) -> None:
    self.__init__(self.timeout)

  def setNewData(self, joystick: 'Joystick'):
    """
    Update remote control commands from joystick input.
    Args:
      joystick: Joystick message containing axes and button states.
        axes[ steering, accel/brake ]
                   0       1                2                3        4          5       6
        buttons[ valid, enabled, cruiseManualActivation, reserve1, reserve2, reserve3, reserve4 ]
    """
    if len(joystick.buttons) >= 7:
      self.time_out = False
      if joystick.buttons[0] and len(joystick.axes) == 2: # valid data and correct axes length
        self.steeringAngleDeg = joystick.axes[0]
        if self.steeringAngleDeg > self.steerWheelMaxDeg:
          self.steeringAngleDeg = self.steerWheelMaxDeg
        elif self.steeringAngleDeg < -self.steerWheelMaxDeg:
          self.steeringAngleDeg = -self.steerWheelMaxDeg

        self.brakeAndAccel = joystick.axes[1]
        if self.brakeAndAccel > 1.0:
          self.brakeAndAccel = 1.0
        elif self.brakeAndAccel < -1.0:
          self.brakeAndAccel = -1.0

        self.enabled = joystick.buttons[1]
        self.cruiseManualActivation = joystick.buttons[2]
        self.reserveFlag1 = joystick.buttons[3]
        self.reserveFlag2 = joystick.buttons[4]
        self.reserveFlag3 = joystick.buttons[5]
        self.reserveFlag4 = joystick.buttons[6]
        self.timestamp = time.monotonic()

  def print_log(self):
    if self.logTimer < time.monotonic():
      self.logTimer = time.monotonic() + 2.
      cloudlog.error(f"Log remote control: "
                     f"EN={self.enabled}, "
                     f"RX={self.time_out}, "
                     f"cruiseBut={self.cruiseManualActivation}, "
                     f"brkAcc={(self.brakeAndAccel*100.0):.1f}, "
                     f"steer={self.steeringAngleDeg:.1f}, "
                     f"IsAct={self.is_active}, "
                     f"Targ/Cur/limCurv={self.target_curvature:.3f}/{self.state_curvature:.3f}/{self.steer_limited_by_safety:.3f}, "
                     f"CCisEn={self.state_cc_enabled}, "
                     f"CCEn={self.comma_cc_enabled}, "
                     f"latEn={self.comma_latActive}, "
                     f"lonEn={self.comma_longActive}, "
                     )

  def check_timeout(self):
    self.time_out =  (time.monotonic() - self.timestamp) > self.timeout
    if self.enabled and self.time_out:
      self.enabled = False
      # self.reset()

  def on_driver_bake(self,brakePressed: bool):
    if brakePressed:
      self.enabled = False

  def check_cruise_manual_activation(self, cc_en) -> bool:
    manual_set = False
    if not cc_en and self.cruiseManualActivation:
      if self.cruiseManualStep != "Gone":
        if self.cruiseManualStep == "None":
          self.cruiseManualStep = "Started"
          self.cruiseManualStartedTimeout = time.monotonic()
        elif self.cruiseManualStep == "Started":
          if (time.monotonic() - self.cruiseManualStartedTimeout) > self.timeout:
            self.cruiseManualStep = "Gone"
        manual_set = True
    else:
      self.cruiseManualStep = "None"

    return manual_set


class Controls(ControlsExt, ModelStateBase):
  def __init__(self) -> None:
    self.params = Params()
    cloudlog.info("controlsd is waiting for CarParams")
    self.CP = messaging.log_from_bytes(self.params.get("CarParams", block=True), car.CarParams)
    cloudlog.info("controlsd got CarParams")

    # Initialize sunnypilot controlsd extension and base model state
    ControlsExt.__init__(self, self.CP, self.params)
    ModelStateBase.__init__(self)

    self.CI = interfaces[self.CP.carFingerprint](self.CP, self.CP_SP)

    self.sm = messaging.SubMaster(['liveParameters', 'liveTorqueParameters', 'modelV2', 'selfdriveState',
                                   'liveCalibration', 'livePose', 'longitudinalPlan', 'carState', 'carOutput',
                                   'driverMonitoringState', 'onroadEvents', 'driverAssistance', 'liveDelay',
                                   'testJoystick'
                                   ] + self.sm_services_ext,
                                  poll='selfdriveState')
    self.pm = messaging.PubMaster(['carControl', 'controlsState'] + self.pm_services_ext)

    self.steer_limited_by_safety = False
    self.curvature = 0.0
    self.desired_curvature = 0.0

    self.pose_calibrator = PoseCalibrator()
    self.calibrated_pose: Pose | None = None

    self.LoC = LongControl(self.CP)
    self.VM = VehicleModel(self.CP)
    self.LaC: LatControl
    if self.CP.steerControlType == car.CarParams.SteerControlType.angle:
      self.LaC = LatControlAngle(self.CP, self.CP_SP, self.CI)
    elif self.CP.lateralTuning.which() == 'pid':
      self.LaC = LatControlPID(self.CP, self.CP_SP, self.CI)
    elif self.CP.lateralTuning.which() == 'torque':
      self.LaC = LatControlTorque(self.CP, self.CP_SP, self.CI)

    self.carWheelMaxDeg = 34.0  # degrees
    self._remoteControl =  RemoteControl(timeout=1.0)
    self._remoteControl.steerWheelMaxDeg = self.CP.steerRatio * self.carWheelMaxDeg


  def update(self):
    self.sm.update(15)
    if self.sm.updated["liveCalibration"]:
      self.pose_calibrator.feed_live_calib(self.sm['liveCalibration'])
    if self.sm.updated["livePose"]:
      device_pose = Pose.from_live_pose(self.sm['livePose'])
      self.calibrated_pose = self.pose_calibrator.build_calibrated_pose(device_pose)

  def state_control(self):
    CS = self.sm['carState']

    if self.sm.updated['testJoystick']:
      self._remoteControl.setNewData(joystick=self.sm['testJoystick'])
    self._remoteControl.check_timeout()
    self._remoteControl.on_driver_bake(CS.brakePressed)

    # Update VehicleModel
    lp = self.sm['liveParameters']
    x = max(lp.stiffnessFactor, 0.1)
    sr = max(lp.steerRatio, 0.1)
    self.VM.update_params(x, sr)

    steer_angle_without_offset = math.radians(CS.steeringAngleDeg - lp.angleOffsetDeg)
    self.curvature = -self.VM.calc_curvature(steer_angle_without_offset, CS.vEgo, lp.roll)

    # Update Torque Params
    if self.CP.lateralTuning.which() == 'torque':
      torque_params = self.sm['liveTorqueParameters']
      if self.sm.all_checks(['liveTorqueParameters']) and torque_params.useParams:
        self.LaC.update_live_torque_params(torque_params.latAccelFactorFiltered, torque_params.latAccelOffsetFiltered,
                                           torque_params.frictionCoefficientFiltered)

        self.LaC.extension.update_limits()

      self.LaC.extension.update_model_v2(self.sm['modelV2'])

      self.lat_delay = get_lat_delay(self.params, self.sm["liveDelay"].lateralDelay)
      self.LaC.extension.update_lateral_lag(self.lat_delay)

    long_plan = self.sm['longitudinalPlan']
    model_v2 = self.sm['modelV2']

    model_desiredCurvature = model_v2.action.desiredCurvature

    CC = car.CarControl.new_message()
    CC.enabled = self.sm['selfdriveState'].enabled

    # Check which actuators can be enabled
    standstill = abs(CS.vEgo) <= max(self.CP.minSteerSpeed, 0.3) or CS.standstill


    self._remoteControl.state_cc_enabled = CS.cruiseState.enabled
    self._remoteControl.state_curvature = self.curvature
    self._remoteControl.comma_cc_enabled = CC.enabled
    self._remoteControl.comma_model_desiredCurvature = model_desiredCurvature

    # Get which state to use for active lateral control
    _lat_active = self.get_lat_active(self.sm)
    _longActive = CC.enabled and not any(e.overrideLongitudinal for e in self.sm['onroadEvents']) and self.CP.openpilotLongitudinalControl
    if self._remoteControl.enabled:



      self._remoteControl.comma_latActive = _lat_active and not CS.steerFaultTemporary and not CS.steerFaultPermanent and \
                   (not standstill or self.CP.steerAtStandstill)
      self._remoteControl.comma_longActive = _longActive
      # self._remoteControl.comma_model_desiredCurvature = model_desiredCurvature
      rc_steer_angle_without_offset = math.radians(self._remoteControl.steeringAngleDeg - lp.angleOffsetDeg)
      self._remoteControl.target_curvature = -self.VM.calc_curvature(rc_steer_angle_without_offset, CS.vEgo, lp.roll)
      model_desiredCurvature = self._remoteControl.target_curvature

      if not _lat_active:
        _lat_active = self.sm['selfdriveState'].active

      CC.enabled  = True
      _longActive = self.CP.openpilotLongitudinalControl


      self._remoteControl.is_active = _lat_active and any(_longActive or sself.CP.pcmCruise)
    else:
      self._remoteControl.is_active = False

    CC.latActive = _lat_active and not CS.steerFaultTemporary and not CS.steerFaultPermanent and \
                   (not standstill or self.CP.steerAtStandstill)

    CC.longActive = _longActive


    actuators = CC.actuators
    actuators.longControlState = self.LoC.long_control_state

    # Enable blinkers while lane changing
    if model_v2.meta.laneChangeState != LaneChangeState.off:
      CC.leftBlinker = model_v2.meta.laneChangeDirection == LaneChangeDirection.left
      CC.rightBlinker = model_v2.meta.laneChangeDirection == LaneChangeDirection.right

    # accel PID lim
    pid_accel_limits = self.CI.get_pid_accel_limits(self.CP, CS.vEgo, CS.vCruise * CV.KPH_TO_MS)

    if not self._remoteControl.enabled:
      if not CC.latActive:
        self.LaC.reset()
      if not CC.longActive:
        self.LoC.reset()
      # accel PID loop
      actuators.accel = float(self.LoC.update(CC.longActive, CS, long_plan.aTarget, long_plan.shouldStop, pid_accel_limits))

    else:
      # Set longet params
      if self._remoteControl.brakeAndAccel < 0.0:
        long_shouldStop = True
        long_aTarget = self._remoteControl.brakeAndAccel * 3.5
      else:
        if long_plan.hasLead and any(long_plan.shouldStop or long_plan.aTarget < 0.0) and self._remoteControl.comma_longActive:
          # TODO Make case for adaptive
          cloudlog.error(f"Romote conterol accel {self._remoteControl.brakeAndAccel} conflict with lead car: shouldStop {long_plan.shouldStop}, aTarget {long_plan.aTarget}")

        long_shouldStop = False
        long_aTarget = self._remoteControl.brakeAndAccel * 2.0
      # accel PID loop
      actuators.accel = float(self.LoC.update(CC.longActive, CS, long_aTarget, long_shouldStop, pid_accel_limits))

    # Steering PID loop and lateral MPC
    # Reset desired curvature to current to avoid violating the limits on engage
    new_desired_curvature = model_desiredCurvature if CC.latActive else self.curvature

    self.desired_curvature, curvature_limited = clip_curvature(CS.vEgo, self.desired_curvature, new_desired_curvature, lp.roll)

    actuators.curvature = self.desired_curvature
    steer, steeringAngleDeg, lac_log = self.LaC.update(CC.latActive, CS, self.VM, lp,
                                                       self.steer_limited_by_safety, self.desired_curvature,
                                                       self.calibrated_pose, curvature_limited)  # TODO what if not available
    actuators.torque = float(steer)
    actuators.steeringAngleDeg = float(steeringAngleDeg)
    # Ensure no NaNs/Infs
    for p in ACTUATOR_FIELDS:
      attr = getattr(actuators, p)
      if not isinstance(attr, Number):
        continue

      if not math.isfinite(attr):
        cloudlog.error(f"actuators.{p} not finite {actuators.to_dict()}")
        setattr(actuators, p, 0.0)

    return CC, lac_log

  def publish(self, CC, lac_log):
    CS = self.sm['carState']

    # Orientation and angle rates can be useful for carcontroller
    # Only calibrated (car) frame is relevant for the carcontroller
    CC.currentCurvature = self.curvature
    if self.calibrated_pose is not None:
      CC.orientationNED = self.calibrated_pose.orientation.xyz.tolist()
      CC.angularVelocity = self.calibrated_pose.angular_velocity.xyz.tolist()

    # Handle manual cruise set On
    if self._remoteControl.enabled:
      CC.cruiseControl.override = not CC.longActive   # and self.CP.openpilotLongitudinalControl
      CC.cruiseControl.resume = CS.cruiseState.standstill and self._remoteControl.brakeAndAccel > 0.0
      # FIXME Испоьзовать флаги экстренной остановки от COMMA
      # CC.cruiseControl.resume = CS.cruiseState.standstill and self._remoteControl.brakeAndAccel > 0.0 and not self.sm['longitudinalPlan'].shouldStop

      # if self._remoteControl.check_cruise_manual_activation(CS.cruiseState.enabled) and self.CP.pcmCruise:
      #   CC.cruiseControl.speedOverrideDEPRECATED = 1.0
      # else:
      #   CC.cruiseControl.speedOverrideDEPRECATED = 0.0

      CC.cruiseControl.speedOverrideDEPRECATED = 0.0

      CC.cruiseControl.cancel = CS.cruiseState.enabled and (not self.CP.pcmCruise)
    else:
      CC.cruiseControl.override = CC.enabled and not CC.longActive and self.CP.openpilotLongitudinalControl
      CC.cruiseControl.resume = CC.enabled and CS.cruiseState.standstill and not self.sm['longitudinalPlan'].shouldStop
      CC.cruiseControl.speedOverrideDEPRECATED = 0.0
      CC.cruiseControl.cancel = CS.cruiseState.enabled and (not CC.enabled or not self.CP.pcmCruise)


    hudControl = CC.hudControl
    hudControl.setSpeed = float(CS.vCruiseCluster * CV.KPH_TO_MS)
    hudControl.speedVisible = CC.enabled or self._remoteControl.enabled
    hudControl.lanesVisible = CC.enabled if not self._remoteControl.enabled else True
    hudControl.leadVisible = self.sm['longitudinalPlan'].hasLead
    hudControl.leadDistanceBars = self.sm['selfdriveState'].personality.raw + 1
    hudControl.visualAlert = self.sm['selfdriveState'].alertHudVisual

    hudControl.rightLaneVisible = True
    hudControl.leftLaneVisible = True
    if self.sm.valid['driverAssistance']:
      hudControl.leftLaneDepart = self.sm['driverAssistance'].leftLaneDeparture
      hudControl.rightLaneDepart = self.sm['driverAssistance'].rightLaneDeparture

    if self.sm['selfdriveState'].active or self._remoteControl.enabled:
      CO = self.sm['carOutput']
      if self.CP.steerControlType == car.CarParams.SteerControlType.angle:
        self.steer_limited_by_safety = abs(CC.actuators.steeringAngleDeg - CO.actuatorsOutput.steeringAngleDeg) > \
                                              STEER_ANGLE_SATURATION_THRESHOLD
      else:
        self.steer_limited_by_safety = abs(CC.actuators.torque - CO.actuatorsOutput.torque) > 1e-2

    self._remoteControl.steer_limited_by_safety = self.steer_limited_by_safety

    # TODO: both controlsState and carControl valids should be set by
    #       sm.all_checks(), but this creates a circular dependency

    # controlsState
    dat = messaging.new_message('controlsState')
    dat.valid = CS.canValid
    cs = dat.controlsState

    cs.curvature = self.curvature
    cs.longitudinalPlanMonoTime = self.sm.logMonoTime['longitudinalPlan']
    cs.lateralPlanMonoTime = self.sm.logMonoTime['modelV2']
    cs.desiredCurvature = self.desired_curvature
    cs.longControlState = self.LoC.long_control_state
    cs.upAccelCmd = float(self.LoC.pid.p)
    cs.uiAccelCmd = float(self.LoC.pid.i)
    cs.ufAccelCmd = float(self.LoC.pid.f)

    if not self._remoteControl.enabled:
      cs.forceDecel = bool((self.sm['driverMonitoringState'].awarenessStatus < 0.) or
                           (self.sm['selfdriveState'].state == State.softDisabling))
    else:
      cs.forceDecel = False

    lat_tuning = self.CP.lateralTuning.which()
    if self.CP.steerControlType == car.CarParams.SteerControlType.angle:
      cs.lateralControlState.angleState = lac_log
    elif lat_tuning == 'pid':
      cs.lateralControlState.pidState = lac_log
    elif lat_tuning == 'torque':
      cs.lateralControlState.torqueState = lac_log

    # Remote control state for debug use
    cs.enabledDEPRECATED = self._remoteControl.enabled
    cs.activeDEPRECATED = self._remoteControl.is_active

    self.pm.send('controlsState', dat)

    # carControl
    cc_send = messaging.new_message('carControl')
    cc_send.valid = CS.canValid
    cc_send.carControl = CC
    self.pm.send('carControl', cc_send)

  def params_thread(self, evt):
    while not evt.is_set():
      self.get_params_sp()

      time.sleep(0.1)

  def run(self):
    rk = Ratekeeper(100, print_delay_threshold=None)
    e = threading.Event()
    t = threading.Thread(target=self.params_thread, args=(e,))
    try:
      t.start()
      while True:
        self.update()
        CC, lac_log = self.state_control()
        self.publish(CC, lac_log)
        self.run_ext(self.sm, self.pm)
        rk.monitor_time()
    finally:
      e.set()
      t.join()


def main():
  config_realtime_process(4, Priority.CTRL_HIGH)
  controls = Controls()
  controls.run()


if __name__ == "__main__":
  main()
