#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import socket
import time
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any


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
      telemetry_peer: Optional[Tuple[str, int]] = None,
      use_last_sender_as_peer: bool = True,
      max_datagram_bytes: int = 2048,
  ) -> None:
    self.listen_host = listen_host
    self.listen_port = listen_port
    self.telemetry_peer = telemetry_peer
    self.use_last_sender_as_peer = use_last_sender_as_peer
    self.max_datagram_bytes = max_datagram_bytes

    self._transport: Optional[asyncio.DatagramTransport] = None
    self._last_joy: Optional[JoyPacket] = None
    self._last_sender: Optional[Tuple[str, int]] = None

  # asyncio.DatagramProtocol
  def connection_made(self, transport: asyncio.BaseTransport) -> None:
    self._transport = transport  # type: ignore[assignment]

  def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
    if len(data) > self.max_datagram_bytes:
      return

    try:
      payload = json.loads(data.decode("utf-8", errors="strict"))
      axes = payload.get("axes", [])
      buttons = payload.get("buttons", [])
      seq = int(payload.get("seq", 0))
      if not isinstance(axes, list) or not isinstance(buttons, list):
        return
      axes_f = [float(x) for x in axes]
      buttons_b = [bool(x) for x in buttons]
    except Exception:
      return

    self._last_sender = addr
    self._last_joy = JoyPacket(
      t_rx_ns=monotonic_ns(),
      seq=seq,
      axes=axes_f,
      buttons=buttons_b,
      src=addr,
    )

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
    if self.use_last_sender_as_peer:
      return self._last_sender
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
