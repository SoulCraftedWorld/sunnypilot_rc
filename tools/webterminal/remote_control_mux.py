#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from dataclasses import dataclass
from typing import List, Optional, Callable

from .udp_bridge import UdpJoyTelemetryBridge, JoyPacket


def monotonic_ns() -> int:
  return time.monotonic_ns()

@dataclass
class JoystickCommands:
  seq: int
  steering_angle_deg: float
  brake_and_accel: float
  control_enabled: bool
  cruise_manual_set: bool
  ext_flags: List[bool]


@dataclass
class MuxedJoystick:
  # src: str  # "udp" | "web" | "none"
  t_ns: int
  axes: List[float]
  buttons: List[bool]
  enabled: bool

  def is_valid(self) -> bool:
    return bool(self.buttons[0]) if len(self.buttons) > 2 else False

  def is_enabled(self) -> bool:
    return bool(self.buttons[1]) if len(self.buttons) > 2 else False


class RemoteControlMux:
  def __init__(
      self,
      udp_timeout_ms: int = 400,
      web_timeout_ms: int = 800,
      on_control_mode_change_p: Optional[Callable[[bool], None]] = None
  ) -> None:
    self.debug_flag_en = False
    self.source_control = "none"
    self.source_controled = False
    self.udp_timeout_ns = int(udp_timeout_ms * 1e6)
    self.web_timeout_ns = int(web_timeout_ms * 1e6)

    self._web_cmd = MuxedJoystick(
      t_ns=0,
      axes=[0.0, 0.0],
      buttons=[False, False, False, False, False, False, False],
      enabled=False
    )

    self._udp_cmd = MuxedJoystick(
      t_ns=0,
      axes=[0.0, 0.0],
      buttons=[False, False, False, False, False, False, False],
      enabled=False
    )

    # exported state
    self.on_control_mode_change_p = on_control_mode_change_p

  def update_from_web(self, msg: JoystickCommands) -> None:

    ext_flags = msg.ext_flags + [False] * (4 - len(msg.ext_flags))
    self._web_cmd = MuxedJoystick(
      t_ns=monotonic_ns(),
      axes=[msg.steering_angle_deg, msg.brake_and_accel],
      buttons=[
        True,
        msg.control_enabled,
        msg.cruise_manual_set,
        ext_flags[0],
        ext_flags[1],
        ext_flags[2],
        ext_flags[3]
      ],
      enabled=msg.control_enabled
    )
    self._set_debug_flag_en(True)


  def update_from_udp(self, msg: JoystickCommands) -> None:
    ext_flags = msg.ext_flags + [False] * (4 - len(msg.ext_flags))
    self._udp_cmd = MuxedJoystick(
      t_ns=monotonic_ns(),
      axes=[msg.steering_angle_deg, msg.brake_and_accel],
      buttons=[
        True,
        msg.control_enabled,
        msg.cruise_manual_set,
        ext_flags[0],
        ext_flags[1],
        ext_flags[2],
        ext_flags[3]
      ],
      enabled=msg.control_enabled
    )
    self._set_debug_flag_en(True)

  def _fresh(self, now_ns: int, last_ns: int, timeout_ns: int) -> bool:
    return last_ns != 0 and (now_ns - last_ns) <= timeout_ns

  def _set_debug_flag_en(self, debug_flag_en):
    if self.debug_flag_en != debug_flag_en:
      self.debug_flag_en = debug_flag_en
      if self.on_control_mode_change_p is not None:
        self.on_control_mode_change_p(debug_flag_en)

  def get(self)-> Optional[MuxedJoystick]:
    now = monotonic_ns()

    chosen_msg = None

    web_fresh = self._fresh(now, self._web_cmd.t_ns, self.web_timeout_ns)
    if web_fresh and self._web_cmd.enabled:
      self.source_control = "web"
      self.source_controled = True
      chosen_msg = self._web_cmd
    else:
      udp_fresh = self._fresh(now, self._udp_cmd.t_ns, self.udp_timeout_ns)
      if udp_fresh and self._udp_cmd.enabled:
        self.source_control = "udp"
        self.source_controled = True
        chosen_msg = self._udp_cmd
      else:
        self.source_control = "none"
        self.source_controled = False
        if not web_fresh and not udp_fresh:
          self._set_debug_flag_en(False)

    return chosen_msg
