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
import struct

# ─── Screen / World Constants ────────────────────────────────────────────────
W, H = 900, 450
GROUND_Y = 345
FPS = 60

# ─── Physics ─────────────────────────────────────────────────────────────────
GRAVITY = 0.72
JUMP_V = -15.5

# ─── Game Speed ──────────────────────────────────────────────────────────────
INIT_SPEED = 5.0
MAX_SPEED = 13.0
SPEED_INC = 0.0016

# ─── Avalanche ───────────────────────────────────────────────────────────────
AVAL_X0 = -9999.0
AVAL_BASE = 0.0
AVAL_ACC = 0.0

# ─── Player Layout ───────────────────────────────────────────────────────────
P1_SX, P2_SX = 110, 175

# ─── Object Sizes ────────────────────────────────────────────────────────────
DINO_W = 38
DINO_H = 52
DINO_DUCK_H = 26

ROCK_W = 34
ROCK_H = 38

PTERO_W = 54
PTERO_H = 26
PTERO_Y = GROUND_Y - 58

EGG_W = 20
EGG_H = 26

PORT = 5555


# ─── Network Protocol Helpers ────────────────────────────────────────────────
def send_msg(sock, data_dict):
    """
    Encodes a data dictionary into JSON format, prefixes it with a 4-byte 
    length header, and sends it completely over the specified network socket.

    :param sock: Target socket destination connection.
    :param data_dict: Context tracking metric updates to serialize and transmit.
    """
    raw_json = json.dumps(data_dict).encode('utf-8')
    header = struct.pack('!I', len(raw_json))
    sock.sendall(header + raw_json)


def recv_exact(sock, num_bytes):
    """
    Blocks until an exact number of bytes is received over a socket. 
    Prevents errors caused by network data fragmentation.

    :param sock: Active reading socket pipeline stream.
    :param num_bytes: Integer detailing required buffer sizes.
    :return: Completed data payload containing the exact bytes requested.
    """
    buf = b''
    while len(buf) < num_bytes:
        chunk = sock.recv(num_bytes - len(buf))
        if not chunk:
            raise OSError("Connection closed")
        buf += chunk
    return buf


def recv_msg(sock):
    """
    Reads the length header and extracts the underlying JSON message string from 
    a socket, returning it as a native dictionary mapping structure.

    :param sock: Target active pipeline connection.
    :return: Unpacked data payload dictionary context map, or None if error.
    """
    try:
        header = recv_exact(sock, 4)
        msg_len = struct.unpack('!I', header)[0]
        raw_json = recv_exact(sock, msg_len)
        return json.loads(raw_json.decode('utf-8'))
    except (OSError, json.JSONDecodeError, struct.error):
        return None


# ─── Helpers ─────────────────────────────────────────────────────────────────
def rects_overlap(r1, r2):
    """
    Executes standard 2D AABB Axis-Aligned Bounding Box calculation to determine 
    if any collision or intersection occurs between two rectangular entities.

    :param r1: Coordinates tuple representing bounding box 1 (x, y, width, height).
    :param r2: Coordinates tuple representing bounding box 2 (x, y, width, height).
    :return: Boolean validation signaling intersection state overlap.
    """
    x1, y1, w1, h1 = r1
    x2, y2, w2, h2 = r2
    return (x1 < x2 + w2 and x1 + w1 > x2 and
            y1 < y2 + h2 and y1 + h1 > y2)


# ─── Game Objects ────────────────────────────────────────────────────────────
class Player:
    def __init__(self, pid, sx):
        """
        Initializes individual player state tracking parameters, placement layout metrics, 
        and ongoing control keys.

        :param pid: Integer index tracking identity (0 for Player 1, 1 for Player 2).
        :param sx: Constant spawn horizontal point coordinate alignment.
        """
        self.id = pid
        self.sx = sx
        self.y = float(GROUND_Y)
        self.vy = 0.0
        self.alive = True
        self.ducking = False
        self.score = 0
        self.inp_jump = False
        self.inp_duck = False

    def update(self):
        """
        Applies gravitational acceleration physics to positions and handles structural vertical jumping 
        and crouching states based on the latest input.
        """
        if not self.alive:
            return
        on_ground = self.y >= GROUND_Y - 1
        if self.inp_jump and on_ground:
            self.vy = JUMP_V
        self.vy += GRAVITY
        self.y += self.vy
        if self.y >= GROUND_Y:
            self.y = GROUND_Y
            self.vy = 0.0
        self.ducking = self.inp_duck and on_ground

    def rect(self):
        """
        Computes the current geometric collision rectangle context configuration.

        :return: Tuple parameters mapping out (x, y, width, height).
        """
        h = DINO_DUCK_H if self.ducking else DINO_H
        return (self.sx, self.y - h, DINO_W, h)

    def as_dict(self):
        """
        Transforms the player class instance attributes into a lightweight dictionary for network serialization.

        :return: Clean dictionary representation mapping out player metrics.
        """
        return {
            'id': self.id,
            'sx': self.sx,
            'y': round(self.y, 1),
            'alive': self.alive,
            'ducking': self.ducking,
            'score': self.score,
        }


class Obstacle:
    def __init__(self, x, kind):
        """
        Initializes an obstacle obstacle element (e.g., Ground Rock or airborne Pterodactyl).

        :param x: Float specifying initialization horizontal spacing coordinate.
        :param kind: String description labeling structure configurations ('rock' or 'ptero').
        """
        self.x = float(x)
        self.kind = kind
        if kind == 'rock':
            self.y = GROUND_Y - ROCK_H
            self.w, self.h = ROCK_W, ROCK_H
        else:
            self.y = PTERO_Y
            self.w, self.h = PTERO_W, PTERO_H

    def as_dict(self):
        """
        Packages obstacle attributes into a structured format suitable for message packets.

        :return: Data schema tracking coordinate positioning configuration variables.
        """
        return {'x': round(self.x, 1), 'y': self.y,
                'w': self.w, 'h': self.h, 'kind': self.kind}


class Egg:
    def __init__(self, x):
        """
        Spawns a collectible egg point component at a specific coordinate tracking distance location.

        :param x: Base float axis placement marker coordinate.
        """
        self.x = float(x)
        self.y = GROUND_Y - EGG_H
        self.taken = [False, False]

    def as_dict(self):
        """
        Converts the egg instance into a map structure detailing configuration parameters.

        :return: Object serialization parameters tracker tracking current state parameters.
        """
        return {'x': round(self.x, 1), 'y': self.y,
                'w': EGG_W, 'h': EGG_H, 'taken': self.taken[:]}


# ─── Game State Machine ───────────────────────────────────────────────────────
class Game:
    def __init__(self):
        """
        Initializes the top-level server match state machine, scoreboard configurations, 
        and structural state records.
        """
        self.wins = [0, 0]
        self.round_num = 0
        self.phase = 'splash'
        self._init_round()

    def _init_round(self):
        """
        Resets and clears round-specific tracking states, emptying lists for hazards/collectibles 
        and initializing placement coordinates.
        """
        self.players = [Player(0, P1_SX), Player(1, P2_SX)]
        self.obstacles = []
        self.eggs = []
        self.speed = INIT_SPEED
        self.aval_x = AVAL_X0
        self.frame = 0
        self.delay = 0
        self.next_obs = float(random.randint(320, 520))
        self.next_egg = float(random.randint(250, 450))

    def start_round(self):
        """
        Triggers transitions to activate core physics tick computations, clearing past tracking buffers 
        and advancing phase metrics.
        """
        self._init_round()
        self.phase = 'playing'
        self.round_num += 1

    def update(self):
        """
        Executes the main server-side game logic frame tick. Simulates obstacle movement, 
        procedurally generates map hazards, updates character positions, checks for entity collisions, 
        and manages score updates and round termination delays.
        """
        if self.phase in ('splash', 'disconnect'):
            return

        if self.phase in ('round_end', 'game_over'):
            self.delay -= 1
            if self.delay <= 0:
                if self.phase == 'round_end':
                    self.start_round()
                else:
                    self.wins = [0, 0]
                    self.round_num = 0
                    self._init_round()
                    self.phase = 'splash'
            return

        f = self.frame
        self.frame += 1
        self.speed = min(MAX_SPEED, INIT_SPEED + f * SPEED_INC)
        self.aval_x += AVAL_BASE + f * AVAL_ACC

        self.next_obs -= self.speed
        if self.next_obs <= 0:
            kind = random.choices(
                ['rock', 'ptero', 'rock'], weights=[55, 30, 15])[0]
            spawn = W + 80
            self.obstacles.append(Obstacle(spawn, kind))
            if kind == 'rock' and random.random() < 0.25:
                self.obstacles.append(Obstacle(spawn + ROCK_W + 18, 'rock'))
            self.next_obs = float(random.randint(230, 500))

        self.next_egg -= self.speed
        if self.next_egg <= 0:
            self.eggs.append(Egg(W + 60))
            self.next_egg = float(random.randint(200, 420))

        for o in self.obstacles:
            o.x -= self.speed
        for e in self.eggs:
            e.x -= self.speed

        self.obstacles = [o for o in self.obstacles if o.x > -140]
        self.eggs = [e for e in self.eggs if e.x > -60]

        for p in self.players:
            p.update()
            if not p.alive:
                continue

            if self.aval_x >= p.sx:
                p.alive = False
                continue

            pr = p.rect()

            for o in self.obstacles:
                if rects_overlap(pr, (o.x, o.y, o.w, o.h)):
                    p.alive = False
                    break
            if not p.alive:
                continue

            for e in self.eggs:
                if not e.taken[p.id]:
                    if rects_overlap(pr, (e.x, e.y, EGG_W, EGG_H)):
                        e.taken[p.id] = True
                        p.score += 10

            p.score += 1

        alive = [p for p in self.players if p.alive]
        if len(alive) < 2:
            if len(alive) == 1:
                w = alive[0].id
                self.wins[w] += 1

            if max(self.wins) >= 2:
                self.phase = 'game_over'
                self.delay = FPS * 10
            else:
                self.phase = 'round_end'
                self.delay = FPS * 4

    def state(self):
        """
        Unpacks entire framework object instances, consolidating attributes into standard Python objects.

        :return: Central state dictionary representing the authoritative game world.
        """
        return {
            'phase': self.phase,
            'wins': self.wins[:],
            'round': self.round_num,
            'speed': round(self.speed, 2),
            'aval_x': round(self.aval_x, 1),
            'players': [p.as_dict() for p in self.players],
            'obstacles': [o.as_dict() for o in self.obstacles],
            'eggs': [e.as_dict() for e in self.eggs],
        }


# ─── Networking ──────────────────────────────────────────────────────────────
game = Game()
clients = [None, None]


def recv_loop(sock, pid):
    """
    Asynchronous network listening function attached to every connected client socket. 
    Continuously listens for incoming keystroke inputs and flags game start activation signals.

    :param sock: Connected communication line mapping to client console target.
    :param pid: Integer mapping identity tracker (0 or 1).
    """
    """Background thread: read client input, update game player input."""
    while True:
        msg = recv_msg(sock)
        if msg is None:
            break

        p = game.players[pid]
        p.inp_jump = bool(msg.get('j', False))
        p.inp_duck = bool(msg.get('d', False))
        if game.phase == 'splash' and msg.get('start', False):
            game.start_round()

    print(f'[server] Player {pid + 1} disconnected.')
    clients[pid] = None
    game.phase = 'disconnect'


def main():
    """
    Primary operational server thread bootstrap. Generates listening TCP server sockets, 
    waits for both players to connect, attaches input receiver loop listeners, 
    and drives the strict 60 FPS state broadcast broadcast pipeline.
    """
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
    print(f'║  Waiting for 2 players to connect…       ║')
    print(f'╚══════════════════════════════════════════╝')

    for pid in range(2):
        conn, addr = srv.accept()
        print(f'[server] Player {pid + 1} connected from {addr[0]}:{addr[1]}')
        clients[pid] = conn

        send_msg(conn, {'welcome': pid})

        t = threading.Thread(target=recv_loop, args=(conn, pid), daemon=True)
        t.start()

    print('[server] Both players connected!  Showing splash screen…')

    interval = 1.0 / FPS
    while True:
        t0 = time.perf_counter()

        if game.phase != 'disconnect':
            game.update()
        st = game.state()

        raw_json = json.dumps(st).encode('utf-8')
        packet = struct.pack('!I', len(raw_json)) + raw_json

        for c in clients:
            if c:
                try:
                    c.sendall(packet)
                except OSError:
                    pass

        elapsed = time.perf_counter() - t0
        sleep = interval - elapsed
        if sleep > 0:
            time.sleep(sleep)


if __name__ == '__main__':
    main()
