import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple

def now_ns() -> int:
  return time.monotonic_ns()

@dataclass
class ClientLease:
  client_id: str
  last_seen_ns: int
  ip: str
  user_agent: str
  is_master: bool

@dataclass
class SnapshotClientInfo:
  client_id: str
  ip: str
  is_master: bool
  kind: str
  age_ms: int

@dataclass
class SnapshotInfo:
  master_id: Optional[str]
  has_live_master: bool
  clients: List[SnapshotClientInfo]

class ClientRegistry:
  def __init__(self, timeout_ms: int = 800, kind: str = 'web') -> None:
    self.timeout_ns = int(timeout_ms * 1e6)
    self.clients: Dict[str, ClientLease] = {}
    self.master_id: Optional[str] = None
    self.kind = kind
    self._lock = threading.Lock()

  def touch(self, client_id: str, ip: str, user_agent: str) -> bool:
    """Register or update a client lease.
    Args:
      client_id: Unique identifier for the client.
      ip: Client's IP address.
      user_agent: Client's user agent string.

    return:
      is it master
    """
    with self._lock:
      t = now_ns()
      # ensure only one is_master flag
      if self.master_id is None:
        self.master_id = client_id

      # register/update
      lease = self.clients.get(client_id)
      if lease is None:
        lease = ClientLease(
          client_id=client_id,
          last_seen_ns=t,
          ip=ip,
          user_agent=user_agent,
          is_master=(client_id == self.master_id),
        )
        self.clients[client_id] = lease
      else:
        lease.last_seen_ns = t
        lease.ip = ip
        lease.user_agent = user_agent
        lease.is_master = (client_id == self.master_id)

      # update is_master flags for all (optional but nice)
      for cid, l in self.clients.items():
        l.is_master = (cid == self.master_id)

      return self.master_id == client_id

  def purge_dead(self):
    with self._lock:
      t = now_ns()

      dead = [cid for cid, l in self.clients.items() if (t - l.last_seen_ns) > self.timeout_ns]
      for cid in dead:
        self.clients.pop(cid, None)
        if self.master_id == cid:
          self.master_id = None

      # if master died and someone remains -> pick a new master deterministically
      if self.master_id is None and self.clients:
        self.master_id = sorted(self.clients.keys())[0]
        for cid, l in self.clients.items():
          l.is_master = (cid == self.master_id)


  def _has_live_master(self, t) -> bool:
    l = self.clients.get(self.master_id)
    if l is None:
      return False
    ret = (t - l.last_seen_ns) <= self.timeout_ns
    return ret

  def has_live_master(self) -> bool:
    self.purge_dead()
    return self.master_id is not None and self.master_id in self.clients

  def snapshot(self):
    self.purge_dead()

    with self._lock:
      t = now_ns()
      info = SnapshotInfo(
        master_id=self.master_id,
        has_live_master=self._has_live_master(t),
        clients=[
          SnapshotClientInfo(
            client_id=l.client_id,
            ip=l.ip,
            is_master=l.is_master,
            kind=self.kind,
            age_ms=int((t - l.last_seen_ns) / 1e6),
          ) for l in self.clients.values()
        ],
      )
    return info

  def is_master(self, client_id: str) -> bool:
    return self.master_id == client_id


