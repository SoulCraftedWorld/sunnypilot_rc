import asyncio
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from aiohttp import web

def now_ns() -> int:
  return time.monotonic_ns()

@dataclass
class ClientLease:
  client_id: str
  last_seen_ns: int
  ip: str
  user_agent: str
  kind: str            # "udp" | "web" | "unknown"
  is_master: bool

class ClientRegistry:
  def __init__(self, timeout_ms: int = 800) -> None:
    self.timeout_ns = int(timeout_ms * 1e6)
    self.clients: Dict[str, ClientLease] = {}
    self.master_id: Optional[str] = None
    self.primary_kind = "web" # "autoware"

  def touch(self, client_id: str, ip: str, user_agent: str, kind: str, want_master: bool) -> ClientLease:
    """Register or update a client lease.
    Args:
      client_id: Unique identifier for the client.
      ip: Client's IP address.
      user_agent: Client's user agent string.
      kind: Type of client ("udp", "web", "unknown").
      want_master: Whether the client wants to be the master.
    """
    t = now_ns()

    # register/update
    lease = self.clients.get(client_id)
    if lease is None:
      lease = ClientLease(
        client_id=client_id,
        last_seen_ns=t,
        ip=ip,
        user_agent=user_agent,
        kind=kind,
        is_master=False,
      )
      self.clients[client_id] = lease
    else:
      lease.last_seen_ns = t
      lease.ip = ip
      lease.user_agent = user_agent
      lease.kind = kind

    # master selection (simple policy):
    # - if no master, allow claim
    # - if master already equals this client, keep it
    # - else ignore claim
    if want_master:
      if self.master_id is None or self.master_id == client_id:
        self.master_id = client_id
        lease.is_master = True
      elif self.clients.get(self.master_id) is None or self.clients[self.master_id].kind != self.primary_kind:
        # allow takeover if current master is not primary kind
        self.master_id = client_id
        lease.is_master = True
      else:
        lease.is_master = False

    # ensure only one is_master flag
    if self.master_id is not None:
      for cid, l in self.clients.items():
        l.is_master = (cid == self.master_id)

    return lease

  def purge_dead(self) -> None:
    t = now_ns()
    dead = [cid for cid, l in self.clients.items() if (t - l.last_seen_ns) > self.timeout_ns]
    for cid in dead:
      self.clients.pop(cid, None)
      if self.master_id == cid:
        self.master_id = None

  def get_current_control_source(self) -> Optional[ClientLease]:
    if self.master_id is None:
      return None
    return self.clients.get(self.master_id)

  def has_live_master(self) -> bool:
    if self.master_id is None:
      return False
    l = self.clients.get(self.master_id)
    if l is None:
      return False
    return (now_ns() - l.last_seen_ns) <= self.timeout_ns

  def snapshot(self):
    self.purge_dead()
    return {
      "master_id": self.master_id,
      "has_live_master": self.has_live_master(),
      "clients": [
        {
          "client_id": l.client_id,
          "ip": l.ip,
          "kind": l.kind,
          "is_master": l.is_master,
          "age_ms": int((now_ns() - l.last_seen_ns) / 1e6),
        } for l in self.clients.values()
      ]
    }

