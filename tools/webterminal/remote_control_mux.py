#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from dataclasses import dataclass
from typing import List, Optional

from .udp_bridge import UdpJoyTelemetryBridge, JoyPacket


def monotonic_ns() -> int:
  return time.monotonic_ns()

@dataclass
class JoystickCommands:
  steering_and_angle_deg: float
  brake_and_accel: float
  control_enabled: bool
  cruise_manual_activation: bool
  reserve1: bool
  reserve2: bool
  reserve3: bool
  reserve4: bool


@dataclass
class MuxedJoystick:
  # src: str  # "udp" | "web" | "none"
  t_ns: int
  axes: List[float]
  buttons: List[bool]
  enabled: bool = False

  @property
  def valid(self) -> bool:
    return bool(self.buttons[0]) if len(self.buttons) > 2 else False

  @property
  def enabled(self) -> bool:
    return bool(self.buttons[1]) if len(self.buttons) > 2 else False


class RemoteControlMux:
  def __init__(
      self,
      udp: UdpJoyTelemetryBridge,
      udp_timeout_ms: int = 400,
      web_timeout_ms: int = 800,
      on_control_mode_change_p = None
  ) -> None:
    self.udp = udp
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

  def update_from_web(self, msg: JoystickCommands, client_id: str) -> None:

    self._web_cmd = MuxedJoystick(
      t_ns=monotonic_ns(),
      axes=[msg.steering_and_angle_deg, msg.brake_and_accel],
      buttons=[
        True,
        msg.control_enabled,
        msg.cruise_manual_activation,
        msg.reserve1,
        msg.reserve2,
        msg.reserve3,
        msg.reserve4
      ],
      enabled=msg.control_enabled
    )


  def update_from_udp(self, axes: List[float], buttons: List[bool]) -> None:
    self._udp_cmd = MuxedJoystick(
      t_ns=monotonic_ns(),
      axes=[msg.steering_and_angle_deg, msg.brake_and_accel],
      buttons=[
        True,
        msg.control_enabled,
        msg.cruise_manual_activation,
        msg.reserve1,
        msg.reserve2,
        msg.reserve3,
        msg.reserve4
      ],
      enabled=msg.control_enabled
    )

  def _fresh(self, now_ns: int, last_ns: int, timeout_ns: int) -> bool:
    return last_ns != 0 and (now_ns - last_ns) <= timeout_ns

  def _set_enabled(self, enabled):
    if self.enabled != enabled:
      self.enabled = enabled
      if self.on_control_mode_change_p is not None:
        self.on_control_mode_change_p(enabled)

  def get_joystick(self) -> MuxedJoystick:
    now = monotonic_ns()

    udp_pkt: Optional[JoyPacket] = self.udp.get_last_joy()
    if udp_pkt is not None and self._fresh(now, udp_pkt.t_rx_ns, self.udp_timeout_ns):
      axes = udp_pkt.axes
      buttons = udp_pkt.buttons
      if len(axes) < self.min_axes:
        axes = (axes + [0.0] * self.min_axes)[:self.min_axes]
      if len(buttons) < self.min_buttons:
        buttons = (buttons + [False] * self.min_buttons)[:self.min_buttons]

      mj = MuxedJoystick(src="udp", t_ns=now, axes=axes[:self.min_axes], buttons=buttons[:])
      self._set_enabled(mj.enabled)
      return mj

    if self._fresh(now, self._web_last_ns, self.web_timeout_ns):
      mj = MuxedJoystick(src="web", t_ns=now, axes=self._web_axes[:], buttons=self._web_buttons[:])
      self._set_enabled(mj.enabled)
      return mj

    mj = MuxedJoystick(src="none", t_ns=now, axes=[0.0]*self.min_axes, buttons=[False]*self.min_buttons)

    self._set_enabled(False)
    return mj

  def _norm_axes_buttons(axes, buttons, min_axes=2, min_buttons=7):
    if axes is None: axes = []
    if buttons is None: buttons = []
    if len(axes) < min_axes:
      axes = (list(axes) + [0.0] * min_axes)[:min_axes]
    if len(buttons) < min_buttons:
      buttons = (list(buttons) + [False] * min_buttons)[:min_buttons]
    axes = [float(x) for x in axes[:min_axes]]
    buttons = [bool(x) for x in buttons]
    return axes, buttons

  def _valid(buttons) -> bool:
    return bool(buttons[0]) if len(buttons) > 2 else False

  def _enabled(buttons) -> bool:
    return bool(buttons[1]) if len(buttons) > 2 else False

  def get(self):
    now = monotonic_ns()

    # --- read UDP (if fresh) ---
    udp_axes = None
    udp_buttons = None
    udp_fresh = (self.udp.last_joy is not None) and self._fresh(now, self.udp.last_joy_rx_ns, self.udp_timeout_ns)
    if udp_fresh:
      udp_axes, udp_buttons = _norm_axes_buttons(self.udp.last_joy["axes"], self.udp.last_joy["buttons"])

    # --- read WEB (if fresh) ---
    web_axes = None
    web_buttons = None
    web_fresh = self._fresh(now, self.web_rx_ns, self.web_timeout_ns)
    if web_fresh:
      web_axes, web_buttons = _norm_axes_buttons(self.web_axes, self.web_buttons)

    # --- compute status flags ---
    web_ok = web_fresh and _valid(web_buttons)
    udp_ok = udp_fresh and _valid(udp_buttons)

    web_en = web_ok and _enabled(web_buttons)
    udp_en = udp_ok and _enabled(udp_buttons)

    # --- arbitration by control_enabled (buttons[1]) with WEB priority ---
    if web_en:
      chosen_axes, chosen_buttons, src = web_axes, web_buttons, "web"
    elif udp_en:
      chosen_axes, chosen_buttons, src = udp_axes, udp_buttons, "udp"
    else:
      # никто не "включил" контроль -> safe
      chosen_axes, chosen_buttons, src = [0.0, 0.0], [False, False], "none"

    # export enabled/active
    self.enabled = _enabled(chosen_buttons)
    self.active = _valid(chosen_buttons) and self.enabled
    self.src = src
    return chosen_axes, chosen_buttons, src
