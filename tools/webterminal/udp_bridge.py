#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import socket
import time
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any, Callable

from openpilot.tools.webterminal.remote_control_mux import JoystickCommands




def monotonic_ns() -> int:
  return time.monotonic_ns()


@dataclass
class JoyPacket:
  t_rx_ns: int
  seq: int
  axes: List[float]
  buttons: List[bool]
  src: Tuple[str, int]


class UdpJoyTelemetryBridge(asyncio.DatagramProtocol):
  """
  UDP:
    - receive joystick commands (JSON datagrams)
    - send telemetry datagrams (JSON) to configured peer or last joystick sender
  """

  def __init__(
      self,
      listen_host: str = "0.0.0.0",
      listen_port: int = 14550,
      send_port: int = 14551,
      publisher_p: Optional[Callable[[JoystickCommands], None]] = None,
      telemetry_peer: Optional[Tuple[str, int]] = None,
      use_last_sender_as_peer: bool = True,
      max_datagram_bytes: int = 2048,
      logger: Optional[Any] = None
  ) -> None:
    self.listen_host = listen_host
    self.listen_port = listen_port
    self.send_port = send_port
    self.telemetry_peer = telemetry_peer
    self.use_last_sender_as_peer = use_last_sender_as_peer
    self.max_datagram_bytes = max_datagram_bytes

    self._transport: Optional[asyncio.DatagramTransport] = None
    self._last_joy: Optional[JoyPacket] = None
    self._last_sender: Optional[Tuple[str, int]] = None
    self._logger = logger
    self.publisher_p = publisher_p

  def _log(self, msg: str) -> None:
    if self._logger is not None:
      self._logger(msg)

  # asyncio.DatagramProtocol
  def connection_made(self, transport: asyncio.BaseTransport) -> None:
    self._transport = transport  # type: ignore[assignment]

  def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
    """
    Expected joystick command JSON format:
    {
        seq: int
        steering_angle_deg: float
        brake_and_accel: float
        control_enabled: bool
        cruise_manual_set: bool
        ext_flags: List[bool]
    }
    """
    if len(data) > self.max_datagram_bytes:
      return

    try:
      payload = json.loads(data.decode("utf-8", errors="strict"))
      ext_flags = payload.get("ext_flags", [False, False, False, False])

      joystick = JoystickCommands(
        seq=int(payload.get("seq", 0)),
        steering_angle_deg=float(payload.get("steering_angle_deg", 0.0)),
        brake_and_accel=float(payload.get("brake_and_accel", 0.0)),
        control_enabled=bool(payload.get("control_enabled", False)),
        cruise_manual_set=bool(payload.get("cruise_manual_set", False)),
        ext_flags=[bool(x) for x in ext_flags]
      )
    except Exception as e:
      self._log(f"UdpJoyTelemetryBridge: failed to parse joystick datagram from {addr}: {e}")
      return

    self._last_sender = addr
    if self._last_joy is None or joystick.seq > self._last_joy.seq:
      self._last_joy = joystick
      if self.publisher_p is not None:
        self.publisher_p(joystick)

    # ignore out-of-order packets

    return


  def error_received(self, exc: Exception) -> None:
    # deliberately ignore to avoid log spam
    pass

  def connection_lost(self, exc: Optional[Exception]) -> None:
    self._transport = None

  async def start(self) -> None:
    loop = asyncio.get_running_loop()
    await loop.create_datagram_endpoint(
      lambda: self,
      local_addr=(self.listen_host, self.listen_port),
    )

  def get_last_joy(self) -> Optional[JoyPacket]:
    return self._last_joy

  def _get_telemetry_peer(self) -> Optional[Tuple[str, int]]:
    if self.telemetry_peer is not None:
      return self.telemetry_peer
    if self.use_last_sender_as_peer and self._last_sender is not None:
      pear: Tuple[str, int] = (self._last_sender[0], self.send_port)
      return pear
    return None

  def send_telemetry(self, msg: Dict[str, Any]) -> None:
    peer = self._get_telemetry_peer()
    if peer is None or self._transport is None:
      return
    try:
      data = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
      if len(data) > self.max_datagram_bytes:
        return
      self._transport.sendto(data, peer)
    except Exception:
      return


