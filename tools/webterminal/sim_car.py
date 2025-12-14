import traceback

import cereal.messaging as messaging
from opendbc.can.packer import CANPacker
from opendbc.can.parser import CANParser
from openpilot.common.params import Params
from openpilot.selfdrive.pandad.pandad_api_impl import can_list_to_can_capnp
from openpilot.tools.sim.lib.common import SimulatorState

class SimVwCar:
  """Simulates a honda civic 2022 (panda state + can messages) to OpenPilot"""
  # packer = CANPacker("honda_civic_ex_2022_can_generated")

  def __init__(self, car_model = "vw_mqb"):
    self._car_model = car_model
    self.packer = CANPacker(self._car_model)
    self.pm = messaging.PubMaster(['can', 'pandaStates'])
    self.sm = messaging.SubMaster(['carControl', 'controlsState', 'carParams', 'selfdriveState'])
    self.cp = self.get_car_can_parser()
    self.idx = 0
    self.params = Params()
    self.obd_multiplexing = False


  def get_car_can_parser(self):
    # dbc_f = 'honda_civic_ex_2022_can_generated'
    dbc_f = self._car_model
    checks = []
    return CANParser(dbc_f, checks, 0)

  def send_can_messages(self, simulator_state: SimulatorState):
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
    if cb == "CANCEL":
      gra["GRA_Abbrechen"] = 1
    elif cb == "RESUME":
      gra["GRA_Tip_Wiederaufnahme"] = 1
    elif cb == "SET":
      gra["GRA_Tip_Setzen"] = 1
    elif cb == "ACCEL":
      gra["GRA_Tip_Hoch"] = 1
    elif cb == "DECEL":
      gra["GRA_Tip_Runter"] = 1
    elif cb == "GAP":
      gra["GRA_Verstellung_Zeitluecke"] = 1
    elif cb == "MAIN":
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

  def send_panda_state(self, simulator_state):
    self.sm.update(0)

    if self.params.get_bool("ObdMultiplexingEnabled") != self.obd_multiplexing:
      self.obd_multiplexing = not self.obd_multiplexing
      self.params.put_bool("ObdMultiplexingChanged", True)

    dat = messaging.new_message('pandaStates', 1)
    dat.valid = True
    dat.pandaStates[0] = {
      'ignitionLine': simulator_state.ignition,
      'pandaType': "blackPanda",
      'controlsAllowed': True,
      'safetyModel': 'hondaBosch',
      'alternativeExperience': self.sm["carParams"].alternativeExperience,
      'safetyParam': 0,
    }

    self.pm.send('pandaStates', dat)

  def update(self, simulator_state: SimulatorState):
    try:
      self.send_can_messages(simulator_state)

      if self.idx % 50 == 0: # only send panda states at 2hz
        self.send_panda_state(simulator_state)

      self.idx += 1
    except Exception:
      traceback.print_exc()
      raise
