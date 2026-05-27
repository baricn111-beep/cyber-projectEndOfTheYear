#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════╗
║           DINO RUN  —  Multiplayer Client                ║
╠══════════════════════════════════════════════════════════╣
║  Usage:  python client.py <server_ip> [port]             ║
║  Example: python client.py 192.168.1.10                  ║
║                                                          ║
║  Requirements:  pip install pygame                       ║
║                                                          ║
║  Player 1 controls:  W = Jump    S  = Duck               ║
║  Player 2 controls:  ↑ = Jump    ↓  = Duck               ║
╚══════════════════════════════════════════════════════════╝
"""

import socket
import threading
import json
import sys
import time
import math
import random

try:
    import pygame
except ImportError:
    print("pygame is required.  Run:  pip install pygame")
    sys.exit(1)

# ─── Connection ───────────────────────────────────────────────────────────────
SERVER_IP = sys.argv[1] if len(sys.argv) > 1 else '127.0.0.1'
PORT      = int(sys.argv[2]) if len(sys.argv) > 2 else 5555

# ─── Screen ──────────────────────────────────────────────────────────────────
W, H      = 900, 450
GROUND_Y  = 345
FPS       = 60
INIT_SPEED = 5

# ─── Colour Palette ──────────────────────────────────────────────────────────
C = {
    'sky_top'   : (100, 180, 230),
    'sky_bot'   : (195, 230, 255),
    'ground'    : (130, 85,  40),
    'grass'     : (72,  155, 55),
    'grass2'    : (55,  130, 40),
    'rock'      : (115, 96,  74),
    'rock_hi'   : (148, 126, 100),
    'rock_sh'   : (82,  66,  50),
    'ptero'     : (75,  55,  110),
    'ptero_hi'  : (105, 80,  150),
    'egg'       : (255, 242, 175),
    'egg_hi'    : (255, 215, 80),
    'doom'      : (45,  12,  8),
    'doom_edge' : (180, 38,  10),
    'doom_glow' : (230, 90,  30),
    'p1'        : (55,  190, 80),
    'p1_hi'     : (130, 240, 140),
    'p2'        : (70,  115, 230),
    'p2_hi'     : (130, 170, 255),
    'white'     : (255, 255, 255),
    'black'     : (0,   0,   0),
    'gold'      : (255, 215, 0),
    'red'       : (220, 60,  60),
    'grey'      : (160, 160, 160),
    'overlay'   : (0,   0,   0),
}

DINO_COLS = [
    (C['p1'], C['p1_hi']),
    (C['p2'], C['p2_hi']),
]

# ─── Shared State (written by network thread, read by render thread) ──────────
_lock        = threading.Lock()
_latest_st   = None
_player_id   = None


# ─── Network Receiver Thread ─────────────────────────────────────────────────
def net_thread(sock):
    global _latest_st, _player_id
    buf = ''
    while True:
        try:
            chunk = sock.recv(8192).decode('utf-8', errors='replace')
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
                    if 'welcome' in msg:
                        _player_id = int(msg['welcome'])
                        print(f'[client] Assigned as Player {_player_id + 1}')
                    else:
                        with _lock:
                            _latest_st = msg
                except json.JSONDecodeError:
                    pass
        except OSError:
            break


# ─── Drawing: Background ─────────────────────────────────────────────────────
_sky_surf = None

def _build_sky():
    global _sky_surf
    _sky_surf = pygame.Surface((W, GROUND_Y))
    t, b = C['sky_top'], C['sky_bot']
    for y in range(GROUND_Y):
        r = t[0] + (b[0] - t[0]) * y // GROUND_Y
        g = t[1] + (b[1] - t[1]) * y // GROUND_Y
        bl= t[2] + (b[2] - t[2]) * y // GROUND_Y
        pygame.draw.line(_sky_surf, (r, g, bl), (0, y), (W, y))


def draw_background(surf, scroll, ft):
    surf.blit(_sky_surf, (0, 0))

    # Parallax clouds
    for i in range(4):
        cx = int((i * 260 - scroll * 0.08 + 40) % (W + 120)) - 60
        cy = 40 + i * 22
        pygame.draw.ellipse(surf, (230, 242, 255), (cx,     cy,    90, 32))
        pygame.draw.ellipse(surf, (240, 248, 255), (cx + 30, cy-10, 70, 28))
        pygame.draw.ellipse(surf, (255, 255, 255), (cx + 15, cy - 8, 55, 22))

    # Distant mountains (slow parallax)
    ms = int(scroll * 0.18) % (W + 380)
    for i in range(3):
        mx = (i * 380 - ms) % (W + 380) - 190
        pts = [(mx, GROUND_Y),
               (mx + 120, GROUND_Y - 110),
               (mx + 240, GROUND_Y - 70),
               (mx + 380, GROUND_Y)]
        pygame.draw.polygon(surf, (155, 140, 168), pts)
        # Snow cap
        snow = [(mx + 105, GROUND_Y - 100),
                (mx + 120, GROUND_Y - 110),
                (mx + 135, GROUND_Y - 100)]
        pygame.draw.polygon(surf, (235, 240, 255), snow)

    # Ground
    pygame.draw.rect(surf, C['ground'], (0, GROUND_Y, W, H - GROUND_Y))
    pygame.draw.rect(surf, C['grass'],  (0, GROUND_Y, W, 9))
    pygame.draw.rect(surf, C['grass2'], (0, GROUND_Y + 9, W, 4))

    # Ground pebbles (fast parallax)
    off = int(scroll * 0.9) % 70
    for x in range(-off, W + 70, 70):
        cx = x + (hash((x // 70)) % 30)
        pygame.draw.circle(surf, (100, 72, 35), (cx, GROUND_Y + 22), 3)
        pygame.draw.circle(surf, (120, 90, 52), (cx + 18, GROUND_Y + 30), 2)


# ─── Drawing: Dino ───────────────────────────────────────────────────────────
def draw_dino(surf, sx, y, ducking, pid, dead=False, step=0):
    base, hi = DINO_COLS[pid]
    if dead:
        base = tuple(min(255, c + 90) for c in base)
        hi   = base

    bx = int(sx)
    by = int(y)

    if ducking:
        # Tail
        pygame.draw.ellipse(surf, base, (bx - 12, by - 22, 18, 12))
        # Body
        pygame.draw.rect(surf, base, (bx, by - 28, 38, 24), border_radius=7)
        pygame.draw.rect(surf, hi,   (bx + 4, by - 26, 16, 8), border_radius=3)
        # Head
        pygame.draw.rect(surf, base, (bx + 20, by - 36, 22, 18), border_radius=5)
        # Snout
        pygame.draw.rect(surf, base, (bx + 36, by - 32, 8, 8), border_radius=3)
        # Eye
        pygame.draw.circle(surf, C['white'], (bx + 34, by - 30), 4)
        pygame.draw.circle(surf, C['black'], (bx + 35, by - 30), 2)
        # Nostril
        pygame.draw.circle(surf, C['rock'],  (bx + 40, by - 28), 1)
        # Legs (short)
        leg_bob = int(math.sin(step * 0.35) * 2)
        pygame.draw.rect(surf, base, (bx + 4,  by - 6 + leg_bob, 9, 8), border_radius=2)
        pygame.draw.rect(surf, base, (bx + 18, by - 6 - leg_bob, 9, 8), border_radius=2)
        # Feet
        pygame.draw.rect(surf, hi,   (bx + 2,  by - 1, 12, 3), border_radius=1)
        pygame.draw.rect(surf, hi,   (bx + 16, by - 1, 12, 3), border_radius=1)
    else:
        leg_bob = int(math.sin(step * 0.35) * 4)
        # Tail
        tail_pts = [(bx + 4, by - 36),
                    (bx - 16, by - 26 + leg_bob // 2),
                    (bx + 4,  by - 18)]
        pygame.draw.polygon(surf, base, tail_pts)
        # Body
        pygame.draw.rect(surf, base, (bx + 4,  by - 40, 26, 32), border_radius=7)
        pygame.draw.rect(surf, hi,   (bx + 8,  by - 38, 10, 12), border_radius=3)
        # Head
        pygame.draw.rect(surf, base, (bx + 14, by - 54, 24, 22), border_radius=6)
        # Snout
        pygame.draw.rect(surf, base, (bx + 30, by - 50, 10, 10), border_radius=3)
        # Eye
        pygame.draw.circle(surf, C['white'], (bx + 30, by - 47), 4)
        pygame.draw.circle(surf, C['black'], (bx + 31, by - 47), 2)
        pygame.draw.circle(surf, C['white'], (bx + 29, by - 49), 1)  # glint
        # Nostril
        pygame.draw.circle(surf, C['rock'],  (bx + 37, by - 44), 1)
        # Arm
        pygame.draw.rect(surf, base, (bx + 20, by - 32, 12, 6), border_radius=2)
        pygame.draw.rect(surf, hi,   (bx + 29, by - 32, 5,  5), border_radius=1)
        # Legs
        pygame.draw.rect(surf, base, (bx + 4,  by - 12 + leg_bob, 11, 14), border_radius=3)
        pygame.draw.rect(surf, base, (bx + 18, by - 12 - leg_bob, 11, 14), border_radius=3)
        # Feet
        pygame.draw.rect(surf, hi,   (bx + 2,  by - 1, 14, 4), border_radius=2)
        pygame.draw.rect(surf, hi,   (bx + 16, by - 1, 14, 4), border_radius=2)

    # Dead X eyes
    if dead:
        for dx, dy in [(bx + 28, by - 48), (bx + 35, by - 47)]:
            pygame.draw.line(surf, C['red'], (dx-3, dy-3), (dx+3, dy+3), 2)
            pygame.draw.line(surf, C['red'], (dx+3, dy-3), (dx-3, dy+3), 2)


# --- Replace the draw_rock function (around line 225) ---
def draw_rock(surf, x, y, w, h):
    """Draws a classic Dino-game Cactus instead of a rock."""
    ix, iy = int(x), int(y)
    green = (72, 155, 55)
    dark_green = (55, 130, 40)

    # Main Trunk
    pygame.draw.rect(surf, green, (ix + w//3, iy, w//3, h), border_radius=4)
    # Highlight on trunk
    pygame.draw.rect(surf, (100, 200, 80), (ix + w//3 + 2, iy + 4, 3, h - 8), border_radius=2)
    
    # Left Arm
    pygame.draw.rect(surf, green, (ix, iy + h//3, w//3, h//4), border_radius=3) # Horizontal part
    pygame.draw.rect(surf, green, (ix, iy + h//6, w//4, h//4), border_radius=3) # Vertical part
    
    # Right Arm
    pygame.draw.rect(surf, green, (ix + 2*w//3, iy + h//2, w//3, h//4), border_radius=3) # Horizontal
    pygame.draw.rect(surf, green, (ix + 3*w//4, iy + h//4, w//4, h//3), border_radius=3) # Vertical

    # Ground Shadow
    pygame.draw.ellipse(surf, (0, 0, 0, 40), (ix, iy + h - 5, w, 10))


# ─── Drawing: Pterodactyl ────────────────────────────────────────────────────
def draw_ptero(surf, x, y, w, h, ft):
    flap = math.sin(ft * 0.18) * 10
    cx   = int(x + w // 2)
    gy   = int(y + h // 2)

    # Wing shadows
    pygame.draw.polygon(surf, C['rock_sh'], [
        (cx, gy + 2), (int(x - 4), int(gy - 8 + flap + 2)), (int(x + 14), gy + 2)])
    pygame.draw.polygon(surf, C['rock_sh'], [
        (cx, gy + 2), (int(x + w + 4), int(gy - 8 + flap + 2)), (int(x + w - 14), gy + 2)])

    # Wings
    pygame.draw.polygon(surf, C['ptero'], [
        (cx, gy), (int(x - 4), int(gy - 10 + flap)), (int(x + 14), gy)])
    pygame.draw.polygon(surf, C['ptero'], [
        (cx, gy), (int(x + w + 4), int(gy - 10 + flap)), (int(x + w - 14), gy)])

    # Body
    pygame.draw.ellipse(surf, C['ptero'],    (cx - 12, gy - 8, 24, 14))
    pygame.draw.ellipse(surf, C['ptero_hi'], (cx - 8,  gy - 6, 10, 7))

    # Head + beak
    pygame.draw.ellipse(surf, C['ptero'],    (cx + 8, gy - 10, 14, 10))
    pygame.draw.line(surf, C['ptero'], (cx + 22, gy - 6), (cx + 32, gy - 4), 3)

    # Eye
    pygame.draw.circle(surf, C['white'], (cx + 14, gy - 7), 3)
    pygame.draw.circle(surf, C['black'], (cx + 15, gy - 7), 1)


# ─── Drawing: Egg ────────────────────────────────────────────────────────────
def draw_egg(surf, x, y, w, h, ft):
    ix, iy = int(x), int(y)
    bob  = int(math.sin(ft * 0.07) * 3)
    iy  -= bob
    # Shadow
    pygame.draw.ellipse(surf, (90, 64, 24), (ix + 2, iy + h - 4, w - 2, 6))
    # Body
    pygame.draw.ellipse(surf, C['egg'],    (ix,     iy,     w,     h))
    pygame.draw.ellipse(surf, C['egg_hi'], (ix + 4, iy + 3, w - 8, h // 2))
    # Glint
    pygame.draw.ellipse(surf, C['white'],  (ix + 5, iy + 4, 5, 3))
    # Spots
    pygame.draw.circle(surf, C['egg_hi'],  (ix + w // 2, iy + h - 6), 3)


# ─── Drawing: Avalanche ──────────────────────────────────────────────────────
def draw_avalanche(surf, aval_x, ft):
    ax = int(aval_x)
    if ax <= 0:
        return

    # Fill block
    pygame.draw.rect(surf, C['doom'], (0, 0, ax, H))

    # Jagged lava edge
    edge_pts = [(0, 0), (ax, 0)]
    for yy in range(0, H + 30, 15):
        jag = int(12 + 9 * math.sin(yy * 0.28 + ft * 0.12))
        edge_pts.append((ax + jag, yy))
    edge_pts += [(ax, H), (0, H)]
    pygame.draw.polygon(surf, (70, 18, 8), edge_pts)

    # Glow layers
    for i in range(10):
        alpha = max(0, 200 - i * 20)
        r     = max(0, 220 - i * 22)
        g     = max(0, 55  - i * 5)
        b     = max(0, 18  - i * 2)
        gx    = ax + i
        if gx >= 0:
            pygame.draw.line(surf, (r, g, b), (gx, 0), (gx, H), 2)

    # Dust particles
    rng = random.Random(ft // 8)
    for _ in range(6):
        px = ax + rng.randint(4, 24)
        py = rng.randint(0, H)
        pr = rng.randint(2, 6)
        pygame.draw.circle(surf, C['doom_glow'], (px, py), pr)


# ─── Drawing: HUD ────────────────────────────────────────────────────────────
def draw_star(surf, cx, cy, r, col):
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.42
        pts.append((cx + math.cos(ang) * rad, cy + math.sin(ang) * rad))
    pygame.draw.polygon(surf, col, pts)


def draw_hud(surf, fonts, st, my_pid):
    font, big, tiny = fonts
    players = st.get('players', [])
    wins    = st.get('wins', [0, 0])
    rnd     = st.get('round', 0)

    # Round indicator
    rnd_s = tiny.render(f'Round {rnd}  ·  Best of 3', True, C['white'])
    surf.blit(rnd_s, (W // 2 - rnd_s.get_width() // 2, 8))

    for i, p in enumerate(players):
        col   = DINO_COLS[i][0]
        label = 'P1' if i == 0 else 'P2'
        mine  = (i == my_pid)
        x     = 12 if i == 0 else W - 170

        # "YOU" indicator
        if mine:
            you = tiny.render('◄ YOU', True, C['gold'])
            surf.blit(you, (x + (148 if i == 1 else 90), 10))

        # Name + score
        score_s = font.render(f'{label}: {p["score"]:,}', True, col)
        surf.blit(score_s, (x, 10))

        # Win stars
        for w in range(wins[i]):
            draw_star(surf, x + w * 26 + 12, 46, 11, C['gold'])
        for w in range(wins[i], 2):
            draw_star(surf, x + w * 26 + 12, 46, 11, (60, 60, 60))

        # Status badge
        if not p['alive']:
            dead_s = tiny.render('✗  OUT', True, C['red'])
            surf.blit(dead_s, (x, 64))
        else:
            ok_s = tiny.render('● ALIVE', True, (100, 230, 100))
            surf.blit(ok_s, (x, 64))

    # Speed indicator (subtle)
    spd = st.get('speed', 5)
    spd_s = tiny.render(f'Speed {spd:.1f}×', True, (100, 100, 120))
    surf.blit(spd_s, (W // 2 - spd_s.get_width() // 2, H - 20))


# ─── Drawing: Splash Screen ──────────────────────────────────────────────────
def draw_splash(surf, fonts, my_pid, ft):
    font, big, tiny = fonts

    # Animated night-sky background
    surf.fill((18, 12, 32))
    rng = random.Random(42)
    for _ in range(80):
        sx = rng.randint(0, W)
        sy = rng.randint(0, H // 2)
        twinkle = int(160 + 80 * math.sin(ft * 0.05 + sx * 0.3))
        pygame.draw.circle(surf, (int(twinkle) % 256, int(twinkle) % 256, min(255, int(twinkle + 30))), (sx, sy), 1)
    # Ground strip
    pygame.draw.rect(surf, C['ground'], (0, H - 80, W, 80))
    pygame.draw.rect(surf, C['grass'],  (0, H - 80, W, 9))

    # Animated dinos on splash
    for pid in range(2):
        dx   = 220 + pid * 380
        step = ft + pid * 30
        draw_dino(surf, dx, H - 80, False, pid, dead=False, step=step)

    # Title with shadow
    title_sh = big.render('DINO  RUN', True, (40, 20, 80))
    title    = big.render('DINO  RUN', True, (80, 225, 110))
    tx = W // 2 - title.get_width() // 2
    surf.blit(title_sh, (tx + 4, 64))
    surf.blit(title,    (tx,     60))

    sub = font.render('2-Player Multiplayer', True, (160, 200, 255))
    surf.blit(sub, (W // 2 - sub.get_width() // 2, 138))

    # Controls box
    box_rect = pygame.Rect(W // 2 - 240, 175, 480, 135)
    box_surf = pygame.Surface((480, 135), pygame.SRCALPHA)
    box_surf.fill((255, 255, 255, 22))
    surf.blit(box_surf, box_rect.topleft)
    pygame.draw.rect(surf, (80, 80, 120), box_rect, 1, border_radius=6)

    ctrl_lines = [
        ('Player 1  :  W = Jump   ·   S = Duck',  DINO_COLS[0][0]),
        ('Player 2  :  ↑ = Jump   ·   ↓ = Duck',  DINO_COLS[1][0]),
        ('',                                        C['white']),
        ('Collect eggs for bonus points!',          C['egg_hi']),
        ('First to win 2 rounds wins the match.',   C['grey']),
    ]
    for i, (line, col) in enumerate(ctrl_lines):
        s = tiny.render(line, True, col)
        surf.blit(s, (W // 2 - s.get_width() // 2, 185 + i * 24))

    # Player badge
    if my_pid is not None:
        col  = DINO_COLS[my_pid][0]
        badge = font.render(f'You are  Player {my_pid + 1}', True, col)
        surf.blit(badge, (W // 2 - badge.get_width() // 2, 330))

    # Pulsing start prompt
    alpha = int(180 + 70 * math.sin(ft * 0.08))
    start_col = (alpha, alpha, int(alpha * 0.7))
    start_s = font.render('Press  SPACE  to start', True, start_col)
    surf.blit(start_s, (W // 2 - start_s.get_width() // 2, 375))

    # Waiting label
    if my_pid is None:
        wait_s = tiny.render('Connecting to server…', True, C['grey'])
        surf.blit(wait_s, (W // 2 - wait_s.get_width() // 2, 418))


# ─── Drawing: Overlay Panels ─────────────────────────────────────────────────
def _overlay(surf, alpha=160):
    ov = pygame.Surface((W, H), pygame.SRCALPHA)
    ov.fill((0, 0, 0, alpha))
    surf.blit(ov, (0, 0))


def draw_round_end(surf, fonts, st):
    font, big, tiny = fonts
    _overlay(surf, 145)

    players = st.get('players', [])
    wins    = st.get('wins', [0, 0])
    alive   = [p for p in players if p['alive']]

    if alive:
        wid = alive[0]['id']
        col = DINO_COLS[wid][0]
        msg = f'Player {wid + 1}  Wins the Round!'
    else:
        col = C['white']
        msg = "It's a Tie!"

    shadow = big.render(msg, True, (20, 20, 20))
    text   = big.render(msg, True, col)
    surf.blit(shadow, (W // 2 - text.get_width() // 2 + 3, H // 2 - 66))
    surf.blit(text,   (W // 2 - text.get_width() // 2,     H // 2 - 70))

    if len(players) == 2:
        sc = font.render(
            f'Score  —  P1: {players[0]["score"]:,}   ·   P2: {players[1]["score"]:,}',
            True, C['white'])
        surf.blit(sc, (W // 2 - sc.get_width() // 2, H // 2 + 5))

        w_txt = font.render(
            f'Wins  —  P1: {"★" * wins[0]}{"☆" * (2 - wins[0])}   '
            f'P2: {"★" * wins[1]}{"☆" * (2 - wins[1])}',
            True, C['gold'])
        surf.blit(w_txt, (W // 2 - w_txt.get_width() // 2, H // 2 + 45))

    nxt = tiny.render('Next round starting soon…', True, C['grey'])
    surf.blit(nxt, (W // 2 - nxt.get_width() // 2, H // 2 + 95))


def draw_game_over(surf, fonts, st):
    font, big, tiny = fonts
    _overlay(surf, 175)

    players = st.get('players', [])
    wins    = st.get('wins', [0, 0])
    winner  = 0 if wins[0] >= wins[1] else 1
    col     = DINO_COLS[winner][0]

    # Trophy area
    trophy = big.render('🏆', True, C['gold']) if False else None  # emoji unreliable

    t1_sh = big.render(f'Player {winner + 1}  Wins the Match!', True, (20, 20, 20))
    t1    = big.render(f'Player {winner + 1}  Wins the Match!', True, col)
    surf.blit(t1_sh, (W // 2 - t1.get_width() // 2 + 3, H // 2 - 86))
    surf.blit(t1,    (W // 2 - t1.get_width() // 2,     H // 2 - 90))

    if len(players) == 2:
        sc = font.render(
            f'Final Scores  —  P1: {players[0]["score"]:,}   ·   P2: {players[1]["score"]:,}',
            True, C['white'])
        surf.blit(sc, (W // 2 - sc.get_width() // 2, H // 2 + 5))

    w_txt = font.render(
        f'Match Result  —  P1: {wins[0]}  ·  P2: {wins[1]}',
        True, C['gold'])
    surf.blit(w_txt, (W // 2 - w_txt.get_width() // 2, H // 2 + 48))

    again = font.render('New match starting soon…  Get ready!', True, C['grey'])
    surf.blit(again, (W // 2 - again.get_width() // 2, H // 2 + 95))


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    global _player_id

    # ── Connect to server ────────────────────────────────────────────────────
    print(f'[client] Connecting to {SERVER_IP}:{PORT}…')
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((SERVER_IP, PORT))
    except ConnectionRefusedError:
        print(f'[client] Could not connect to {SERVER_IP}:{PORT} — is the server running?')
        sys.exit(1)

    print('[client] Connected!  Waiting for player assignment…')
    t = threading.Thread(target=net_thread, args=(sock,), daemon=True)
    t.start()

    # Wait up to 5 s for player-id assignment
    for _ in range(100):
        if _player_id is not None:
            break
        time.sleep(0.05)

    # ── Pygame ───────────────────────────────────────────────────────────────
    pygame.init()
    surf   = pygame.display.set_mode((W, H))
    title  = f'Dino Run — Player {_player_id + 1}' if _player_id is not None else 'Dino Run'
    pygame.display.set_caption(title)
    clock  = pygame.time.Clock()

    _build_sky()

    try:
        font = pygame.font.SysFont('Arial', 22, bold=True)
        big  = pygame.font.SysFont('Arial', 46, bold=True)
        tiny = pygame.font.SysFont('Arial', 17)
    except Exception:
        font = pygame.font.Font(None, 26)
        big  = pygame.font.Font(None, 56)
        tiny = pygame.font.Font(None, 20)
    fonts = (font, big, tiny)

    # ── Per-frame local state ─────────────────────────────────────────────────
    keys_down = set()
    scroll_bg = 0.0
    ft        = 0         # frame timer for animations

    running = True
    while running:
        clock.tick(FPS)
        ft += 1

        # ── Events ───────────────────────────────────────────────────────────
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            if ev.type == pygame.KEYDOWN:
                keys_down.add(ev.key)
            if ev.type == pygame.KEYUP:
                keys_down.discard(ev.key)

        # ── Determine inputs based on player id ──────────────────────────────
        pid = _player_id
        if pid == 0:
            j_key, d_key = pygame.K_w, pygame.K_s
        else:
            j_key, d_key = pygame.K_UP, pygame.K_DOWN

        jump  = j_key in keys_down
        duck  = d_key in keys_down
        start = pygame.K_SPACE in keys_down

        # ── Send input to server ──────────────────────────────────────────────
        msg = json.dumps({'j': jump, 'd': duck, 'start': start}).encode() + b'\n'
        try:
            sock.sendall(msg)
        except OSError:
            pass

        # ── Grab latest game state ────────────────────────────────────────────
        with _lock:
            st = _latest_st

        # ── Render ────────────────────────────────────────────────────────────
        if st is None:
            # Still connecting
            surf.fill((18, 12, 32))
            wait = font.render('Connecting to server…', True, C['grey'])
            surf.blit(wait, (W // 2 - wait.get_width() // 2, H // 2))
            pygame.display.flip()
            continue

        phase = st.get('phase', 'splash')

        if phase == 'splash':
            draw_splash(surf, fonts, pid, ft)
        else:
            spd = st.get('speed', INIT_SPEED)
            scroll_bg += spd

            draw_background(surf, scroll_bg, ft)

            # ── Eggs ──────────────────────────────────────────────────────────
            for e in st.get('eggs', []):
                taken = e.get('taken', [False, False])
                # Draw only if not taken by at least one player (both players share view)
                if not (taken[0] and taken[1]):
                    alpha = 0.5 if (taken[0] or taken[1]) else 1.0
                    draw_egg(surf, e['x'], e['y'], e['w'], e['h'], ft)

            # ── Obstacles ────────────────────────────────────────────────────
            for o in st.get('obstacles', []):
                if o['kind'] == 'rock':
                    draw_rock(surf, o['x'], o['y'], o['w'], o['h'])
                else:
                    draw_ptero(surf, o['x'], o['y'], o['w'], o['h'], ft)

            # ── Players ───────────────────────────────────────────────────────
            for p in st.get('players', []):
                draw_dino(surf, p['sx'], p['y'], p['ducking'],
                          p['id'], dead=not p['alive'], step=ft)
                # Player label above dino
                lbl = tiny.render(f'P{p["id"]+1}', True, DINO_COLS[p['id']][0])
                surf.blit(lbl, (int(p['sx']) + 10, int(p['y']) - 72))

            # ── Avalanche ────────────────────────────────────────────────────

            # ── HUD ───────────────────────────────────────────────────────────
            draw_hud(surf, fonts, st, pid)

            # ── Phase overlays ────────────────────────────────────────────────
            if phase == 'round_end':
                draw_round_end(surf, fonts, st)
            elif phase == 'game_over':
                draw_game_over(surf, fonts, st)

        pygame.display.flip()

    sock.close()
    pygame.quit()


if __name__ == '__main__':
    main()
