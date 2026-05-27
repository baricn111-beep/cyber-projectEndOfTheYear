#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════╗
║           DINO RUN  —  Multiplayer Server                ║
╠══════════════════════════════════════════════════════════╣
║  Usage:  python server.py [port]                         ║
║  Default port: 5555                                      ║
║                                                          ║
║  Start the server first, then have BOTH players run      ║
║  client.py on their own machines.                        ║
╚══════════════════════════════════════════════════════════╝
"""

import socket
import threading
import json
import time
import random
import sys

# ─── Screen / World Constants ────────────────────────────────────────────────
W, H        = 900, 450
GROUND_Y    = 345           # y-coordinate of ground surface (pixels from top)
FPS         = 60

# ─── Physics ─────────────────────────────────────────────────────────────────
GRAVITY     = 0.72
JUMP_V      = -15.5

# ─── Game Speed ──────────────────────────────────────────────────────────────
INIT_SPEED  = 5.0
MAX_SPEED   = 13.0
SPEED_INC   = 0.0016        # px per frame² speed increase

# ─── Avalanche ───────────────────────────────────────────────────────────────
# --- Lines 41-55 in server.py ---
# AVALANCHE DISABLED (The "Lava Wall" will never reach players)
AVAL_X0     = -9999.0  
AVAL_BASE   = 0.0      
AVAL_ACC    = 0.0      

# PLAYER LAYOUT (P1 is no longer "trapped" by the wall)
P1_SX, P2_SX = 110, 185 

# UPDATED HITBOXES (Cactus style: Taller and Thinner)
DINO_W      = 38
DINO_H      = 52
DINO_DUCK_H = 26

ROCK_W      = 24   # Thinner for Cacti
ROCK_H      = 46   # Taller for Cacti

# ─── Player Layout ───────────────────────────────────────────────────────────
P1_SX, P2_SX = 110, 175     # fixed screen-x positions

# ─── Object Sizes ────────────────────────────────────────────────────────────
DINO_W      = 38
DINO_H      = 52
DINO_DUCK_H = 26

ROCK_W      = 34
ROCK_H      = 38

PTERO_W     = 54
PTERO_H     = 26
PTERO_Y     = GROUND_Y - 58   # must duck to avoid

EGG_W       = 20
EGG_H       = 26

PORT        = int(sys.argv[1]) if len(sys.argv) > 1 else 5555


# ─── Helpers ─────────────────────────────────────────────────────────────────
def rects_overlap(r1, r2):
    x1, y1, w1, h1 = r1
    x2, y2, w2, h2 = r2
    return (x1 < x2 + w2 and x1 + w1 > x2 and
            y1 < y2 + h2 and y1 + h1 > y2)


# ─── Game Objects ────────────────────────────────────────────────────────────
class Player:
    def __init__(self, pid, sx):
        self.id      = pid
        self.sx      = sx
        self.y       = float(GROUND_Y)
        self.vy      = 0.0
        self.alive   = True
        self.ducking = False
        self.score   = 0
        # inputs written by network thread
        self.inp_jump = False
        self.inp_duck = False

    def update(self):
        if not self.alive:
            return
        on_ground = self.y >= GROUND_Y - 1
        if self.inp_jump and on_ground:
            self.vy = JUMP_V
        self.vy += GRAVITY
        self.y  += self.vy
        if self.y >= GROUND_Y:
            self.y  = GROUND_Y
            self.vy = 0.0
        self.ducking = self.inp_duck and on_ground

    def rect(self):
        """Axis-aligned bounding box: (left, top, w, h)"""
        h = DINO_DUCK_H if self.ducking else DINO_H
        return (self.sx, self.y - h, DINO_W, h)

    def as_dict(self):
        return {
            'id'     : self.id,
            'sx'     : self.sx,
            'y'      : round(self.y, 1),
            'alive'  : self.alive,
            'ducking': self.ducking,
            'score'  : self.score,
        }


class Obstacle:
    def __init__(self, x, kind):
        self.x    = float(x)
        self.kind = kind        # 'rock' or 'ptero'
        if kind == 'rock':
            self.y = GROUND_Y - ROCK_H
            self.w, self.h = ROCK_W, ROCK_H
        else:
            self.y = PTERO_Y
            self.w, self.h = PTERO_W, PTERO_H

    def as_dict(self):
        return {'x': round(self.x, 1), 'y': self.y,
                'w': self.w, 'h': self.h, 'kind': self.kind}


class Egg:
    def __init__(self, x):
        self.x     = float(x)
        self.y     = GROUND_Y - EGG_H
        self.taken = [False, False]

    def as_dict(self):
        return {'x': round(self.x, 1), 'y': self.y,
                'w': EGG_W, 'h': EGG_H, 'taken': self.taken[:]}


# ─── Game State Machine ───────────────────────────────────────────────────────
class Game:
    """All game logic lives here; completely independent of networking."""

    def __init__(self):
        self.wins      = [0, 0]
        self.round_num = 0
        self.phase     = 'splash'  # splash | playing | round_end | game_over
        self._init_round()

    # ── Round Management ─────────────────────────────────────────────────────
    def _init_round(self):
        self.players   = [Player(0, P1_SX), Player(1, P2_SX)]
        self.obstacles = []
        self.eggs      = []
        self.speed     = INIT_SPEED
        self.aval_x    = AVAL_X0
        self.frame     = 0
        self.delay     = 0          # countdown timer (frames)
        # Spawn timers (distance remaining until next spawn, in px)
        self.next_obs  = float(random.randint(320, 520))
        self.next_egg  = float(random.randint(250, 450))

    def start_round(self):
        self._init_round()
        self.phase      = 'playing'
        self.round_num += 1

    # ── Main Update (called every frame) ─────────────────────────────────────
    def update(self):
        if self.phase == 'splash':
            return

        if self.phase in ('round_end', 'game_over'):
            self.delay -= 1
            if self.delay <= 0:
                if self.phase == 'round_end':
                    self.start_round()
                else:           # game_over → restart whole match
                    self.wins      = [0, 0]
                    self.round_num = 0
                    self._init_round()
                    self.phase = 'splash'
            return

        # ── Advance frame ────────────────────────────────────────────────────
        f           = self.frame
        self.frame += 1
        self.speed  = min(MAX_SPEED, INIT_SPEED + f * SPEED_INC)
        self.aval_x += AVAL_BASE + f * AVAL_ACC

        # ── Spawn obstacles ──────────────────────────────────────────────────
        self.next_obs -= self.speed
        if self.next_obs <= 0:
            # Occasionally spawn double rocks
            kind  = random.choices(['rock', 'ptero', 'rock'], weights=[55, 30, 15])[0]
            spawn = W + 80
            self.obstacles.append(Obstacle(spawn, kind))
            # Sometimes a second rock right after the first
            if kind == 'rock' and random.random() < 0.25:
                self.obstacles.append(Obstacle(spawn + ROCK_W + 18, 'rock'))
            self.next_obs = float(random.randint(230, 500))

        # ── Spawn eggs ───────────────────────────────────────────────────────
        self.next_egg -= self.speed
        if self.next_egg <= 0:
            self.eggs.append(Egg(W + 60))
            self.next_egg = float(random.randint(200, 420))

        # ── Move objects ─────────────────────────────────────────────────────
        for o in self.obstacles:
            o.x -= self.speed
        for e in self.eggs:
            e.x -= self.speed

        self.obstacles = [o for o in self.obstacles if o.x > -140]
        self.eggs      = [e for e in self.eggs      if e.x > -60]

        # ── Update players ───────────────────────────────────────────────────
        for p in self.players:
            p.update()
            if not p.alive:
                continue

            # Caught by avalanche?
            if self.aval_x >= p.sx:
                p.alive = False
                continue

            pr = p.rect()

            # Obstacle collision?
            for o in self.obstacles:
                if rects_overlap(pr, (o.x, o.y, o.w, o.h)):
                    p.alive = False
                    break
            if not p.alive:
                continue

            # Egg pickup?
            for e in self.eggs:
                if not e.taken[p.id]:
                    if rects_overlap(pr, (e.x, e.y, EGG_W, EGG_H)):
                        e.taken[p.id] = True
                        p.score      += 10

            # Survival score (one point per frame alive)
            p.score += 1

        # ── Check round end ──────────────────────────────────────────────────
        alive = [p for p in self.players if p.alive]
        if len(alive) < 2:
            if len(alive) == 1:
                w = alive[0].id
                self.wins[w] += 1

            if max(self.wins) >= 2:         # match decided
                self.phase = 'game_over'
                self.delay = FPS * 10
            else:
                self.phase = 'round_end'
                self.delay = FPS * 4

    # ── Serialise state for broadcast ────────────────────────────────────────
    def state(self):
        return {
            'phase'    : self.phase,
            'wins'     : self.wins[:],
            'round'    : self.round_num,
            'speed'    : round(self.speed, 2),
            'aval_x'   : round(self.aval_x, 1),
            'players'  : [p.as_dict()  for p in self.players],
            'obstacles': [o.as_dict()  for o in self.obstacles],
            'eggs'     : [e.as_dict()  for e in self.eggs],
        }


# ─── Networking ──────────────────────────────────────────────────────────────
game    = Game()
clients = [None, None]
lock    = threading.Lock()


def recv_loop(sock, pid):
    """Background thread: read client input, update game player input."""
    buf = ''
    sock.settimeout(2.0)
    while True:
        try:
            chunk = sock.recv(512).decode('utf-8', errors='replace')
            if not chunk:
                break
            buf += chunk
            while '\n' in buf:
                line, buf = buf.split('\n', 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    with lock:
                        p = game.players[pid]
                        p.inp_jump = bool(msg.get('j', False))
                        p.inp_duck = bool(msg.get('d', False))
                        if game.phase == 'splash' and msg.get('start', False):
                            game.start_round()
                except json.JSONDecodeError:
                    pass
        except socket.timeout:
            continue
        except OSError:
            break
    print(f'[server] Player {pid + 1} disconnected.')


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', PORT))
    srv.listen(2)

    local_ip = socket.gethostbyname(socket.gethostname())
    print(f'╔══════════════════════════════════════════╗')
    print(f'║      DINO RUN SERVER  —  Ready           ║')
    print(f'╠══════════════════════════════════════════╣')
    print(f'║  Host IP  : {local_ip:<28} ║')
    print(f'║  Port     : {PORT:<28} ║')
    print(f'║                                          ║')
    print(f'║  Waiting for 2 players to connect…      ║')
    print(f'╚══════════════════════════════════════════╝')

    for pid in range(2):
        conn, addr = srv.accept()
        print(f'[server] Player {pid + 1} connected from {addr[0]}:{addr[1]}')
        clients[pid] = conn
        hello = json.dumps({'welcome': pid}).encode() + b'\n'
        conn.sendall(hello)
        t = threading.Thread(target=recv_loop, args=(conn, pid), daemon=True)
        t.start()

    print('[server] Both players connected!  Showing splash screen…')

    interval = 1.0 / FPS
    while True:
        t0 = time.perf_counter()

        with lock:
            game.update()
            st = game.state()

        msg = json.dumps(st).encode() + b'\n'
        for c in clients:
            if c:
                try:
                    c.sendall(msg)
                except OSError:
                    pass

        elapsed = time.perf_counter() - t0
        sleep   = interval - elapsed
        if sleep > 0:
            time.sleep(sleep)


if __name__ == '__main__':
    main()
