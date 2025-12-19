import traceback

import cereal.messaging as messaging
from opendbc.can.packer import CANPacker
from opendbc.can.parser import CANParser
from openpilot.common.params import Params
from openpilot.selfdrive.pandad.pandad_api_impl import can_list_to_can_capnp
from cereal import car, log
import time
from opendbc.car.volkswagen.values import VolkswagenFlags
from collections import namedtuple

vec3 = namedtuple("vec3", ["x", "y", "z"])


class GPSState:
  def __init__(self):
    self.latitude = 0
    self.longitude = 0
    self.altitude = 0

  def from_xy(self, xy):
    """Simulates a lat/lon from an xy coordinate on a plane, for simple simulation. TODO: proper global projection?"""
    BASE_LAT = 32.75308505188913
    BASE_LON = -117.2095393365393
    DEG_TO_METERS = 100000

    self.latitude = float(BASE_LAT + xy[0] / DEG_TO_METERS)
    self.longitude = float(BASE_LON + xy[1] / DEG_TO_METERS)
    self.altitude = 0


class IMUState:
  def __init__(self):
    self.accelerometer: vec3 = vec3(0,0,0)
    self.gyroscope: vec3 = vec3(0,0,0)
    self.bearing: float = 0

class SimState:
  def __init__(self):
    self.valid = False
    self.is_engaged = False
    self.ignition = True

    self.velocity: vec3 = vec3(0,0,0)
    self.bearing: float = 0
    self.gps = GPSState()
    self.imu = IMUState()

    self.steering_angle: float = 0

    self.user_gas: float = 0
    self.user_brake: float = 0
    self.user_torque: float = 0

    self.cruise_button = 0

    self.left_blinker = False
    self.right_blinker = False

    self.fuelGauge: float  = 0.88  # battery or fuel tank level from [0.0, 1.0]
    self.charging  = False

    self.velocityLin = 0.0

  @property
  def speed(self):
    return math.sqrt(self.velocity.x ** 2 + self.velocity.y ** 2 + self.velocity.z ** 2)


class CruiseButtons:
  CANCEL = 1
  RESUME = 2
  SET = 4
  ACCEL = 8
  DECEL = 16
  GAP = 32
  MAIN = 64

class SimVwCar:
  """Simulates a honda civic 2022 (panda state + can messages) to OpenPilot"""
  # packer = CANPacker("honda_civic_ex_2022_can_generated")

  def __init__(self, car_model = "vw_mqb", pb_carsate=False):
    self._car_model = car_model
    self.packer = CANPacker(self._car_model)
    self.pm = messaging.PubMaster(['can', 'pandaStates', 'peripheralState'])
    self.sm = messaging.SubMaster(['carControl', 'controlsState', 'carParams', 'selfdriveState'])
    self.cp = self.get_car_can_parser()
    self.idx = 0
    self.params = Params()
    self.obd_multiplexing = False
    self.CS = car.CarState()
    self.pm_cs = None
    self.pb_carsate = pb_carsate
    try:
      if pb_carsate:
        self.pm_cs = messaging.PubMaster(['carState'])
    except Exception:
      traceback.print_exc()


  def get_car_can_parser(self):
    # dbc_f = 'honda_civic_ex_2022_can_generated'
    dbc_f = self._car_model
    checks = []
    return CANParser(dbc_f, checks, 0)

  def send_can_messages2(self, simulator_state: SimState):
    if not simulator_state.valid:
      return

    msg = []

    # ---------- helpers ----------
    speed_kph = simulator_state.speed * 3.6  # m/s -> km/h

    # VW MQB wheel speed signals are usually scaled with 0.0075.
    # packer сам применит scaling из DBC, поэтому мы передаём физическое значение (km/h),
    # если packer у тебя работает в "phys" режиме (как обычно в openpilot).
    w = speed_kph

    # Steering angle in VW MQB: magnitude + separate sign bit (VZ)
    steer_deg = float(simulator_state.steering_angle)  # предполагаем, что simulator_state.steering_angle уже в градусах
    lwi_sign = 1 if steer_deg < 0 else 0
    lwi_abs = abs(steer_deg)

    # Brake
    brake_pressed = 1 if simulator_state.user_brake > 0 else 0

    # Gas (0..1 -> 0..100%)
    gas_percent = float(simulator_state.user_gas) * 100.0

    # Gear selector mapping for MO_Waehlpos (Motor_EV_01).
    # ВНИМАНИЕ: это типичный маппинг-гипотеза для VAG, проверь по логам CAN:
    # 0=P, 1=R, 2=N, 3=D, 4=S/Вперёд-спорт (если есть)
    # Если у тебя в симуляции всегда "D", оставь 3.
    gear_pos = 3

    # Seatbelt latch (Airbag_02 AB_Gurtschloss_FA: 0..3)
    # Часто 2 = пристёгнут, но зависит. Для симуляции можно поставить 2.
    seatbelt_latched = 2

    # Cruise buttons mapping (Honda-like enum -> VW MQB discrete bits)
    # Тут тебе нужно сопоставить simulator_state.cruise_button с нужным действием.
    # Я сделал универсальную схему: активен только один бит в кадре.
    gra = {
      "GRA_Hauptschalter": 1,  # MAIN ON (держим включенным)
      "GRA_Abbrechen": 0,  # CANCEL
      "GRA_Tip_Setzen": 0,  # SET
      "GRA_Tip_Hoch": 0,  # RES/+ (увеличить)
      "GRA_Tip_Runter": 0,  # SET/- (уменьшить)
      "GRA_Tip_Wiederaufnahme": 0,  # RESUME
      "GRA_Verstellung_Zeitluecke": 0,  # GAP
      "GRA_Limiter": 0,
      "GRA_Tip_Stufe_2": 0,
    }

    # Пример: если у тебя simulator_state.cruise_button кодирует "нажатую кнопку"
    # (как в Honda симе), то сделай маппинг под твои значения.
    # Ниже — безопасный пример через строковые константы (подгони под свой enum):
    cb = simulator_state.cruise_button
    # допустим cb может быть: "CANCEL", "RESUME", "SET", "ACCEL", "DECEL", "GAP", "MAIN"
    if cb == CruiseButtons.CANCEL:
      gra["GRA_Abbrechen"] = 1
    elif cb == CruiseButtons.RESUME:
      gra["GRA_Tip_Wiederaufnahme"] = 1
    elif cb == CruiseButtons.SET:
      gra["GRA_Tip_Setzen"] = 1
    elif cb == CruiseButtons.ACCEL:
      gra["GRA_Tip_Hoch"] = 1
    elif cb == CruiseButtons.DECEL:
      gra["GRA_Tip_Runter"] = 1
    elif cb == CruiseButtons.GAP:
      gra["GRA_Verstellung_Zeitluecke"] = 1
    elif cb == CruiseButtons.MAIN:
      gra["GRA_Hauptschalter"] = 1


    # ---------- powertrain bus (0) ----------

    # Wheel speeds (ESP_19)
    msg.append(self.packer.make_can_msg("ESP_19", 0, {
      "ESP_VL_Radgeschw_02": w,
      "ESP_VR_Radgeschw_02": w,
      "ESP_HL_Radgeschw_02": w,
      "ESP_HR_Radgeschw_02": w,
    }))

    # Steering angle (LWI_01)
    msg.append(self.packer.make_can_msg("LWI_01", 0, {
      "LWI_Lenkradwinkel": lwi_abs,
      "LWI_VZ_Lenkradwinkel": lwi_sign,
      # по желанию можно добавить скорость вращения руля, если есть в simulator_state:
      # "LWI_Lenkradw_Geschw": abs(simulator_state.steering_rate_dps),
      # "LWI_VZ_Lenkradw_Geschw": 1 if simulator_state.steering_rate_dps < 0 else 0,
    }))

    # Gas pedal (Motor_20)
    msg.append(self.packer.make_can_msg("Motor_20", 0, {
      "MO_Fahrpedalrohwert_01": gas_percent,
    }))

    # Gear selector (Motor_EV_01) — актуально для e-Golf / BEV из твоего DBC
    msg.append(self.packer.make_can_msg("Motor_EV_01", 0, {
      "MO_Waehlpos": gear_pos,
    }))

    # Seatbelt latch (Airbag_02)
    msg.append(self.packer.make_can_msg("Airbag_02", 0, {
      "AB_Gurtschloss_FA": seatbelt_latched,
    }))

    # Brake pressed / brake light (ESP_05)
    msg.append(self.packer.make_can_msg("ESP_05", 0, {
      "ESP_Fahrer_bremst": brake_pressed,
      "ECD_Bremslicht": brake_pressed,
    }))

    # ACC / Cruise buttons (GRA_ACC_01)
    msg.append(self.packer.make_can_msg("GRA_ACC_01", 0, gra))

    # ---------- cam bus (2) ----------
    # Если у тебя в симе есть отдельные “камера/ассистенты” кадры — добавляй сюда.
    # Для минимальной симуляции можно оставить пустыми/не слать.
    # msg.append(self.packer.make_can_msg("...some_cam_msg...", 2, {}))

    self.pm.send('can', can_list_to_can_capnp(msg))



  def send_can_messages(self, simulator_state: SimState):
    if not simulator_state.valid:
      return

    msg = []
    speed_kph = float(simulator_state.velocityLin) * 3.6  # m/s -> km/h

    # --------------------------
    # 1) Колёсные скорости (ESP_19) — CarState.parse_wheel_speeds() читает именно их
    # --------------------------
    msg.append(self.packer.make_can_msg("ESP_19", 0, {
      "ESP_VL_Radgeschw_02": speed_kph,
      "ESP_VR_Radgeschw_02": speed_kph,
      "ESP_HL_Radgeschw_02": speed_kph,
      "ESP_HR_Radgeschw_02": speed_kph,
    }))

    # --------------------------
    # 2) Угол руля (LWI_01) — magnitude + sign bit
    # --------------------------
    steer_deg = float(simulator_state.steering_angle)  # предполагаем градусы
    msg.append(self.packer.make_can_msg("LWI_01", 0, {
      "LWI_Lenkradwinkel": abs(steer_deg),
      "LWI_VZ_Lenkradwinkel": 1 if steer_deg < 0 else 0,

      # скорость вращения руля (если нет — ставим 0)
      "LWI_Lenkradw_Geschw": 0,
      "LWI_VZ_Lenkradw_Geschw": 0,
    }))

    # --------------------------
    # 3) Газ (Motor_20) — CarState.gasPressed читает MO_Fahrpedalrohwert_01
    # --------------------------
    gas_percent = float(simulator_state.user_gas) * 100.0
    msg.append(self.packer.make_can_msg("Motor_20", 0, {
      "MO_Fahrpedalrohwert_01": gas_percent,
    }))

    # --------------------------
    # 4) Тормоз: CarState использует Motor_14.MO_Fahrer_bremst и ESP_05.ESP_Fahrer_bremst
    # --------------------------
    brake_pressed = 1 if float(simulator_state.user_brake) > 0.0 else 0

    msg.append(self.packer.make_can_msg("Motor_14", 0, {
      "MO_Fahrer_bremst": brake_pressed,
    }))

    # В ESP_05 ещё читают давление, но для минималки можно 0
    msg.append(self.packer.make_can_msg("ESP_05", 0, {
      "ESP_Fahrer_bremst": brake_pressed,
      "ESP_Bremsdruck": 0,
    }))

    # --------------------------
    # 5) Ремень: CarState.seatbeltUnlatched = AB_Gurtschloss_FA != 3
    # То есть "пристёгнут" -> ставим 3
    # --------------------------
    msg.append(self.packer.make_can_msg("Airbag_02", 0, {
      "AB_Gurtschloss_FA": 3,
    }))

    # --------------------------
    # 6) Поворотники: CarState читает Blinkmodi_02 Comfort_Signal_Left/Right
    # --------------------------
    msg.append(self.packer.make_can_msg("Blinkmodi_02", 0, {
      "Comfort_Signal_Left": int(bool(simulator_state.left_blinker)),
      "Comfort_Signal_Right": int(bool(simulator_state.right_blinker)),
    }))

    # --------------------------
    # 7) Двери: CarState.doorOpen читает Gateway_72.ZV_*_offen
    # Если в симе нет — держим всё закрыто (0)
    # --------------------------
    msg.append(self.packer.make_can_msg("Gateway_72", 0, {
      "ZV_FT_offen": 0,
      "ZV_BT_offen": 0,
      "ZV_HFS_offen": 0,
      "ZV_HBFS_offen": 0,
      "ZV_HD_offen": 0,
      # если у тебя manual коробка — там ещё Rueckfahrlicht_Schalter, но в MQB-ветке это не нужно
    }))

    # --------------------------
    # 8) Скорость на приборке: CarState.vEgoCluster = Kombi_01.KBI_angez_Geschw * KPH_TO_MS
    # --------------------------
    msg.append(self.packer.make_can_msg("Kombi_01", 0, {
      "KBI_angez_Geschw": speed_kph,
      "KBI_Handbremse": 0,  # парковочный тормоз
    }))

    # --------------------------
    # 9) Кнопки круиза: CarState читает self.gra_stock_values = pt_cp.vl["GRA_ACC_01"]
    # create_button_events() использует self.CCP.BUTTONS, которые смотрят на GRA_ACC_01.
    # Здесь важно: выставляй ровно те поля, которые ожидает твой CarControllerParams.
    # Минимально включим главный выключатель.
    # --------------------------
    gra = {
      "GRA_Hauptschalter": 1,
      "GRA_Abbrechen": 0,
      "GRA_Tip_Setzen": 0,
      "GRA_Tip_Hoch": 0,
      "GRA_Tip_Runter": 0,
      "GRA_Tip_Wiederaufnahme": 0,
      "GRA_Verstellung_Zeitluecke": 0,
      "GRA_Limiter": 0,
      "GRA_Tip_Stufe_2": 0,
    }

    # если cruise_button у тебя не строки — замени маппинг под свой enum
    cb = simulator_state.cruise_button
    # допустим cb может быть: "CANCEL", "RESUME", "SET", "ACCEL", "DECEL", "GAP", "MAIN"
    if cb == CruiseButtons.CANCEL:
      gra["GRA_Abbrechen"] = 1
    elif cb == CruiseButtons.RESUME:
      gra["GRA_Tip_Wiederaufnahme"] = 1
    elif cb == CruiseButtons.SET:
      gra["GRA_Tip_Setzen"] = 1
    elif cb == CruiseButtons.ACCEL:
      gra["GRA_Tip_Hoch"] = 1
    elif cb == CruiseButtons.DECEL:
      gra["GRA_Tip_Runter"] = 1
    elif cb == CruiseButtons.GAP:
      gra["GRA_Verstellung_Zeitluecke"] = 1
    elif cb == CruiseButtons.MAIN:
      gra["GRA_Hauptschalter"] = 1

    msg.append(self.packer.make_can_msg("GRA_ACC_01", 0, gra))

    # --------------------------
    # 10) TSK_06: CarState.cruiseState.available/enabled завязаны на TSK_06.TSK_Status
    # Чтобы UI не считал, что круиза нет — можно держать статус 2/3/4/5
    # Пример: 3 = enabled (часто так), но значения зависят от DBC/реализации.
    # --------------------------
    msg.append(self.packer.make_can_msg("TSK_06", 0, {
      "TSK_Status": 3 if simulator_state.is_engaged else 2,
      "TSK_Limiter_ausgewaehlt": 0,
    }))

    # --------------------------
    # CAM bus (2) — для MQB-ветки можно пока не слать, если networkLocation не требует
    # --------------------------


    self.pm.send('can', can_list_to_can_capnp(msg))

    # msg = []
    # msg.append(self.packer.make_can_msg("TSK_06", 1, {
    #   "TSK_Status": 3,
    #   "TSK_Limiter_ausgewaehlt": 0,
    # }))
    # self.pm.send('can', can_list_to_can_capnp(msg))
    # msg = []
    # msg.append(self.packer.make_can_msg("TSK_06", 2, {
    #   "TSK_Status": 3,
    #   "TSK_Limiter_ausgewaehlt": 0,
    # }))
    # self.pm.send('can', can_list_to_can_capnp(msg))

  def send_panda_state(self, simulator_state):
    self.sm.update(0)

    if self.params.get_bool("ObdMultiplexingEnabled") != self.obd_multiplexing:
      self.obd_multiplexing = not self.obd_multiplexing
      self.params.put_bool("ObdMultiplexingChanged", True)

    # dat = messaging.new_message('pandaStates', 1)
    # dat.valid = True
    # dat.pandaStates[0] = {
    #   'ignitionLine': simulator_state.ignition,
    #   'pandaType': "blackPanda",
    #   'controlsAllowed': True,
    #   'safetyModel': 'hondaBosch',
    #   'alternativeExperience': self.sm["carParams"].alternativeExperience,
    #   'safetyParam': 0,
    #
    #   'ignitionCan': simulator_state.ignition,
    #   'faultStatus': 0,
    #   'powerSaveEnabled': False,
    #   'uptime': 0,
    #   'faults': [],
    #   'heartbeatLost': False,
    #   'interruptLoad': 0.0,
    #   'fanPower': 0,
    #   'fanStallCount': 0,
    #   'spiErrorCount': 0,
    #   'harnessStatus': 1, # normal
    #   'sbu1Voltage': 0.0,
    #   'sbu2Voltage': 0.0,
    #   'canState0': {
    #     'busOff': False,
    #     'totalTxCnt': 10000,
    #     'totalRxCnt': 10000,
    #   },
    #   'canState1':  {
    #     'busOff': False,
    #     'totalTxCnt': 10000,
    #     'totalRxCnt': 10000,
    #   },
    #   'canState2': {},
    # }
    # self.pm.send('pandaStates', dat)

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
    per_msg.peripheralState.voltage = 12300  # мВ
    per_msg.peripheralState.current = 200  # мА
    per_msg.peripheralState.fanSpeedRpm = 0  # UInt16

    self.pm.send("pandaStates", pst_msg)
    self.pm.send("peripheralState", per_msg)



  def send_car_state(self, simulator_state: SimState):
    if self.pm_cs is None or not self.pb_carsate:
      return
    cs_send = messaging.new_message('carState')
    CS = car.CarState()
    CS.canValid = True
    CS.canTimeout = False
    CS.canErrorCounter = 0

    speed = float(simulator_state.velocityLin)
    CS.vEgo = speed # best estimate of speed
    CS.aEgo = 0.0  # acceleration not simulated
    CS.vEgoRaw = speed  # unfiltered speed from wheel speed sensors
    CS.vEgoCluster = speed  # best estimate of speed shown on car's instrument cluster, used for UI

    # CS.vCruise = speed  # actual set speed
    # CS.vCruiseCluster = speed  # set speed to display

    CS.standstill = speed < 0.01
    CS.wheelSpeeds = car.CarState.WheelSpeeds.new_message()
    CS.wheelSpeeds.fl = float(speed)
    CS.wheelSpeeds.fr = float(speed)
    CS.wheelSpeeds.rl = float(speed)
    CS.wheelSpeeds.rr = float(speed)

    CS.gasPressed = simulator_state.user_gas > 0.0
    CS.brake = float(simulator_state.user_brake)
    CS.brakePressed = simulator_state.user_brake > 0.0
    CS.regenBraking = False
    CS.parkingBrake = False
    CS.brakeHoldActive = False

    cb = simulator_state.cruise_button

    # steering wheel
    CS.steeringAngleDeg = float(simulator_state.steering_angle)
    CS.steeringRateDeg = 0.0  # not simulated
    CS.steeringTorque = float(simulator_state.user_torque)
    CS.steeringPressed = abs(simulator_state.user_torque) > 1e-3
    CS.steerFaultTemporary = False
    CS.steerFaultPermanent = False
    CS.steeringDisengage = False
    CS.steeringTorqueEps = float(simulator_state.user_torque)

    CS.cruiseState = car.CarState.CruiseState.new_message()
    if cb == CruiseButtons.SET:
      CS.cruiseState.enabled = True
    else:
      CS.cruiseState.enabled = False
    CS.cruiseState.available = True
    CS.cruiseState.speed = float(simulator_state.velocityLin)
    CS.cruiseState.speedCluster = float(simulator_state.velocityLin)
    CS.cruiseState.standstill = simulator_state.velocityLin < 0.01
    CS.cruiseState.nonAdaptive = False


    # допустим cb может быть: "CANCEL", "RESUME", "SET", "ACCEL", "DECEL", "GAP", "MAIN"
    # if cb == CruiseButtons.SET:


    # gear
    CS.gearShifter = car.CarState.GearShifter.drive # park, reverse, neutral, drive, sport, low, brake, eco, manumatic
    CS.buttonEvents = []

    CS.fuelGauge = simulator_state.fuelGauge  # battery or fuel tank level from [0.0, 1.0]
    CS.charging = simulator_state.charging


    cs_send.valid = CS.canValid
    cs_send.carState = CS
    cs_send.carState.canErrorCounter = 0
    cs_send.carState.cumLagMs = -1000.
    try:
      self.pm_cs.send('carState', cs_send)
    except Exception:
      pass

  def update(self, simulator_state: SimState):
    try:
      self.send_can_messages(simulator_state)

      if self.idx % 50 == 0: # only send panda states at 2hz
        self.send_panda_state(simulator_state)

      # self.send_car_state(simulator_state)
      self.idx += 1
    except Exception:
      traceback.print_exc()

