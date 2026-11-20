"""
===============================================================================
 3D PINBALL v5  -  Ursina (3D rendering) + Pymunk (2D rigid-body physics)
 FULLY DOCUMENTED EDITION
 v5 adds: music player (audio folder, mp3/ogg/wav, in-game menu), a pub/bar
 background, a picture puzzle on the back box, a subtle ball trail/shadow and
 extra playfield detail.
===============================================================================

CONTENTS OF THIS DOCSTRING
    1.  Overview
    2.  Installing and running, controls
    3.  Architecture: two engines kept in sync
    4.  Coordinates and units
    5.  Scene graph (what is a child of what)
    6.  Physics model, with the formulas used
    7.  Game rules and scoring
    8.  Game state and the state machine
    9.  The per-frame pipeline (order of operations inside update())
    10. Function index
    11. Data structure reference
    12. Known limitations / quirks (found while documenting)
    13. Tuning cheat-sheet
    14. Music system (audio folder, menu)
    15. Picture puzzle
    16. Bar scenery and extra graphics


-------------------------------------------------------------------------------
1. OVERVIEW
-------------------------------------------------------------------------------
A single-file, single-player 3D pinball game.  A steel ball is launched by a
spring plunger, bounces around a tilted playfield containing pop bumpers,
slingshots, two stages of flippers, three top rollover lanes and an orbit ring
with three bonus holes.  The player can also "nudge" (shove) the machine with
the space bar; nudging too often causes a TILT penalty.

All gameplay physics is computed in 2D by Pymunk, in units chosen so that they
map onto real pinball dimensions (1 unit = 1.35 mm).  Ursina only DRAWS the
result in 3D: every frame the 2D positions are copied onto 3D entities.  The
tilt of the playfield is modelled twice, consistently:
    * physically, as a reduced gravity acting along the playfield plane;
    * visually, by rotating the whole 3D table about its X axis.


-------------------------------------------------------------------------------
2. INSTALLING AND RUNNING, CONTROLS
-------------------------------------------------------------------------------
    pip install ursina pymunk
    python pinball_3d_v5.py

    Left arrow / A / Left Shift / Left Ctrl      left flippers  (lower + upper stage)
    Right arrow / D / Right Shift / Right Ctrl   right flippers (lower + upper stage)
    SPACE with the ball waiting in the plunger lane : hold to pull the plunger,
                                                      release to fire
    SPACE with the ball in play                  : NUDGE (shove the whole machine)
    UP / DOWN arrow                              : playfield angle +/- 0.5 deg
                                                   (clamped to 4.0 .. 9.0 deg)
    C                                            : cycle camera (angled, top, side, bar view)
    M                                            : open / close the MUSIC MENU (game pauses)
    N                                            : next music track
    R                                            : restart the game
    ESC                                          : quit (closes the menu when it is open)

    MUSIC MENU:  UP/DOWN select, ENTER play, 1-9 quick play, LEFT/RIGHT volume,
                 S stop, F5 rescan the folder, M or ESC close.


-------------------------------------------------------------------------------
3. ARCHITECTURE: TWO ENGINES KEPT IN SYNC
-------------------------------------------------------------------------------
    PYMUNK (module variable `space`)       URSINA (module variable `app`)
    ----------------------------------     ------------------------------------
    static bodies: walls, posts, bumper    Entities: boxes/spheres drawn with a
    rings, slingshot rails, ring segments  flat ("unlit") shader; colours are
    kinematic bodies: the 4 flippers       animated every frame to make LEDs.
    one dynamic body: the ball             The ONLY physics objects that move
                                           are the ball and the flippers; their
                                           transforms are copied to Entities
                                           in update().

Ursina automatically calls two functions defined at module level of the main
script:  update()  once per rendered frame, and  input(key)  once per key event.
`app.run()` at the very end starts that loop.

The module is organised top to bottom as:
    imports/engine start -> constants -> helpers -> static table geometry
    -> ball -> kickers -> flippers -> ring/holes -> TILT lettering -> UI
    -> game-state functions -> nudge/tilt functions -> input -> physics
    functions -> update() -> app.run()
Everything is built at import time (module level); nothing is created per frame
except colour/position updates, so there is no per-frame allocation of Entities.


-------------------------------------------------------------------------------
4. COORDINATES AND UNITS
-------------------------------------------------------------------------------
PHYSICS ("playfield") COORDINATES  -  used by every pymunk object and by all
the gameplay constants (wall endpoints, bumper centres, ...):
    x : to the player's right                 (-180 .. +180 across the table)
    y : up the slope, away from the player    (-300 plunger floor .. +350 arch top)
    1 physics unit = 1.35 mm  (BALL_R = 10 units = 13.5 mm = half of 27 mm)
    The main field is centred on x = CX = -17; the plunger lane is x 146..180.

URSINA WORLD COORDINATES (left-handed):
    x : right,  y : up,  z : away from the player.
    A playfield point (px, py) at height h above the board surface becomes the
    table-local point  (px*S, h, py*S)  with S = 0.1.  So z mirrors the physics
    y axis and world x mirrors the physics x axis.
    1 world unit = 10 physics units = 13.5 mm  (see WORLD_PER_M).

ANGLES:
    Pymunk angles are counter-clockwise (seen with x right / y up).  Ursina's
    positive rotation_y turns clockwise when seen from above.  That is why
    every visual rotation about the vertical axis is written
    rotation_y = -degrees(physics_angle).

COLOURS:
    color.hsv(h, s, v)  with h in degrees 0..360 and s, v in 0..1.


-------------------------------------------------------------------------------
5. SCENE GRAPH (what is a child of what)
-------------------------------------------------------------------------------
    scene (Ursina root)
      |-- wooden floor + the whole bar (back wall, shelves, counter, stools,
      |     tables, jukebox, dart board, pool table ...)  (parent=scene: never moves)
      `-- machine  (Entity)                 moves when the player NUDGES
            |-- legs, back box, equalizer, soft shadow        (via wk())
            `-- table (Entity)  position y = TABLE_Y,
                  rotation_x = -tilt degrees (far end raised)
                  `-- EVERYTHING on/in the playfield           (via mk())
                      board, rails, walls, LEDs, bumpers, flippers' pivots,
                      ball + dots, shadow, trail, plunger, sparks, TILT pixels

Because the ball, sparks, trail, etc. are children of `table`, they are
positioned in table-local coordinates and automatically inherit the table tilt
and the cabinet's nudge motion.  Screen-space UI uses camera.ui.

Rendering: every playfield Entity uses Ursina's `unlit_shader` (flat colour, no
lighting).  Depth/bevel is faked by layering: a dark body cube with a thin
bright "cap" cube on top.  If `unlit_shader` cannot be imported the code falls
back to Ursina's default shader.  Approximate heights above the board surface
(y = 0): inserts 0.02-0.16, wall body 0-2.2, wall cap 2.2-2.6, LED bulbs at
2.85, ball centre 1.0 (radius 1.0).


-------------------------------------------------------------------------------
6. PHYSICS MODEL, WITH THE FORMULAS USED
-------------------------------------------------------------------------------
6.1 Gravity along the tilted playfield (apply_tilt, accel_units)
    A frictionless sliding mass accelerates down a plane at g*sin(theta).  A
    ROLLING solid sphere (I = 2/5 m r^2) accelerates at
        a = g sin(theta) / (1 + I/(m r^2)) = (5/7) g sin(theta)
    ROLL_FACTOR = 1/(1+0.4) = 5/7.  At theta = 6.5 deg: a = 0.793 m/s^2
    = 587.4 physics units/s^2.  Pymunk simulates a disc SLIDING on the plane
    (there is no friction between ball and playfield in 2D), so the 5/7 factor
    on gravity is how rolling inertia is emulated.  The pymunk body is still
    given the sphere moment of inertia 0.4*m*r^2, which only matters for
    friction torques at wall contacts.

6.2 Materials (MAT)
    Pymunk multiplies the elasticity values of the two touching shapes, and
    likewise the friction values.  Ball: elasticity 0.85, friction 0.5.
        steel   (0.75, 0.50) -> ball-on-steel  e = 0.64, mu = 0.25
        wood    (0.70, 0.50) -> e = 0.60, mu = 0.25
        rubber  (0.60, 1.60) -> e = 0.51, mu = 0.80
        flipper (0.55, 1.40) -> e = 0.47, mu = 0.70
        bumper  (0.80, 0.20) -> e = 0.68, mu = 0.10

6.3 Rolling resistance (pre_step)
    a_rr = C_ROLL * g * cos(theta) = 0.0015*9.80665*cos(6.5 deg)
         = 0.0146 m/s^2 = 10.8 units/s^2, subtracted from the ball's speed in
    every sub-step (never below zero), in the direction opposite to motion.

6.4 Time stepping (update)
    dt = min(frame time, 1/30 s).  The frame is split into
    SUB = max(12, int(dt*960)) sub-steps of sd = dt/SUB (about 1.04 ms at 60 fps).
    At the speed limit of 6 m/s (4444 units/s) the ball moves 4.6 units per
    sub-step, much less than its radius (10), so it cannot tunnel through the
    thinnest walls.  space.iterations = 20 and collision_slop = 0.05 further
    stabilise contacts.

6.5 Flippers (make_flipper, drive_flipper)
    Kinematic bodies (they are driven, not pushed).  A left flipper has its
    blade along local +x, rests at -28 deg (blade pointing down-right) and
    swings to +32 deg; a right flipper has the blade along local -x, rests at
    +28 deg and swings to -32 deg: a 60 deg swing.  Every sub-step the angular
    velocity is set to +/-speed toward the target angle until the remaining
    angle is smaller than speed*sd, then the angle snaps to the target and the
    angular velocity is zeroed.  Speed up: 32 rad/s (solenoid), down: 14 rad/s
    (return spring).  Tip speed = omega * length = 32*62*1.35 mm = 2.68 m/s
    (lower stage), 2.16 m/s (upper stage).  Because the body is kinematic
    with a real angular velocity, pymunk gives the ball the proper impulse.

6.6 Spring plunger (plunger_ball_speed)
    Pull distance d = fraction * 70 mm.  Spring energy 1/2 k d^2 becomes
    plunger kinetic energy 1/2 M v_p^2, so v_p = d*sqrt(k/M)  (k = 250 N/m,
    M = 0.120 kg).  An elastic collision with the ball (mass m = 0.0805 kg,
    at rest) gives  v_ball = 2M/(M+m) * v_p.  Full pull: 3.82 m/s.  The ball
    needs about 1.07 m/s to climb to the arch, i.e. roughly 28-30 % pull.

6.7 Kickers (post_step)
    Pop bumper: contact is detected analytically (centre distance < bumper
    radius + ball radius + 3).  The ball is thrown radially outward at
    max(1.8 m/s, 0.9 * current speed).  Slingshot: when the ball is within
    BALL_R+8 of the rail, velocity along the rail's "front" normal is raised
    to at least 1.5 m/s.  Per-device cool-downs (0.12 s / 0.15 s) prevent
    re-triggering every sub-step.

6.8 Hole "dish" and capture (pre_step, post_step)
    Within 27 units of a hole centre the ball gets an extra acceleration toward
    the centre of 2*a_roll*(1 - d/27).  If the ball is within 10 units of the
    centre and slower than 0.9 m/s it is captured: it is pinned to the hole for
    1.3 s, then ejected at 1.1 m/s through the ring opening (+/-25 deg of the
    gap centre).  For 1.2 s afterwards holes ignore the ball.

6.9 Nudge: cabinet as a damped spring (machine_step, nudge, pre_step)
    The cabinet's displacement s (metres, along the shove direction) obeys
        s'' = -omega^2 s - 2 zeta omega s'      omega = 2 pi 5.5 Hz = 34.56 rad/s,
                                                zeta = 0.22
    integrated with semi-implicit Euler at every physics sub-step.  A shove adds
    v0 = 0.35 m/s (+/-10 %) to s' instantly.  Peak displacement is about 7.4 mm,
    peak cabinet acceleration about 9.8 m/s^2, settling in about 0.45 s.
    In the cabinet's (accelerating) frame the ball feels an inertial force:
      * at the shove  : relative velocity change  -kappa*v0  along the shove
                        direction (kappa = NUDGE_COUPLING = 0.7 -> 0.245 m/s),
                        i.e. the ball "lags" toward the player;
      * every sub-step: velocity change  -kappa * a_cabinet(t) * sd  along the
                        shove direction, which is a decaying oscillation.
    The shove direction is (sin phi, cos phi), phi uniform in +/-0.15 rad.
    On screen the cabinet moves  s * VISUAL_GAIN(3) * WORLD_PER_M  world units.

6.10 Tilt meter
    +1.0 per accepted nudge; decays by 0.6 per second.  >= 2.0 shows "DANGER!";
    >= 3.0 triggers TILT (see 7.4).  Pushing about every 0.5 s tilts on the 4th
    shove.


-------------------------------------------------------------------------------
7. GAME RULES AND SCORING
-------------------------------------------------------------------------------
7.1 Balls
    3 balls per game (st.balls).  Draining (ball y < -312) costs one ball.  An
    Extra Ball adds one.  When st.balls reaches 0 the phase becomes 'over'.

7.2 Scoring events
    Pop bumper hit .............. +100 score, +100 bonus
    Slingshot hit ............... +25 score,  +25 bonus
    Top rollover lane (each) .... +500 score  (each lane lights once)
      all three lit ............. bonus multiplier +1 (max x5), lanes reset
    Entering the orbit ring ..... +150 score
    Hole, first time ............ +1000 score, +500 bonus
      all three holes lit ....... EXTRA BALL, +5000, holes reset
    Hole already lit ............ +250 score
    End-of-ball bonus ........... bonus * multiplier added at drain (zero when
                                  tilted); bonus, multiplier and lit lanes reset.

7.3 Plunger lane and one-way gate
    The lane's inner wall ends at y = 150, leaving a wide opening into the
    arch.  A static "gate" segment is added to the physics space once the ball
    is in the field (x < 132 and y > 160) so it cannot fall back into the lane,
    and removed again when the next ball is spawned.

7.4 TILT
    On tilt: flippers drop and stay dead, pop bumpers and slingshots stop kicking
    and scoring, rollover lanes / ring / holes stop scoring or capturing,
    nudging is disabled, the end-of-ball bonus is forfeited, the pixel letters
    "TILT" appear on the board, "TILT" flashes on screen, and every light
    (rail LEDs, neon caps, inserts, stars, bumper LEDs, ring, equalizer) strobes
    in random-looking colours.  The tilt ends only when the player launches the
    next ball with the plunger (or restarts with R).


-------------------------------------------------------------------------------
8. GAME STATE AND THE STATE MACHINE
-------------------------------------------------------------------------------
st.phase :
    'plunger' : ball sits in the lane; SPACE charges the plunger.
    'play'    : ball in play (set when the plunger fires).
    'over'    : no balls left; ball hidden and parked off-table.
Transitions:
    reset_game()/respawn_ball() -> 'plunger'
    plunger release with ball in lane -> 'play'
    drain() with balls left -> respawn_ball() -> 'plunger'
    drain() with no balls left -> 'over'
Independent flags: st.tilted (tilt active), st.captured (index of the hole that
currently holds the ball, or None), st.gate_on (gate segment in the space).
A weak plunge may drop the ball back into the lane while st.phase is still
'play'; the lane test (x > 148 and y < -150) then lets SPACE re-charge it.


-------------------------------------------------------------------------------
9. THE PER-FRAME PIPELINE (order of operations inside update())
-------------------------------------------------------------------------------
    1. dt = min(time.dt, 1/30); advance the clock st.t.
    2. Read flipper keys (incl. Ctrl); gate by st.tilted; update cabinet buttons.
    3. Plunger: charge while SPACE held in the lane; on release fire the ball
       (and clear any tilt).
    4. Sub-step loop, SUB times:
           drive_flipper() for every flipper -> machine_step() -> pre_step()
           -> space.step(sd) -> post_step()        (pre/post skipped when 'over')
    5. Decay tilt meter; move the whole machine (nudge visual).
    6. If 'over', park the ball far away.
    7. Read ball position/velocity; HUD speed; stuck-ball rescue.
    8. Visual sync: ball (+roll dots, shadow, trail), flipper rotations,
       plunger, then all LED / neon / insert / star / lane / equalizer /
       bumper / sling / ring / hole colours, then the spark particles.
    9. UI text (score, balls, physics read-out), message timer, nudge meter,
       flashing TILT text and pixels.
drain()/respawn_ball() can be called from post_step() in the middle of the
sub-step loop; the remaining sub-steps then simulate the new ball.


-------------------------------------------------------------------------------
10. FUNCTION INDEX
-------------------------------------------------------------------------------
Unit helpers ........ ms_to_units, units_to_ms, accel_units
Alpha helper ........ soft
Music ............... find_audio_dir, MusicPlayer (scan, play, stop, set_volume,
                      next, tick, hud_text), music_autostart, show_menu,
                      draw_menu, menu_key
Puzzle .............. _mix, pic_sunset, pic_beer, pic_planet, make_picture_texture,
                      puzzle_set_picture, puzzle_reset, add_puzzle, puzzle_update
Bar scenery ......... build_bar, add_arrow
Table/tilt .......... apply_tilt
Scene helpers ....... mk, wk, seg_visual, dist_pt_seg
Table building ...... add_led, add_wall, add_post
Plunger physics ..... plunger_ball_speed
Effects ............. spawn_sparks
Flippers ............ make_flipper, drive_flipper
UI / messages ....... show_msg
Game flow ........... set_gate, respawn_ball, reset_game, drain, set_camera,
                      input
Nudge / tilt ........ C, trigger_tilt, clear_tilt, machine_step, nudge
Physics loop ........ pre_step, post_step, roll_ball
Main loop ........... update
(class State is a plain attribute container; `st` is its single instance.)


-------------------------------------------------------------------------------
11. DATA STRUCTURE REFERENCE
-------------------------------------------------------------------------------
st  (State instance) fields
    tilt        playfield angle in degrees (UP/DOWN keys), default 6.5
    t           game clock in seconds (sum of clamped dt), drives animations
    score       integer score
    balls       balls remaining including the one in play
    phase       'plunger' | 'play' | 'over'
    charge      plunger pull fraction 0..1
    space_prev  was SPACE held on the previous frame (to detect release)
    gate_on     True while the one-way gate segment is in the physics space
    hole_filled list of 3 bools: holes lit toward the extra ball
    lane_lit    list of 3 bools: top rollover lanes lit
    mult        end-of-ball bonus multiplier 1..5
    bonus       accumulated end-of-ball bonus points
    captured    index (0..2) of the hole holding the ball, else None
    capture_timer  seconds left before the held ball is ejected
    hole_cool   seconds during which holes ignore the ball (after ejection)
    ring_inside True while the ball centre is inside the orbit ring
    ring_flash  seconds of ring celebration flashing left
    stuck_t     seconds the ball has been nearly motionless (rescue at 3 s)
    msg_t       seconds left before msg_text is cleared
    cam_mode    0 angled, 1 top-down, 2 side
    hist        recent ball positions (x, y) for the glowing trail
    speed_ms    ball speed in m/s for the HUD
    hud_t       accumulator throttling HUD text refresh to 10 Hz
    btn_l, btn_r  UNUSED (leftover); the button colours come from key state
    m_s, m_v, m_acc  cabinet displacement (m), velocity (m/s), acceleration (m/s^2)
    m_dir       unit shove direction (x, y) in playfield coordinates
    meter       tilt meter value
    tilted      True while TILT is active
    menu_open   True while the music menu is shown (game logic is frozen)
    puz_idx     index of the current puzzle picture (0..2)
    puz_pts     bonus points collected toward the next tile
    puz_open    tiles already opened in the current picture
    puz_order   shuffled order in which the 24 tiles will open
    puz_done_t  seconds the finished picture stays on show (0 = not finished)
    puz_flash   seconds of frame celebration flashing left

Lists of animated visuals (filled while building the table)
    leds   [(entity, kind, phase)]   kind 'cycle' (rainbow pulse) or 'chase'
    neon   [(entity, phase)]         rail-cap strips cycling in hue
    inserts[(entity, phase 0..1)]    14 flowing floor lights
    stars  [([4 entities], x)]       5 star inserts
    eq_bars[(entity, index)]         17 equalizer bars on the back box
    lane_vis [entity] x3             lamps of the top rollover lanes
    ring_vis [entity]                20 neon caps of the orbit ring
    trail  [entity] x TRAIL_N        glowing trail spheres
    tilt_px[(entity, phase)] x30     pixels of the letters T I L T

bumpers[i] dict : x, y, r (20), hue, cap, skirt, leds (12 entities), flash (s), cool (s)
slings[i]  dict : a, b (rail end points), front (unit normal), vis (cap entity),
                  flash (s), cool (s)
flippers[i] dict: body (pymunk kinematic body), pivot (Entity), side 'L'/'R',
                  active (bool), rest (rad), up (rad)
holes[i]   dict : x, y, rim (Entity), glow (Entity)
sparks[i]  dict : e (Entity), vx, vy, vz (world units/s), life, mx (initial life)


-------------------------------------------------------------------------------
12. KNOWN LIMITATIONS / QUIRKS  (found while documenting)
-------------------------------------------------------------------------------
 1. (Fixed in v5.)  In v4 the flashing "TILT" text hid "GAME OVER" when the last
    ball was lost while tilted; the tilt text is now only drawn while the game
    is not over (the TILT pixels on the board and the strobing lights keep
    flashing until R is pressed).
 2. st.btn_l / st.btn_r are never used.
 3. Rolling is approximated (see 6.1): ball spin is not coupled to the
    playfield, only gravity is reduced by 5/7.
 4. The ball is a 2D disc: it cannot leave the plane (no airborne shots).
 5. Slingshot kicks do not test which side of the rail the ball is on; the
    geometry keeps the ball on the field side.
 6. Lane tests use hard-coded numbers (x > 148, y < -150) that must match the
    lane geometry if it is edited.
 7. Changing the playfield angle with UP/DOWN affects gravity immediately.
 8. A ball already held in a hole when a tilt happens is still released
    normally after 1.3 s.


-------------------------------------------------------------------------------
13. TUNING CHEAT-SHEET
-------------------------------------------------------------------------------
    st.tilt (initial)        playfield angle        (6.5 deg, real: 6-7)
    FLIP_UP_SPEED/DOWN_SPEED flipper strength       (32 / 14 rad/s)
    BUMPER_KICK, SLING_KICK  kicker strength        (1.8 / 1.5 m/s)
    PLUNGER_K, PLUNGER_M     plunger strength       (250 N/m, 0.12 kg)
    MAT[...]                 bounciness / grip
    NUDGE_V0, CAB_FREQ, CAB_ZETA, NUDGE_COUPLING     nudge feel
    METER_DECAY, METER_DANGER, METER_TILT            tilt sensitivity
    VISUAL_GAIN              how far the cabinet visibly moves
    PUZ_TILE_COST            bonus points per puzzle tile (300)
    BAR_SCENERY              False = do not build the pub (faster on slow PCs)


-------------------------------------------------------------------------------
14. MUSIC SYSTEM (audio folder, menu)
-------------------------------------------------------------------------------
Folder: an `audio` directory in the game root, i.e. next to this script
(.\audio on Windows).  find_audio_dir() prefers <script folder>/audio, then
<current directory>/audio, and creates the first one if neither exists.
Supported files: .mp3, .ogg, .wav (sorted case-insensitively).  The folder is
scanned at start-up, whenever the menu is opened and on F5.

MusicPlayer tries two back-ends in this order:
  1. Panda3D / OpenAL (base.loader.loadSfx).  The whole track is decoded into
     memory and looped with setLoop(True).  A file counts as loaded when its
     length is greater than 0.5 s.  MP3 needs Panda3D's FFmpeg plug-in, which is
     part of the standard panda3d wheels; if it is missing the load yields a
     zero-length sound and the player moves on to
  2. pygame.mixer.music (only if `pip install pygame` was done), which decodes
     MP3 itself and loops with play(-1).
If both fail, MusicPlayer.error explains it and the menu shows the message.
Looping is guaranteed twice: by the back-end loop flag and by tick(), which
every 0.5 s restarts a track that has stopped although it should be playing.

The first track starts automatically at start-up at 60 % volume.  Press M for
the menu: the game is paused (update() only draws the menu and keeps the
music ticking).  The selected track loops until you choose another one or
press S.  N skips to the next track at any time.  The bottom-right text shows
the current track.


-------------------------------------------------------------------------------
15. PICTURE PUZZLE
-------------------------------------------------------------------------------
The back box shows a picture (112 x 36 pixel art generated by code, no image
files) covered by 8 x 3 = 24 tiles.  Bonus points collected during play open
the tiles one by one in a random order: every PUZ_TILE_COST (300) points a
tile flips open.  Points count from pop bumpers (100), slingshots (25), top
lanes (500), ring entry (150), holes (500) and the multiplier part of the
end-of-ball bonus.  When all 24 tiles are open the picture is complete:
+10000 points, a message with the picture's title, a flashing frame; after 6 s
the next of the 3 pictures (Neon Sunset, A Cold One, Chrome Planet) is covered
again.  A new game restarts at picture 1.  The HUD shows PUZZLE n/24.

Implementation: each picture is a function (x, y) -> (r, g, b) evaluated into
a Panda3D PNMImage -> Texture (nearest-neighbour magnification for crisp
pixels) shown on one quad.  The tiles are cover quads in front of it.  If
Panda3D texture creation fails the quad falls back to a solid colour.


-------------------------------------------------------------------------------
16. BAR SCENERY AND EXTRA GRAPHICS
-------------------------------------------------------------------------------
build_bar() creates the pub behind and around the machine: brick back wall and
side walls with a wainscot, a mirror with three bottle shelves, a bar counter
with beer taps, pint glasses and a cash register, five stools, a neon "BAR"
sign, a dart board, framed posters, a wall clock, pendant lamps, a jukebox,
two rugs, four round tables with stools and a pool table with a lamp.  The
default camera was lowered (view 0) so that the wall is visible.  Neon items
join the `neon` registry, so they strobe during a TILT as well; candles and
lamps are in `warm`.

Extra playfield details: chrome rivets on the side rails, chevron arrows that
chase toward the top lanes and along the lower guides (`arrows`), faint glass
reflections over the playfield, a picture-frame around the puzzle.

Ball visuals: a two-layer soft shadow under the ball and a very faint, short
trail made of flat translucent discs that fades in only above 0.6 m/s.
"""
import math
import os
import random

# Star-import brings in Ursina, Entity, Text, Vec2, Vec3, camera, window,
# color, held_keys, time, scene, application, ...
from ursina import *
import pymunk

# Low-level Panda3D classes used for audio, picture textures and transparency.
# If the import fails, the related features degrade gracefully (the
# MusicPlayer falls back to pygame, the puzzle picture to a solid colour,
# soft() becomes a no-op).
try:
    from panda3d.core import Filename, PNMImage, SamplerState, TransparencyAttrib, AudioSound
    from panda3d.core import Texture as PandaTexture
except Exception:
    Filename = PNMImage = SamplerState = TransparencyAttrib = AudioSound = PandaTexture = None

# ---- optional shader -------------------------------------------------------
# unlit_shader draws flat colours (no lighting).  It is used for every
# playfield object so the neon colours look the same regardless of lights.
# If the import fails (very old/unusual Ursina builds) fall back to None and
# let Ursina use its default shader.
try:
    from ursina.shaders import unlit_shader
except Exception:
    unlit_shader = None

# ---- engine start and window setup ------------------------------------------
# Creating Ursina() opens the window; it must happen before any Entity exists.
app = Ursina()
window.title = "3D Pinball in Python"
window.borderless = False
# Very dark indigo background colour (h=258 deg, s=0.75, v=0.04).
window.color = color.hsv(258, 0.75, 0.04)
# Wide 72 degree horizontal field of view lets the whole table + back box fit.
camera.fov = 72

# S converts physics units to Ursina world units: 1 physics unit = 0.1 world units.
S = 0.1            # 1 physics unit = 0.1 world units
# Height of the table's centre above the floor (world units).  The table is
# rotated about this centre by the tilt angle.
TABLE_Y = 14       # height of table centre above the floor

# --------------------------------------------------------------------------
# Real-world constants
# --------------------------------------------------------------------------
G_EARTH = 9.80665                 # m/s^2   standard gravity
BALL_R = 10                       # physics units (ball radius)
BALL_DIAMETER_MM = 27.0           # 1-1/16 inch   real pinball ball diameter
BALL_MASS_KG = 0.0805             # real steel pinball mass (used by the plunger)
# Physical size of one physics unit: the ball is 2*BALL_R = 20 units = 27 mm.
UNIT_MM = BALL_DIAMETER_MM / (2 * BALL_R)      # 1.35 mm per unit
# Gravity reduction for a rolling solid sphere: 1 / (1 + I/(m r^2)), I = 2/5 m r^2.
ROLL_FACTOR = 1.0 / (1.0 + 0.4)   # solid sphere, rolling without slipping
# Rolling resistance coefficient (dimensionless): decel = C_ROLL * g * cos(theta).
C_ROLL = 0.0015                   # rolling resistance coefficient (steel on lacquer)


def ms_to_units(v):
    """Convert a speed or acceleration from metres (per second[^2]) to physics units.

    Parameters:
        v : value in m/s (or m/s^2).
    Returns:
        the same quantity in physics units/s (or units/s^2):  v * 1000 / UNIT_MM.
    Used everywhere a real-world number (plunger speed, kick speeds, gravity,
    cabinet acceleration, speed limit) must be injected into the simulation.
    """
    return v * 1000.0 / UNIT_MM


def units_to_ms(u):
    """Inverse of ms_to_units: physics units/s -> m/s.

    Parameters:
        u : speed in physics units per second.
    Returns:
        speed in m/s (used only for the on-screen speed read-out).
    """
    return u * UNIT_MM / 1000.0


def accel_units(tilt_deg):
    """Acceleration of a ROLLING ball down the playfield, in units/s^2.

    Implements a = (5/7) * g * sin(theta)  (see module docstring 6.1) and
    converts it to physics units.  At 6.5 degrees this is 0.793 m/s^2, i.e.
    about 587.4 units/s^2.

    Parameters:
        tilt_deg : playfield inclination in degrees.
    Returns:
        magnitude of the effective gravity in units/s^2 (positive number).
    Used by apply_tilt() (space.gravity) and by the hole "dish" force in pre_step().
    """
    return ms_to_units(G_EARTH * math.sin(math.radians(tilt_deg)) * ROLL_FACTOR)


# Material table  (restitution, friction).  Pymunk multiplies the pair, so the
# ball (0.85 / 0.5) times these gives the effective ball-on-material values.
# Keys are passed to add_wall()/add_post() etc. and looked up as
#     shape.elasticity, shape.friction = MAT[name]
MAT = {
    'steel':   (0.75, 0.50),    # guide rails           -> e = 0.64, mu = 0.25
    'wood':    (0.70, 0.50),    # arch / side walls     -> e = 0.60
    'rubber':  (0.60, 1.60),    # posts, slingshots     -> e = 0.51, mu = 0.80
    'flipper': (0.55, 1.40),    # flipper rubber        -> e = 0.47, mu = 0.70
    'bumper':  (0.80, 0.20),    # pop bumper ring
}

# ---- the physics world -------------------------------------------------------
# One pymunk Space holds every collision object.  Gravity is set later by
# apply_tilt().  `iterations` = constraint/contact solver passes per step
# (default 10); 20 gives stiffer, more accurate contacts for the fast ball.
# `collision_slop` = allowed overlap before pymunk pushes shapes apart
# (default 0.1 units); 0.05 units (0.07 mm) keeps the ball from "sinking".
space = pymunk.Space()
space.iterations = 20
space.collision_slop = 0.05

# --------------------------------------------------------------------------
# Scene root: the TILTED table.  Everything on the playfield is a child.
# --------------------------------------------------------------------------
class State:
    """Plain attribute container for all mutable game state.

    No methods.  A single instance `st` is created below and attributes are
    assigned one by one so each can carry a comment.  Using one object avoids
    scattering `global` statements through the functions.  See module
    docstring section 11 for the meaning of every field.
    """
    pass


st = State()
# --- playfield / clock ---
st.tilt = 6.5              # playfield angle in degrees (changed by UP/DOWN keys)
st.t = 0.0                 # game clock (seconds) for animations
# --- scoring / balls ---
st.score = 0
st.balls = 3               # balls remaining, including the one in play
# --- ball lifecycle ---
st.phase = 'plunger'       # 'plunger' | 'play' | 'over'
st.charge = 0.0            # plunger pull fraction 0..1
st.space_prev = False      # previous-frame state of the SPACE key
st.gate_on = False         # is the one-way gate in the physics space?
# --- bonus features ---
st.hole_filled = [False, False, False]
st.lane_lit = [False, False, False]
st.mult = 1                # bonus multiplier
st.bonus = 0               # end-of-ball bonus accumulator
st.captured = None         # index of hole holding the ball, else None
st.capture_timer = 0.0
st.hole_cool = 0.0
st.ring_inside = False
st.ring_flash = 0.0
# --- housekeeping ---
st.stuck_t = 0.0
st.msg_t = 0.0
st.cam_mode = 0
st.hist = []
st.speed_ms = 0.0
st.hud_t = 0.0
st.btn_l = False           # unused leftovers
st.btn_r = False
# --- nudge / tilt ---
st.m_s = 0.0               # cabinet displacement (m) along the shove direction
st.m_v = 0.0               # cabinet velocity (m/s)
st.m_acc = 0.0             # cabinet acceleration (m/s^2)
st.m_dir = (0.0, 1.0)      # shove direction in playfield coordinates (away from player)
st.meter = 0.0             # tilt meter
st.tilted = False
# --- music menu ---
st.menu_open = False       # True while the music menu is shown (game frozen)
# --- picture puzzle ---
st.puz_idx = 0             # current picture (0..2)
st.puz_pts = 0             # bonus points collected toward the next tile
st.puz_open = 0            # tiles opened so far
st.puz_order = []          # shuffled tile order
st.puz_done_t = 0.0        # seconds the completed picture stays visible
st.puz_flash = 0.0         # seconds of frame flashing left

# `machine` is the root of the whole cabinet; nudging translates it.
machine = Entity()      # whole cabinet: moves when the player nudges
# `table` is the tilted playfield frame.  rotation_x is NEGATIVE so the far end
# (positive z, top of the playfield) is raised and the near end (flippers) is
# lowered, like a real machine.
table = Entity(parent=machine, position=(0, TABLE_Y, 0), rotation_x=-st.tilt)


def apply_tilt():
    """Apply the current st.tilt to both the 3D model and the physics.

    * Visual : table.rotation_x = -tilt (far end up).
    * Physics: space.gravity = (0, -a) where a = accel_units(tilt).  Physics y
      points up the slope, so gravity pulls the ball toward -y (the flippers).

    Called once at start-up and whenever the player presses UP/DOWN.
    """
    table.rotation_x = -st.tilt
    space.gravity = (0, -accel_units(st.tilt))


apply_tilt()


def mk(**kw):
    """Create a PLAYFIELD entity (child of the tilted `table`) with a flat shader.

    Parameters:
        **kw : any Entity keyword arguments (model, color, scale, position,
               rotation_y, parent, ...).  If `parent` is not supplied it
               defaults to `table`.
    Returns:
        the new Entity.
    Side effect: if unlit_shader was importable it is forced as the shader.
    Almost every visible object in the game is created through this helper.
    """
    kw.setdefault('parent', table)
    if unlit_shader is not None:
        kw['shader'] = unlit_shader
    return Entity(**kw)


def wk(**kw):
    """Create a WORLD-side entity: default parent is `machine` (moves on nudge).

    Used for cabinet parts (legs, back box, equalizer bars, soft shadow).  Pass
    parent=scene explicitly for things that must NOT move (the floor and grid).
    Implemented by setting the default parent to `machine` and delegating to mk()
    (mk's own default does not override a parent that is already present).

    Parameters / Returns: same as mk().
    """
    kw.setdefault('parent', machine)
    return mk(**kw)


def soft(e):
    """Enable alpha blending on an entity so semi-transparent colours work.

    Colours created with a fourth (alpha) value, e.g. color.hsv(210, .3, .9, .2),
    are only drawn translucent if the node has a transparency attribute.  This
    calls NodePath.setTransparency(M_alpha) and ignores any failure (then the
    colour is simply drawn opaque).  Used for the ball shadow, the ball trail and
    the glass reflections.

    Parameters:
        e : Entity.
    Returns:
        the same entity (so it can wrap a constructor call).
    """
    if TransparencyAttrib is not None:
        try:
            e.setTransparency(TransparencyAttrib.M_alpha)
        except Exception:
            pass
    return e


def seg_visual(a, b, thickness, height, col, y0=0.0, extra=0.0):
    """Draw a box lying along the playfield segment a -> b.  Returns the Entity.

    The box is a unit cube scaled to (length, height, thickness) and rotated
    about the vertical axis so its long side follows the segment.  Used for
    walls, wall caps, slingshot rails, ring pieces and the gate.

    Parameters:
        a, b      : (x, y) segment end points in PHYSICS units.
        thickness : box width in physics units (perpendicular to the segment).
        height    : box height in WORLD units.
        col       : Ursina colour.
        y0        : height of the box's bottom above the board (world units).
        extra     : extra length (physics units) added to the box so that
                    consecutive pieces overlap and hide the joints.
    The centre is the midpoint of a-b; rotation_y = -degrees(atan2(dy, dx))
    (see module docstring 4 for the sign convention).
    """
    ax, ay = a
    bx, by = b
    length = math.hypot(bx - ax, by - ay) + extra
    ang = math.degrees(math.atan2(by - ay, bx - ax))
    return mk(model='cube', color=col,
              position=((ax + bx) / 2 * S, y0 + height / 2, (ay + by) / 2 * S),
              scale=(length * S, height, thickness * S), rotation_y=-ang)


def dist_pt_seg(p, a, b):
    """Shortest distance from point p to the line SEGMENT a-b (all in physics units).

    Projects p onto the infinite line, clamps the projection parameter t to
    [0, 1] so the nearest point stays on the segment, and returns the distance
    to that point.  A zero-length segment is treated as a point (t = 0).
    Used to detect the ball touching a slingshot rail.

    Parameters:
        p    : (x, y) point.
        a, b : segment end points.
    Returns:
        float distance.
    """
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------
WALL_BODY = color.hsv(238, 0.75, 0.40)     # dark blue body of rails
WOOD = color.hsv(18, 0.62, 0.40)           # cabinet wood
WOOD_TOP = color.hsv(32, 0.50, 0.78)       # lighter wood highlight
CHROME = color.hsv(210, 0.12, 0.85)        # legs, bars, plunger cap

# Registries of animated lights; update() recolours them every frame.
leds = []          # glowing bulbs (entity, kind, phase)
neon = []          # rail cap strips (entity, phase)
# X coordinate of the centre line of the main playfield.  The plunger lane
# (x 146..180) is on the right, so the main field (x -180..146) is centred at -17.
CX = -17           # centre line of the main field (plunger lane is on the right)


def add_led(x, y, h=0.45, size=0.5, kind='cycle', phase=0.0):
    """Create one glowing bulb (a small sphere) and register it for animation.

    Parameters:
        x, y  : playfield position in physics units.
        h     : height above the board in world units.
        size  : sphere diameter in world units.
        kind  : 'cycle' -> pulsing rainbow colour; any other value is treated
                as 'chase' (a brightness wave travelling along a row).
        phase : phase offset: degrees of hue for 'cycle', fraction of a cycle
                (0..~1) for 'chase'.
    Returns:
        the Entity (also appended to the global `leds` list as
        (entity, kind, phase)).  Colours are assigned in update().
    """
    e = mk(model='sphere', position=(x * S, h, y * S), scale=size, color=color.white)
    leds.append((e, kind, phase))
    return e


def add_wall(a, b, r=4, mat='steel', height=2.2, led_step=70):
    """Add a static wall: physics segment + 3D visual + optional LED bulbs.

    Physics: a static pymunk Segment from a to b with rounded ends of radius r
    (so total thickness 2r) and the elasticity/friction of material `mat`.
    Visual : a dark body box of the given height, a thin bright neon "cap" box
    on top (registered in `neon` for colour animation; its phase is
    (a.x + a.y) * 0.35 so neighbouring walls differ), and LED bulbs on top
    every `led_step` units.

    Parameters:
        a, b     : end points (physics units).
        r        : segment radius (physics units).
        mat      : key into MAT.
        height   : visual height of the wall body (world units).
        led_step : spacing of LED bulbs along the wall in physics units;
                   0 (or any falsy value) disables the bulbs.
                   The number of bulbs is max(1, int(length // led_step)),
                   evenly spaced at the middle of equal sub-intervals, at
                   height `height + 0.65`, with random hue phases.
    Returns:
        the pymunk Segment.
    """
    seg = pymunk.Segment(space.static_body, a, b, r)
    seg.elasticity, seg.friction = MAT[mat]
    space.add(seg)
    # dark body
    seg_visual(a, b, r * 2, height, WALL_BODY, extra=r)
    # bright neon cap sitting on top of the body
    cap = seg_visual(a, b, r * 2 + 1.5, 0.4, color.white, y0=height, extra=r + 1)
    neon.append((cap, (a[0] + a[1]) * 0.35))
    if led_step:
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(length // led_step))
        for k in range(n):
            t = (k + 0.5) / n
            add_led(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t,
                    h=height + 0.65, size=0.4, phase=random.uniform(0, 360))
    return seg


def add_post(x, y, r=5, hue=215):
    """Add a rubber post: a static circular collider plus a two-sphere visual.

    Parameters:
        x, y : centre (physics units).
        r    : collider radius (physics units).
        hue  : colour hue in degrees.
    The collider uses MAT['rubber'].  The visual is a flattened coloured sphere
    (the post body) with a small bright cap sphere above it.
    """
    shp = pymunk.Circle(space.static_body, r, (x, y))
    shp.elasticity, shp.friction = MAT['rubber']
    space.add(shp)
    mk(model='sphere', color=color.hsv(hue, 0.8, 0.45), scale=(r * 2.4 * S, 1.6, r * 2.4 * S), position=(x * S, 0.5, y * S))
    mk(model='sphere', color=color.hsv(hue, 0.4, 1), scale=(r * 1.3 * S, 0.4, r * 1.3 * S), position=(x * S, 1.3, y * S))


# --------------------------------------------------------------------------
# Floor, cabinet, back box  (world space)
# --------------------------------------------------------------------------
# Wooden pub floor: a dark slab plus 49 planks (3.9 wide, 400 long, running
# along z) with slightly random brown tones; the 0.1 gaps between planks show
# the dark slab.  parent=scene so the floor stays still when the machine is
# nudged.  A private Random(7) keeps the pattern identical on every run.
wk(parent=scene, model='cube', color=color.hsv(20, 0.6, 0.07), scale=(400, 1, 400), position=(0, -0.5, 0))
_rng = random.Random(7)
for i in range(-24, 25):
    wk(parent=scene, model='cube', color=color.hsv(18 + _rng.uniform(-4, 6), 0.65, 0.17 + _rng.uniform(0, 0.07)),
       scale=(3.9, 0.06, 400), position=(i * 4, 0.03, 0))
# Dark rectangle under the machine imitating a soft shadow (moves with the machine).
wk(model='cube', color=color.hsv(255, 0.8, 0.02), scale=(44, 0.04, 78), position=(0, 0.06, 1))   # soft shadow

# Four chrome legs with orange feet.  The far legs (z = +35.5) are 17 units
# tall and the near legs (z = -33.5) 8.8 because the table is tilted with its
# far end raised.
for lx in (-18.6, 18.6):                                   # chrome legs
    wk(model='cube', color=CHROME, scale=(1.5, 8.8, 1.5), position=(lx, 4.4, -33.5))
    wk(model='cube', color=CHROME, scale=(1.5, 17.0, 1.5), position=(lx, 8.5, 35.5))
    wk(model='cube', color=color.hsv(20, 0.8, 0.9), scale=(2.2, 0.5, 2.2), position=(lx, 0.25, -33.5))
    wk(model='cube', color=color.hsv(20, 0.8, 0.9), scale=(2.2, 0.5, 2.2), position=(lx, 0.25, 35.5))

# Cabinet body and front apron.  These use mk() so they are children of the
# TILTED table and share its tilt.
# table body / apron (tilts with the table)
mk(model='cube', color=WOOD, scale=(39.6, 4, 73), position=(0, -3, 1))               # box under the board
mk(model='cube', color=color.hsv(18, 0.6, 0.30), scale=(39.6, 0.3, 73), position=(0, -5.2, 1))   # underside
mk(model='cube', color=WOOD, scale=(40.6, 5.5, 1.6), position=(0, 0.6, -37.2))       # front apron
mk(model='cube', color=WOOD_TOP, scale=(40.6, 0.3, 1.6), position=(0, 3.5, -37.2))   # apron top trim
mk(model='cube', color=color.hsv(250, 0.7, 0.12), scale=(14, 3.4, 0.3), position=(0, 0.4, -38.1))   # coin door
# Two glowing coin slots on the coin door (registered as neon strips).
for sx in (-4, 4):
    e = mk(model='cube', color=color.white, scale=(1.4, 0.4, 0.2), position=(sx, 1.2, -38.3))
    neon.append((e, sx * 40))
mk(model='cube', color=CHROME, scale=(7, 0.8, 0.8), position=(0, 3.1, -38.0))                         # lock-down bar
# Underglow: neon strips below the cabinet sides and front.
for sx in (-1, 1):                                                                                      # underglow
    e = mk(model='cube', color=color.white, scale=(0.35, 0.35, 72), position=(sx * 20.1, -5.0, 1))
    neon.append((e, sx * 90))
e = mk(model='cube', color=color.white, scale=(40, 0.35, 0.35), position=(0, -5.0, -37.5))
neon.append((e, 45))
# Cabinet flipper buttons on the side rails; update() turns them yellow when
# the corresponding flipper keys are pressed (and not tilted).
btn_l = mk(model='sphere', color=color.red, scale=(1.5, 1.0, 1.5), position=(-20.5, 1.6, -28))        # cabinet flipper buttons
btn_r = mk(model='sphere', color=color.red, scale=(1.5, 1.0, 1.5), position=(20.5, 1.6, -28))

# The board itself: a dark slab (top surface at y = 0) with a lighter inset.
# board
mk(model='cube', color=color.hsv(258, 0.6, 0.20), scale=(36.8, 1, 70), position=(0, -0.5, 1))
mk(model='cube', color=color.hsv(262, 0.55, 0.27), scale=(35.6, 0.2, 68), position=(0, 0.0, 1))
# Wooden side rails (with a light top strip) and the back rail.
for xx in (-19.4, 19.4):                                           # side rails
    mk(model='cube', color=WOOD, scale=(1.8, 3.4, 70), position=(xx, 1.2, 1))
    mk(model='cube', color=WOOD_TOP, scale=(1.2, 0.3, 70), position=(xx, 3.0, 1))
mk(model='cube', color=WOOD, scale=(40.6, 3.4, 1.8), position=(0, 1.2, 36.6))

# ---- playfield artwork ----
# Starburst: 12 thin coloured bars (150 units long) radiating every 30 degrees
# from the art centre (CX, -40); hue = 30 deg * index.  Purely decorative.
for i in range(12):                                                # starburst
    ang = i * 30
    L = 150
    ar = math.radians(ang)
    mk(model='cube', color=color.hsv(i * 30, 0.7, 0.30), scale=(L * S, 0.03, 5 * S),
       position=((CX + L / 2 * math.cos(ar)) * S, 0.025, (-40 + L / 2 * math.sin(ar)) * S), rotation_y=-ang)
# Four concentric flat discs (flattened spheres), drawn at slightly increasing
# heights so each covers the previous one: (diameter in world units, hue,
# brightness, height).
for sc, hue, val, yy in [(30, 285, 0.30, 0.03), (22, 215, 0.34, 0.04), (14, 330, 0.40, 0.05), (6, 50, 0.55, 0.06)]:
    mk(model='sphere', color=color.hsv(hue, 0.75, val), scale=(sc, 0.03, sc), position=(CX * S, yy, -4))
# 14 insert lights on an ellipse (70 x 62 units) around the art centre; the
# phase i/14 makes a brightness wave run around the ellipse.
inserts = []
for i in range(14):                                                # flowing insert lights
    a = math.radians(i * 360 / 14)
    e = mk(model='sphere', scale=(1.3, 0.05, 1.3),
           position=((CX + 70 * math.cos(a)) * S, 0.09, (-40 + 62 * math.sin(a)) * S), color=color.white)
    inserts.append((e, i / 14.0))
# Five 8-point star inserts: each is 4 thin bars rotated 0/45/90/135 degrees.
# stars entries are ([bars], x) where x only serves as a colour phase.
stars = []
for (sx_, sy_) in [(-120, 0), (86, 0), (-17, 20), (-120, 110), (86, 110)]:        # star inserts
    parts = []
    for k in range(4):
        parts.append(mk(model='cube', color=color.white, scale=(3.2, 0.05, 0.5), position=(sx_ * S, 0.1, sy_ * S),
                        rotation_y=k * 45))
    stars.append((parts, sx_))

# Back box: an upright panel 40 wide x 15 tall (y 17.5 .. 32.5) behind the
# table with a neon frame, a strip of 17 equalizer bars along its bottom edge
# (y ~ 18) and, above them, the PICTURE PUZZLE.  wk() => children of
# `machine`, upright (not tilted), z ~ 38-40.  update() animates the bars.
# back box with equalizer + puzzle (world space, upright)
wk(model='cube', color=color.hsv(250, 0.7, 0.09), scale=(40, 15, 1.2), position=(0, 25.0, 39.6))
for (sx, sy, sz, px_, py_) in [(40, 0.4, 0.4, 0, 32.4), (40, 0.4, 0.4, 0, 17.6),
                               (0.4, 15, 0.4, -20, 25.0), (0.4, 15, 0.4, 20, 25.0)]:
    e = wk(model='cube', color=color.white, scale=(sx, sy, sz), position=(px_, py_, 38.9))
    neon.append((e, px_ * 3 + py_ * 9))
eq_bars = []
for i in range(17):
    e = wk(model='cube', color=color.white, scale=(1.5, 1, 0.3), position=((i - 8) * 2.2, 18.6, 38.9))
    eq_bars.append((e, i))

# --------------------------------------------------------------------------
# Picture puzzle (module docstring section 15)
# --------------------------------------------------------------------------
PUZ_COLS, PUZ_ROWS = 8, 3                 # tile grid
PUZ_W, PUZ_H = 32.0, 10.2                 # picture size in world units
PUZ_CX, PUZ_CY = 0.0, 25.7                # picture centre (x, y) on the back box
PUZ_TILE_COST = 300                       # bonus points needed to open one tile
PUZ_PIC_W, PUZ_PIC_H = 112, 36            # pixel-art resolution of each picture
TILE_W = PUZ_W / PUZ_COLS                 # one tile, world units
TILE_H = PUZ_H / PUZ_ROWS

# Four thin neon strips framing the picture (they flash when it is completed).
puz_frame = []
for (sx, sy, px_, py_) in [(PUZ_W + 0.9, 0.35, 0.0, PUZ_CY + PUZ_H / 2 + 0.3),
                           (PUZ_W + 0.9, 0.35, 0.0, PUZ_CY - PUZ_H / 2 - 0.3),
                           (0.35, PUZ_H + 0.9, -PUZ_W / 2 - 0.3, PUZ_CY),
                           (0.35, PUZ_H + 0.9, PUZ_W / 2 + 0.3, PUZ_CY)]:
    puz_frame.append(wk(model='cube', color=color.white, scale=(sx, sy, 0.4), position=(px_, py_, 38.7)))


def _mix(a, b, t):
    """Linear blend of two RGB tuples (components 0..1); t is clamped to 0..1."""
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


# Building silhouettes for the sunset picture: (first column, width, height).
_SKYLINE = [(2, 6, 9), (9, 5, 13), (15, 7, 7), (23, 6, 11), (30, 5, 6),
            (78, 6, 8), (85, 7, 12), (93, 5, 7), (99, 7, 14), (107, 5, 9)]


def pic_sunset(x, y):
    """Picture 1 "NEON SUNSET": returns the RGB (0..1) of pixel (x, y), y = 0 on top.

    Sky above the horizon row 22: a purple-to-pink gradient, a few stars, a big
    sun (radius 15 at (56, 18)) whose lower part is cut by horizontal stripes
    every third row, and a skyline of dark buildings with yellow windows.
    Below the horizon: a dark violet floor with pink horizontal lines at
    perspective-spaced rows and cyan radial lines converging to the sun.
    """
    hy = 22
    if y < hy:
        c = _mix((0.04, 0.0, 0.22), (1.0, 0.30, 0.55), (y / hy) ** 1.4)
        if y < 13 and (x * 7 + y * 13) % 37 == 0:
            c = (1.0, 1.0, 1.0)
        dx, dy = x - 56, y - 18
        if dx * dx + dy * dy < 225 and not (y > 14 and y % 3 == 0):
            c = _mix((1.0, 0.95, 0.25), (1.0, 0.15, 0.55), (y - 3) / 18.0)
        for (bx0, bw, bh) in _SKYLINE:
            if bx0 <= x < bx0 + bw and y >= hy - bh:
                lit = (x - bx0) % 2 == 1 and (y + x) % 3 == 0
                c = (1.0, 0.8, 0.3) if lit else (0.03, 0.0, 0.12)
        return c
    c = _mix((0.30, 0.0, 0.45), (0.06, 0.0, 0.15), (y - hy) / (PUZ_PIC_H - hy))
    if (y - hy) in (1, 3, 6, 10, 13):
        c = (1.0, 0.2, 0.8)
    u = (x - 56) / (y - hy + 1.0)
    if abs(u - round(u / 2.5) * 2.5) < 0.22:
        c = (0.2, 0.9, 1.0)
    return c


def pic_beer(x, y):
    """Picture 2 "A COLD ONE": returns the RGB (0..1) of pixel (x, y).

    A brick wall (running-bond pattern with mortar) with two warm lamp glows, a
    wooden bar top from row 32 down, and a pint glass at x = 56: a trapezoid
    (12 px half-width at the top, 8 at the bottom) holding amber beer with
    bubbles and a scalloped foam head, pale glass edges and a handle on the
    right (an elliptical ring).
    """
    row = y // 3
    off = 4 if row % 2 else 0
    if y % 3 == 0 or (x + off) % 8 == 0:
        c = (0.15, 0.06, 0.05)
    else:
        c = (0.36 + 0.04 * ((x // 8 + row) % 3), 0.12, 0.08)
    for lx in (14, 98):
        d2 = (x - lx) ** 2 + (y - 6) ** 2
        if d2 < 90:
            c = _mix(c, (1.0, 0.8, 0.4), 1.0 - d2 / 90.0)
    if y >= 32:
        c = (0.30 + 0.05 * (y % 2), 0.16, 0.07)
        if y == 32:
            c = (0.75, 0.48, 0.2)
        return c
    if 5 <= y <= 31:
        hw = 12.0 - 4.0 * (y - 5) / 26.0
        dx = x - 56
        if abs(dx) <= hw:
            if y <= 10:
                top = 5 + (1 if x % 4 < 2 else 0)
                if y >= top:
                    c = (0.98, 0.96, 0.88)
            else:
                c = _mix((1.0, 0.78, 0.15), (0.75, 0.40, 0.04), (y - 10) / 21.0)
                if (x * 5 + y * 11) % 19 == 0:
                    c = (1.0, 0.95, 0.6)
            if abs(dx) >= hw - 1.0:
                c = _mix(c, (0.8, 0.95, 1.0), 0.6)
        d = ((x - 70) / 5.0) ** 2 + ((y - 18) / 7.0) ** 2
        if 0.5 < d < 1.0 and x > 56 + hw:
            c = (0.8, 0.95, 1.0)
    return c


def pic_planet(x, y):
    """Picture 3 "CHROME PLANET": returns the RGB (0..1) of pixel (x, y).

    A dark blue space gradient with two kinds of stars; a ringed planet centred
    at (80, 18) (radius 13, orange/red bands, shaded from the lower right, the
    ring drawn behind the planet above its equator and in front below it); a
    chrome ball at (26, 20) with a white highlight and a horizon reflection;
    and a dotted parabolic trajectory between them.
    """
    c = _mix((0.0, 0.0, 0.08), (0.12, 0.03, 0.25), y / PUZ_PIC_H)
    if (x * 11 + y * 17) % 43 == 0:
        c = (1.0, 1.0, 1.0)
    elif (x * 5 + y * 3) % 61 == 0:
        c = (0.6, 0.6, 0.9)
    dx, dy = x - 80, y - 18
    d = math.hypot(dx, dy)
    ring = 0.62 < (dx / 27.0) ** 2 + (dy / 7.0) ** 2 < 1.0
    if ring and dy < 0:
        c = (0.85, 0.7, 0.5)
    if d < 13:
        band = int((y + x * 0.15) / 3) % 3
        base = ((1.0, 0.55, 0.15), (0.85, 0.3, 0.1), (1.0, 0.75, 0.4))[band]
        shade = max(0.35, min(1.0, 0.75 - (dx + dy) / 26.0))
        c = (base[0] * shade, base[1] * shade, base[2] * shade)
    if ring and dy >= 0:
        c = (0.95, 0.8, 0.55)
    bx, by = x - 26, y - 20
    bd = math.hypot(bx, by)
    if bd < 10:
        c = _mix((0.2, 0.25, 0.4), (0.9, 0.95, 1.0), 1.0 - bd / 10.0)
        if math.hypot(bx + 3, by + 4) < 2.5:
            c = (1.0, 1.0, 1.0)
        if 1 < by < 2:
            c = (0.55, 0.7, 0.95)
    for k in range(10):
        if (x, y) == (40 + k * 3, 12 + int((k - 5) ** 2 * 0.4)):
            c = (0.7, 0.9, 1.0)
    return c


# (title, pixel function) of every puzzle picture, in play order.
PUZ_PICTURES = [('NEON SUNSET', pic_sunset), ('A COLD ONE', pic_beer), ('CHROME PLANET', pic_planet)]


def make_picture_texture(fn):
    """Render a picture function into a Panda3D texture.

    Evaluates fn(x, y) for all 112 x 36 pixels into a PNMImage (setXel takes
    floats 0..1; PNMImage row 0 is the TOP row, which Panda maps upright), loads
    it into a Texture and sets nearest-neighbour magnification so the pixels
    stay crisp and linear minification so it does not shimmer from far away.

    Parameters:
        fn : callable (x, y) -> (r, g, b).
    Returns:
        the Panda3D Texture, or None if the classes are unavailable or anything
        fails (the caller then falls back to a solid colour).
    """
    if PNMImage is None or PandaTexture is None:
        return None
    try:
        img = PNMImage(PUZ_PIC_W, PUZ_PIC_H)
        for yy in range(PUZ_PIC_H):
            for xx in range(PUZ_PIC_W):
                r, g, b = fn(xx, yy)
                img.setXel(xx, yy, r, g, b)
        tex = PandaTexture()
        tex.load(img)
        if SamplerState is not None:
            tex.setMagfilter(SamplerState.FT_nearest)
            tex.setMinfilter(SamplerState.FT_linear)
        return tex
    except Exception:
        return None


# One quad shows the current picture; its texture is switched by
# puzzle_set_picture().  The three textures are rendered once, here.
puz_picture = wk(model='quad', color=color.white, scale=(PUZ_W, PUZ_H), position=(PUZ_CX, PUZ_CY, 38.9))
puz_textures = [make_picture_texture(fn) for (_title, fn) in PUZ_PICTURES]

# 24 cover tiles (dark violet quads with a lighter inset and a gold emblem) in
# front of the picture (z 38.8 < 38.9, i.e. nearer to the camera).  Each dict:
# cover / emb (entities), state 0 closed, 1 opening (flip animation), 2 open,
# t (animation time), col / row (grid position, row 0 on top).
puz_tiles = []
for _r in range(PUZ_ROWS):
    for _c in range(PUZ_COLS):
        _x0 = PUZ_CX - PUZ_W / 2 + TILE_W * (_c + 0.5)
        _y0 = PUZ_CY + PUZ_H / 2 - TILE_H * (_r + 0.5)
        _cover = wk(model='quad', color=color.hsv(252, 0.55, 0.20),
                    scale=(TILE_W * 0.96, TILE_H * 0.94), position=(_x0, _y0, 38.8))
        wk(parent=_cover, model='quad', color=color.hsv(258, 0.5, 0.32), scale=(0.84, 0.8), position=(0, 0, -0.01))
        _emb = wk(parent=_cover, model='sphere', color=color.hsv(48, 0.8, 0.9), scale=(0.22, 0.28, 0.02), position=(0, 0, -0.02))
        puz_tiles.append(dict(cover=_cover, emb=_emb, state=0, t=0.0, col=_c, row=_r))


def puzzle_set_picture():
    """Show the picture st.puz_idx on the puzzle quad.

    Applies the pre-rendered texture with NodePath.setTexture(tex, 1) and a
    white colour scale.  If that texture is missing (creation failed) or the call
    raises, the quad gets a solid colour (hue depending on the picture index).
    """
    tex = puz_textures[st.puz_idx]
    if tex is not None:
        try:
            puz_picture.setTexture(tex, 1)
            puz_picture.color = color.white
            return
        except Exception:
            pass
    puz_picture.color = color.hsv((st.puz_idx * 110 + 20) % 360, 0.6, 0.7)


def puzzle_reset(idx=0):
    """Cover the puzzle again, showing picture number `idx` (modulo 3).

    Resets the point counter, opened count and timers, shuffles the order in
    which tiles will open, re-enables and restores every cover tile (colour and
    width) and switches the picture.  Called by reset_game() (idx 0) and
    automatically 6 s after a picture is completed (idx + 1).
    """
    st.puz_idx = idx % len(PUZ_PICTURES)
    st.puz_pts = 0
    st.puz_open = 0
    st.puz_done_t = 0.0
    st.puz_flash = 0.0
    order = list(range(len(puz_tiles)))
    random.shuffle(order)
    st.puz_order = order
    for tl in puz_tiles:
        tl['state'] = 0
        tl['t'] = 0.0
        tl['cover'].enabled = True
        tl['cover'].scale_x = TILE_W * 0.96
        tl['cover'].color = color.hsv(252, 0.55, 0.20)
    puzzle_set_picture()


def add_puzzle(n):
    """Collect n bonus points toward opening puzzle tiles.

    Adds n to st.puz_pts, then, while at least PUZ_TILE_COST points are
    available, tiles remain and no finished picture is on show: subtracts the
    cost, starts the opening animation of the next tile of st.puz_order and
    counts it.  When the last tile opens the picture is complete: +10000 score,
    st.puz_done_t = 6 s of display, st.puz_flash = 6 s of frame flashing and a
    message with the picture title.  Points collected while the finished
    picture is on show are kept for the next picture.

    Parameters:
        n : points to add (callers pass the same amounts they add to the bonus).
    """
    st.puz_pts += n
    while (st.puz_pts >= PUZ_TILE_COST and st.puz_open < len(puz_tiles)
           and st.puz_done_t <= 0):
        st.puz_pts -= PUZ_TILE_COST
        tl = puz_tiles[st.puz_order[st.puz_open]]
        tl['state'] = 1
        tl['t'] = 0.0
        st.puz_open += 1
        if st.puz_open >= len(puz_tiles):
            st.score += 10000
            st.puz_done_t = 6.0
            st.puz_flash = 6.0
            show_msg(f'PICTURE COMPLETE: {PUZ_PICTURES[st.puz_idx][0]}  +10000', 3.0, color.hsv(55, 0.9, 1))


def puzzle_update(dt):
    """Per-frame puzzle animation (called from update()).

    * Tiles in state 1 flip open in 0.45 s: the cover's width shrinks to 0
      (progress p = t / 0.45), its colour is a bright flash during the first half
      and a fading gold afterwards; at p = 1 the cover is hidden (state 2).
    * Counts down the frame-flash timer.
    * While a finished picture is on show, counts down st.puz_done_t; at zero
      switches to the next picture via puzzle_reset(st.puz_idx + 1).

    Parameters:
        dt : frame time in seconds.
    """
    for tl in puz_tiles:
        if tl['state'] == 1:
            tl['t'] += dt
            p = min(1.0, tl['t'] / 0.45)
            cv = tl['cover']
            cv.scale_x = TILE_W * 0.96 * (1.0 - p)
            cv.color = color.hsv(50, 0.15, 1.0) if p < 0.5 else color.hsv(48, 0.8, 1.0 - p)
            if p >= 1.0:
                cv.enabled = False
                tl['state'] = 2
    if st.puz_flash > 0:
        st.puz_flash -= dt
    if st.puz_done_t > 0:
        st.puz_done_t -= dt
        if st.puz_done_t <= 0:
            puzzle_reset(st.puz_idx + 1)


# --------------------------------------------------------------------------
# Bar scenery (module docstring section 16)
# --------------------------------------------------------------------------
warm = []          # warm light bulbs: (entity, phase); candles, pendant lamps


def build_bar():
    """Build the whole pub around and behind the machine (world space, never moves).

    Everything is created with wk(parent=scene, ...) from two local helpers:
        box(x, y0, z, sx, sy, sz, col): cube standing on height y0 (centre-based x, z)
        orb(x, y, z, sx, sy, sz, col) : sphere/ellipsoid centred at y
    A private Random(11) chooses the bottle colours so the scene is identical on
    every run.  The back wall is at z = 86; the camera (view 0) sees it up to a
    height of about 26 units, so the tallest decorations stay below that.

    Layout (x = left/right, z = depth behind the machine):
      * brick back wall + two side walls, mortar lines, wainscot panel + trim;
      * mirror, three shelves with 12 bottles each (body + neck), neon
        underlights on every shelf;
      * bar counter at z = 76 (front planks, top, chrome foot rail, neon strip),
        four beer taps, four pint glasses, a cash register with a glowing screen;
      * five red stools in front of the counter (z = 69);
      * neon "BAR" sign (pixel font, 30 glowing cubes) at the left;
      * dart board (7 rings), two framed posters and a clock at the right;
      * three pendant lamps over the bar;
      * jukebox with glowing glass and side neon at x = -42;
      * two rugs and four round tables, each with candle and two stools;
      * pool table at x = 70, z = 60 (frame, felt, cushions, 6 pockets, racked
        balls, cue ball, legs) with a hanging lamp.
    Neon pieces are added to `neon` (they strobe during a TILT); candles and lamp
    bulbs to `warm`.
    """
    rng = random.Random(11)
    WZ = 86.0
    brick = color.hsv(8, 0.55, 0.26)
    mortar = color.hsv(8, 0.45, 0.14)
    darkwood = color.hsv(18, 0.6, 0.20)
    wood = color.hsv(24, 0.55, 0.38)

    def box(x, y0, z, sx, sy, sz, col):
        return wk(parent=scene, model='cube', color=col, scale=(sx, sy, sz), position=(x, y0 + sy / 2, z))

    def orb(x, y, z, sx, sy, sz, col):
        return wk(parent=scene, model='sphere', color=col, scale=(sx, sy, sz), position=(x, y, z))

    # ---- walls ----
    box(0, 0, WZ, 320, 46, 1.5, brick)
    box(-110, 0, 30, 1.5, 46, 120, brick)
    box(110, 0, 30, 1.5, 46, 120, brick)
    for k in range(17):                                   # horizontal mortar lines
        box(0, 1.2 + k * 2.4, WZ - 0.8, 320, 0.12, 0.08, mortar)
    box(0, 0, WZ - 0.9, 320, 6.5, 0.4, darkwood)          # wainscot
    box(0, 6.5, WZ - 0.95, 320, 0.4, 0.6, wood)           # wainscot trim

    # ---- mirror, shelves, bottles ----
    box(0, 8.5, WZ - 0.85, 58, 14, 0.15, color.hsv(200, 0.25, 0.40))
    hues = (0, 25, 50, 120, 150, 200, 280, 330)
    for row in range(3):
        y = 8.9 + row * 4.5
        box(0, y - 0.5, WZ - 2.2, 58, 0.5, 2.4, wood)
        e = box(0, y - 0.65, WZ - 1.1, 58, 0.15, 0.2, color.white)
        neon.append((e, row * 70))
        for k in range(12):
            h = rng.choice(hues)
            x = -26.4 + k * 4.8
            box(x, y, WZ - 2.2, 1.3, 2.6, 1.3, color.hsv(h, 0.75, 0.6))
            box(x, y + 2.6, WZ - 2.2, 0.5, 1.5, 0.5, color.hsv(h, 0.6, 0.72))

    # ---- bar counter ----
    box(0, 0, 76, 66, 8, 5.5, color.hsv(18, 0.6, 0.22))
    for k in range(-30, 31, 6):                           # front planks
        box(k, 0.8, 73.1, 5.4, 6.4, 0.2, color.hsv(18, 0.6, 0.28))
    box(0, 8, 76, 68, 0.8, 7, color.hsv(28, 0.5, 0.45))   # counter top
    box(0, 1.4, 72.6, 64, 0.35, 0.35, CHROME)             # foot rail
    e = box(0, 0.3, 73.0, 64, 0.2, 0.15, color.white)     # neon underlight
    neon.append((e, 200))
    for k, x in enumerate((-9, -3, 3, 9)):                # beer taps
        box(x, 8.8, 77.2, 0.5, 2.2, 0.5, CHROME)
        orb(x, 11.4, 77.2, 0.7, 1.1, 0.7, color.hsv((k * 90 + 20) % 360, 0.7, 0.8))
        box(x, 9.6, 76.6, 0.3, 0.3, 1.0, CHROME)
    for (x, z) in ((-20, 75.5), (15, 76.5), (24, 75.0), (-28, 76.2)):      # pint glasses
        box(x, 8.8, z, 1.3, 2.0, 1.3, color.hsv(38, 0.9, 0.75))
        box(x, 10.8, z, 1.4, 0.5, 1.4, color.hsv(48, 0.1, 0.97))
    box(30, 8.8, 77, 3.2, 2.0, 2.4, color.hsv(220, 0.15, 0.3))             # cash register
    e = box(30, 10.2, 75.8, 2.0, 0.9, 0.1, color.white)
    neon.append((e, 120))

    # ---- stools ----
    for x in (-24, -12, 0, 12, 24):
        orb(x, 0.15, 69, 2.6, 0.15, 2.6, CHROME)
        box(x, 0.2, 69, 0.5, 5.0, 0.5, CHROME)
        orb(x, 2.4, 69, 2.0, 0.12, 2.0, CHROME)
        orb(x, 5.9, 69, 2.8, 1.0, 2.8, color.hsv(355, 0.8, 0.55))

    # ---- neon BAR sign (left wall) ----
    bar_font = {'B': ['110', '101', '110', '101', '110'],
                'A': ['010', '101', '111', '101', '101'],
                'R': ['110', '101', '110', '101', '101']}
    box(-60, 9.4, WZ - 0.9, 27, 13, 0.3, color.hsv(250, 0.6, 0.08))
    for li, ch in enumerate('BAR'):
        for r, rowbits in enumerate(bar_font[ch]):
            for c, bit in enumerate(rowbits):
                if bit == '1':
                    e = wk(parent=scene, model='cube', color=color.white, scale=(2.0, 2.0, 0.4),
                           position=(-71 + (li * 4 + c) * 2.2, 10 + (4 - r) * 2.2 + 1.1, WZ - 1.1))
                    neon.append((e, li * 90 + r * 20))

    # ---- dart board, posters, clock (right wall) ----
    box(58, 8.5, WZ - 0.9, 13, 11, 0.3, color.hsv(30, 0.4, 0.22))
    for i, (d, col) in enumerate([(10.6, color.hsv(0, 0, 0.05)), (9.2, color.hsv(0, 0.8, 0.6)),
                                  (7.8, color.hsv(45, 0.3, 0.9)), (6.4, color.hsv(130, 0.7, 0.45)),
                                  (5.0, color.hsv(45, 0.3, 0.9)), (2.2, color.hsv(0, 0.8, 0.6)),
                                  (1.0, color.hsv(130, 0.7, 0.45))]):
        orb(58, 14, WZ - 1.0 - 0.1 * i, d, d, 0.12, col)
    for (x, hue) in ((40, 200), (76, 30)):
        box(x, 9, WZ - 0.9, 8, 10, 0.3, color.hsv(30, 0.5, 0.2))
        box(x, 9.6, WZ - 1.0, 6.6, 8.8, 0.1, color.hsv(hue, 0.6, 0.5))
        orb(x, 13.5, WZ - 1.1, 2.6, 2.6, 0.1, color.hsv(hue + 40, 0.8, 1))
        box(x, 10.5, WZ - 1.1, 6.6, 1.0, 0.1, color.hsv(hue + 80, 0.7, 0.8))
    orb(58, 22.5, WZ - 0.9, 5.0, 5.0, 0.2, color.hsv(30, 0.5, 0.25))      # clock rim
    orb(58, 22.5, WZ - 1.0, 4.2, 4.2, 0.2, color.hsv(48, 0.1, 0.95))      # clock face
    box(58, 22.5, WZ - 1.2, 0.2, 1.7, 0.05, color.black)                  # minute hand
    box(58, 22.4, WZ - 1.2, 1.2, 0.2, 0.05, color.black)                  # hour hand

    # ---- pendant lamps over the bar ----
    for x in (-20, 0, 20):
        box(x, 19.5, 78, 0.1, 8, 0.1, color.hsv(0, 0, 0.1))
        orb(x, 19.3, 78, 4.2, 1.8, 4.2, color.hsv(150, 0.6, 0.30))
        b = orb(x, 18.2, 78, 1.3, 1.3, 1.3, color.white)
        warm.append((b, x))

    # ---- jukebox ----
    box(-42, 0, 82, 8, 13, 4.4, color.hsv(12, 0.8, 0.45))
    orb(-42, 13, 82, 8, 5, 4.4, color.hsv(12, 0.8, 0.45))
    e = box(-42, 3.5, 79.7, 5.6, 7.5, 0.2, color.white)
    neon.append((e, 300))
    box(-42, 9.0, 79.6, 4, 2.5, 0.2, color.hsv(0, 0, 0.1))
    box(-42, 1, 79.6, 7, 0.4, 0.2, CHROME)
    for sx in (-45.6, -38.4):
        e = box(sx, 1, 79.7, 0.3, 11, 0.2, color.white)
        neon.append((e, 330 + sx))

    # ---- rugs, tables, stools ----
    box(-50, 0.03, 24, 22, 0.04, 40, color.hsv(355, 0.7, 0.22))
    box(52, 0.03, 24, 22, 0.04, 40, color.hsv(220, 0.6, 0.22))

    def round_table(x, z):
        orb(x, 7.6, z, 7.5, 0.5, 7.5, wood)
        box(x, 0.3, z, 0.7, 7.2, 0.7, color.hsv(220, 0.2, 0.25))
        orb(x, 0.25, z, 3.6, 0.25, 3.6, color.hsv(220, 0.2, 0.2))
        c = orb(x, 8.2, z, 0.5, 0.7, 0.5, color.white)
        warm.append((c, x))
        for sx in (-5.5, 5.5):
            box(x + sx, 0.2, z, 0.5, 4.6, 0.5, CHROME)
            orb(x + sx, 5.0, z, 2.6, 0.9, 2.6, color.hsv(355, 0.7, 0.45))

    for (x, z) in ((-44, 10), (-56, 38), (46, 12), (58, 36)):
        round_table(x, z)

    # ---- pool table ----
    px, pz = 70.0, 60.0
    box(px, 5.2, pz, 20, 2.0, 36, darkwood)
    box(px, 7.2, pz, 17, 0.3, 33, color.hsv(140, 0.7, 0.35))
    for (cx_, cz_, sx, sz) in ((0, 17.4, 20, 1.4), (0, -17.4, 20, 1.4), (9.4, 0, 1.4, 36), (-9.4, 0, 1.4, 36)):
        box(px + cx_, 7.2, pz + cz_, sx, 0.7, sz, wood)
    for (ox, oz) in ((-8, -16), (8, -16), (-8.4, 0), (8.4, 0), (-8, 16), (8, 16)):
        orb(px + ox, 7.55, pz + oz, 2.0, 0.1, 2.0, color.black)
    row_n = 0
    for rr in range(4):                                   # racked balls (triangle of 10)
        for k in range(rr + 1):
            orb(px - rr * 0.0 + (k - rr / 2.0) * 1.0, 8.0, pz + 8 + rr * 0.9, 0.9, 0.9, 0.9,
                color.hsv((row_n * 47) % 360, 0.8, 0.9))
            row_n += 1
    orb(px, 8.0, pz - 8, 0.9, 0.9, 0.9, color.hsv(0, 0, 0.97))               # cue ball
    for (lx_, lz_) in ((-8, -15), (8, -15), (-8, 15), (8, 15)):             # legs
        box(px + lx_, 0, pz + lz_, 1.4, 5.2, 1.4, wood)
    box(px, 21, pz, 14, 0.6, 3, color.hsv(150, 0.6, 0.30))                  # lamp shade
    b = box(px, 20.5, pz, 13, 0.15, 2.5, color.white)
    warm.append((b, 77))
    for sx in (-5, 5):
        box(px + sx, 21.6, pz, 0.1, 6, 0.1, color.hsv(0, 0, 0.1))


# Set BAR_SCENERY = False to skip the pub (about 400 entities) on slow computers.
BAR_SCENERY = True
if BAR_SCENERY:
    build_bar()

# --------------------------------------------------------------------------
# Extra playfield details: rivets, chevron arrows, glass reflections
# --------------------------------------------------------------------------
# 24 chrome rivets (small spheres) along the tops of the two wooden side rails.
for _xx in (-19.4, 19.4):
    for _zz in range(-33, 35, 6):
        mk(model='sphere', color=CHROME, scale=0.38, position=(_xx, 3.2, _zz))

arrows = []        # ([2 entities], phase) chevron arrows, lit by a travelling wave


def add_arrow(x, y, ang_deg, phase, size=3.0):
    """Add a chevron ("V") arrow light on the playfield pointing in a direction.

    The arrow is two flat bars whose outer ends trail behind the tip at +/-38
    degrees from the reverse direction.  The tip is at playfield position (x, y)
    (physics units); the arms are `size` world units long.

    Parameters:
        x, y     : tip position in physics units.
        ang_deg  : direction the arrow points, in physics degrees
                   (counter-clockwise from +x).
        phase    : phase 0..~1 of the chase animation (see update()).
        size     : arm length in world units.
    The pair is appended to `arrows` as (entities, phase).
    """
    parts = []
    for side in (-1, 1):
        a_deg = ang_deg + 180 + side * 38
        a = math.radians(a_deg)
        parts.append(mk(model='cube', color=color.white, scale=(size, 0.05, 0.55),
                        position=((x * S) + math.cos(a) * size / 2, 0.1, (y * S) + math.sin(a) * size / 2),
                        rotation_y=-a_deg))
    arrows.append((parts, phase))


# Three arrows pointing up toward the top rollover lanes.
for _k, _xx in enumerate((CX - 45, CX, CX + 45)):
    add_arrow(_xx, 262, 90, _k * 0.12)
# Three arrows per side along the lower guide rails, pointing toward the
# flippers (-28 degrees on the left; mirror image, 208 degrees, on the right).
for _k, _t in enumerate((0.28, 0.5, 0.72)):
    _gx = -180 + 76 * _t
    _gy = -174 - 40 * _t + 24
    add_arrow(_gx, _gy, -28, _k * 0.12)
    add_arrow(-34 - _gx, _gy, 208, _k * 0.12)

# Faint glass reflections lying over the playfield: two very transparent long
# flat strips rotated 25 degrees about the vertical axis.
soft(mk(model='cube', color=color.hsv(200, 0.1, 1, 0.045), scale=(7, 0.01, 70), position=(-6, 3.6, 1), rotation_y=25))
soft(mk(model='cube', color=color.hsv(200, 0.1, 1, 0.03), scale=(3, 0.01, 70), position=(8, 3.65, 1), rotation_y=25))

# --------------------------------------------------------------------------
# Walls
# --------------------------------------------------------------------------
# Outer boundary.  The left wall stops at y = -174 where the lower guide rail
# begins.
add_wall((-180, -174), (-180, 170), mat='wood')       # left wall
add_wall((180, -300), (180, 170), mat='wood')         # plunger-lane outer wall
add_wall((146, -300), (146, 150), mat='wood')         # lane inner wall stops at y=150 -> wide exit
add_wall((146, -300), (180, -300), mat='wood', led_step=0)   # lane floor (no LEDs)

# Top arch: a semicircle of radius 180 centred at (0, 170), approximated by 32
# straight segments for i = 0..32 at angles 0..180 degrees.  Lower friction is
# not needed here; the wood material is used.
ARCH_N = 32                                           # top arch  r=180 @ (0,170)
arch = [(180 * math.cos(math.radians(180 * i / ARCH_N)),
         170 + 180 * math.sin(math.radians(180 * i / ARCH_N))) for i in range(ARCH_N + 1)]
for i in range(ARCH_N):
    add_wall(arch[i], arch[i + 1], mat='wood', led_step=90)

# Lower guide rails funnel the ball to the lower flippers.  Slope =
# atan(40 / 76) = 27.8 degrees, close to the real 25-30 degree guide angle.
# Lower guide rails at the realistic ~28 deg angle (atan(40/76) = 27.8 deg)
add_wall((-180, -174), (-104, -214))
add_wall((146, -174), (70, -214))
# Upper-stage ledges (slope atan(40/42) = 43.6 degrees) deliver the ball to the
# upper flippers.
# Upper-stage ledges
add_wall((-180, 78), (-138, 38), led_step=30)
add_wall((146, 78), (104, 38), led_step=30)

# One-way gate: a physics segment that is NOT added to the space yet.  It spans
# the lane exit (x = 146, y 150..280).  set_gate(True) adds it; its visual
# (a red bar) is hidden until then.
# one-way gate at the lane exit
gate = pymunk.Segment(space.static_body, (146, 150), (146, 280), 3)
gate.elasticity, gate.friction = MAT['wood']
gate_vis = seg_visual((146, 150), (146, 280), 6, 2.2, color.hsv(355, 0.9, 0.95))
gate_vis.enabled = False

# Chase lights up the plunger lane: 9 bulbs at x = 163, y = -250..110 step 45;
# phase i/9 makes a bright spot travel upward twice per second.
for i, y in enumerate(range(-250, 140, 45)):          # plunger-lane chase lights
    add_led(163, y, h=0.3, size=0.6, kind='chase', phase=i / 9.0)
# Row of 12 rainbow bulbs along the drain at y = -300.
for i, x in enumerate(range(-150, 145, 26)):          # drain row
    add_led(x, -300, h=0.3, size=0.5, kind='cycle', phase=i * 25)

# Four rubber posts: (x, y, hue) at the sides of the field.
# rubber posts
for (px_, py_, hue) in [(-150, -30, 215), (116, -30, 215), (-165, 118, 330), (131, 118, 190)]:
    add_post(px_, py_, 5, hue)

# Top rollover lanes: three sensors at y = 300 spaced 45 units apart around
# CX.  Four steel divider rails (radius 3, 30 units tall in y: 283..313) at
# CX +/- 22.5 and CX +/- 67.5 separate the lanes; each divider gets a bulb on
# top.  Lane lamps are flat discs coloured in update() (yellow when lit).
# Top rollover lanes (3 lanes, light all three for bonus multiplier)
LANES = [(CX - 45, 300), (CX, 300), (CX + 45, 300)]
for dx in (-67.5, -22.5, 22.5, 67.5):
    a, b = (CX + dx, 283), (CX + dx, 313)
    add_wall(a, b, r=3, mat='steel', height=1.8, led_step=0)
    add_led(CX + dx, 313, h=2.4, size=0.5, kind='cycle', phase=dx * 3)
lane_vis = []
for (lx, ly) in LANES:
    lane_vis.append(mk(model='sphere', color=color.white, scale=(2.6, 0.08, 2.6), position=(lx * S, 0.08, ly * S)))

# --------------------------------------------------------------------------
# Ball
# --------------------------------------------------------------------------
# Pymunk ball.  Mass is an arbitrary 1.0 (only ratios matter in this world);
# the moment of inertia is that of a solid SPHERE: 2/5 m r^2 = 40.
BALL_MASS_UNITS = 1.0
ball_body = pymunk.Body(BALL_MASS_UNITS, 0.4 * BALL_MASS_UNITS * BALL_R ** 2)   # solid sphere I = 2/5 m r^2
# Initial position: middle of the plunger lane (x between 150 and 176), a bit
# above the lane floor (whose top is at y = -296, so the ball rests at y = -286).
ball_body.position = (163, -284)
ball_shape = pymunk.Circle(ball_body, BALL_R)
ball_shape.elasticity = 0.85     # steel ball restitution (combined with the other shape)
ball_shape.friction = 0.5
space.add(ball_body, ball_shape)

# Visual ball: a pale blue-silver sphere, diameter BALL_R*2*S = 2 world units.
visual_ball = mk(model='sphere', color=color.hsv(212, 0.10, 0.92), scale=BALL_R * 2 * S)
# Rolling markers: 8 unit vectors pointing to the corners of a cube (each
# divided by sqrt(3)).  roll_ball() rotates these vectors every frame and
# roll_dots (small spheres, children of the ball) are placed at 0.5 * vector,
# i.e. on the surface of the unit sphere model.
roll_vecs = []
roll_dots = []
_n = math.sqrt(3)
for sx in (-1, 1):
    for sy in (-1, 1):
        for sz in (-1, 1):
            roll_vecs.append([sx / _n, sy / _n, sz / _n])
for i, v in enumerate(roll_vecs):
    # alternate blue (215) and red (350) dots
    roll_dots.append(mk(parent=visual_ball, model='sphere', scale=0.17,
                        color=color.hsv(215 if i % 2 else 350, 0.7, 0.45),
                        position=(v[0] * 0.5, v[1] * 0.5, v[2] * 0.5)))
# Static white specular highlight (does not rotate with the ball).
mk(parent=visual_ball, model='sphere', color=color.white, scale=0.22, position=(-0.18, 0.40, -0.18))   # specular
# Soft two-layer shadow under the ball: a darker core (alpha 0.42) and a wider,
# fainter halo (alpha 0.16), both flat translucent discs offset slightly to the
# lower right in update().
ball_shadow = soft(mk(model='sphere', color=color.hsv(260, 0.8, 0.05, 0.42), scale=(2.2, 0.02, 2.2), position=(0, 0.12, 0)))
ball_shadow2 = soft(mk(model='sphere', color=color.hsv(260, 0.8, 0.05, 0.16), scale=(3.0, 0.02, 3.0), position=(0, 0.11, 0)))
# Subtle trail: TRAIL_N flat, very transparent discs re-positioned along the
# ball's recent path; their size and alpha shrink toward the tail and the
# whole trail fades out at low speed (see update()).
TRAIL_N = 12
trail = [soft(mk(model='sphere', color=color.hsv(210, 0.35, 0.9, 0.1), scale=(0.5, 0.03, 0.5))) for _ in range(TRAIL_N)]

# Plunger visuals in the lane (x = 16.3 world units): chrome cap just under the
# ball, a grey rod and a red knob.  update() moves their z by the pull amount.
plunger_cap = mk(model='cube', color=CHROME, scale=(2.4, 0.9, 0.7), position=(163 * S, 0.5, -29.9))
plunger_rod = mk(model='cube', color=color.hsv(0, 0, 0.5), scale=(0.9, 0.7, 5), position=(163 * S, 0.5, -32.5))
plunger_knob = mk(model='sphere', color=color.hsv(0, 0.85, 0.85), scale=(1.8, 1.8, 1.8), position=(163 * S, 0.6, -35.5))

# spring plunger physics
PLUNGER_K = 250.0           # N/m    spring stiffness
PLUNGER_M = 0.120           # kg     moving plunger mass
PULL_MAX_M = 0.070          # m      maximum pull (70 mm)


def plunger_ball_speed(frac):
    """Launch speed (m/s) of the ball for a plunger pulled back by `frac` (0..1).

    Physics (module docstring 6.6):
        d   = frac * PULL_MAX_M                       pull distance in metres
        v_p = d * sqrt(k / M)                         spring energy 1/2 k d^2 -> 1/2 M v_p^2
        v   = 2 M / (M + m) * v_p                     elastic collision, ball at rest
    where k = PLUNGER_K, M = PLUNGER_M, m = BALL_MASS_KG.  Friction and the
    slight gravity effect during the stroke are ignored.

    Examples: frac 0.28 -> 1.07 m/s (just reaches the arch), 1.0 -> 3.82 m/s.
    Parameters:
        frac : pull fraction (the caller guarantees >= 0.05).
    Returns:
        ball speed in m/s along +y (up the lane).
    """
    d = frac * PULL_MAX_M
    vp = d * math.sqrt(PLUNGER_K / PLUNGER_M)                 # plunger speed at the ball (from 1/2 k d^2)
    return 2 * PLUNGER_M / (PLUNGER_M + BALL_MASS_KG) * vp    # elastic collision, ball at rest


# --------------------------------------------------------------------------
# Sparks
# --------------------------------------------------------------------------
# Particle pool of 48 small spheres, created once and hidden.  Each record:
# e (Entity), vx/vy/vz (table-local world units per second), life (remaining
# seconds, <= 0 means free) and mx (initial life, used for shrinking).
sparks = []
for _ in range(48):
    e = mk(model='sphere', scale=0.3, color=color.white)
    e.enabled = False
    sparks.append(dict(e=e, vx=0, vy=0, vz=0, life=0.0, mx=0.5))


def spawn_sparks(x, y, hue, n=9):
    """Emit up to n sparks at playfield position (x, y) in a given hue.

    Takes the first n FREE particles (life <= 0) from the pool; if fewer are
    free, fewer are emitted.  Each gets:
        life = mx = uniform(0.35, 0.75) s
        vx, vz = uniform(-10, 10) world units/s (sideways), vy = uniform(4, 11) (up)
        start height 1.3, hue = hue + uniform(-35, 35) degrees.
    The motion itself (gravity, bounce, shrinking) is integrated in update().

    Parameters:
        x, y : emission point (physics units).
        hue  : base hue in degrees.
        n    : number of sparks wanted.
    """
    k = 0
    for s in sparks:
        if s['life'] <= 0:
            s['life'] = s['mx'] = random.uniform(0.35, 0.75)
            s['vx'], s['vz'], s['vy'] = random.uniform(-10, 10), random.uniform(-10, 10), random.uniform(4, 11)
            s['e'].position = (x * S, 1.3, y * S)
            s['e'].color = color.hsv((hue + random.uniform(-35, 35)) % 360, 0.8, 1)
            s['e'].enabled = True
            k += 1
            if k >= n:
                break


# --------------------------------------------------------------------------
# Pop bumpers & slingshots (solenoid kickers)
# --------------------------------------------------------------------------
# Kick speeds in physics units/s (1.8 m/s = 1333 and 1.5 m/s = 1111 units/s).
BUMPER_KICK = ms_to_units(1.8)
SLING_KICK = ms_to_units(1.5)
# Four pop bumpers: (x, y, hue).  Each has a physical ring of radius 20
# (so the ball also bounces off it physically) AND an analytic kick applied
# in post_step().  Visual layers (bottom to top): dark base disc, coloured
# skirt, domed cap, white highlight, and 12 LEDs on a circle of radius 26.
bumpers = []
for (bx_, by_, hue) in [(-77, 140, 330), (43, 140, 190), (-17, 200, 50), (-17, 85, 120)]:
    shp = pymunk.Circle(space.static_body, 20, (bx_, by_))
    shp.elasticity, shp.friction = MAT['bumper']
    space.add(shp)
    mk(model='sphere', color=color.hsv(hue, 0.7, 0.18), scale=(5.8, 0.2, 5.8), position=(bx_ * S, 0.12, by_ * S))
    skirt = mk(model='sphere', color=color.hsv(hue, 0.8, 0.55), scale=(4.9, 1.0, 4.9), position=(bx_ * S, 0.4, by_ * S))
    cap = mk(model='sphere', color=color.hsv(hue, 0.9, 0.95), scale=(3.8, 2.4, 3.8), position=(bx_ * S, 1.0, by_ * S))
    mk(model='sphere', color=color.white, scale=(0.9, 0.5, 0.9), position=((bx_ - 6) * S, 2.0, (by_ - 6) * S))
    ring_leds = []
    for k in range(12):
        a = math.radians(k * 30)
        ring_leds.append(mk(model='sphere', scale=0.42, color=color.white,
                            position=((bx_ + 26 * math.cos(a)) * S, 0.5, (by_ + 26 * math.sin(a)) * S)))
    bumpers.append(dict(x=bx_, y=by_, r=20, hue=hue, cap=cap, skirt=skirt, leds=ring_leds, flash=0.0, cool=0.0))

# Two slingshots above the lower flippers: (rail end a, rail end b, front normal).
# `front` is a unit vector pointing into the playfield; it is the direction of
# the kick.  Left rail (-140,-105)->(-118,-160), normal (0.93, 0.37); right rail
# is its mirror image about x = CX.  Physics: static segment radius 5 of
# rubber.  Visual: dark orange body and a thin bright cap (recoloured in update()).
slings = []
for (a, b, front) in [((-140, -105), (-118, -160), (0.93, 0.37)),
                      ((106, -105), (84, -160), (-0.93, 0.37))]:
    shp = pymunk.Segment(space.static_body, a, b, 5)
    shp.elasticity, shp.friction = MAT['rubber']
    space.add(shp)
    seg_visual(a, b, 10, 1.8, color.hsv(18, 0.9, 0.55), extra=5)
    cap_v = seg_visual(a, b, 7, 0.4, color.hsv(40, 0.9, 1), y0=1.8, extra=5)
    slings.append(dict(a=a, b=b, front=front, vis=cap_v, flash=0.0, cool=0.0))

# --------------------------------------------------------------------------
# Flippers (60 deg swing, fast up, slower spring return)
# --------------------------------------------------------------------------
FLIP_UP_SPEED = 32.0        # rad/s  (solenoid)
FLIP_DOWN_SPEED = 14.0      # rad/s  (return spring)
flippers = []


def make_flipper(px, py, length, radius, side, rest_deg, up_deg, hue):
    """Create one flipper (physics body + 3D model) and register it.

    Physics: a KINEMATIC pymunk body at the pivot (px, py) carrying a Segment
    from the pivot to (+/-length, 0) in the body's local frame with rounded
    ends of the given radius.  `side` 'L' means the blade extends toward +x
    (left-hand flipper, pivot at its left end); 'R' extends toward -x.  The
    shape uses MAT['flipper'].  The body starts at the rest angle.

    Visual: an invisible `pivot` Entity at the pivot point (height 1.0) with
    children: a body box, a lighter top strip, a round tip sphere, a tip
    highlight and a white pivot bolt.  update() sets pivot.rotation_y.

    Parameters:
        px, py   : pivot position (physics units).
        length   : pivot-to-tip distance of the blade centre line (units).
        radius   : blade half-thickness (units).
        side     : 'L' or 'R'.
        rest_deg : angle (degrees) when idle (left: -28, right: +28).
        up_deg   : angle (degrees) when raised (left: +32, right: -32).
        hue      : colour hue (10 = orange-red lower stage, 195 = cyan upper).
    Appends dict(body, pivot, side, active=False, rest, up) (angles in radians)
    to `flippers`.
    """
    body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
    body.position = (px, py)
    dirx = 1 if side == 'L' else -1
    shape = pymunk.Segment(body, (0, 0), (dirx * length, 0), radius)
    shape.elasticity, shape.friction = MAT['flipper']
    body.angle = math.radians(rest_deg)
    space.add(body, shape)
    pivot = mk(position=(px * S, 1.0, py * S))
    mid = dirx * length / 2 * S
    mk(parent=pivot, model='cube', color=color.hsv(hue, 0.85, 0.65), scale=(length * S, 1.3, radius * 2 * S), position=(mid, 0, 0))
    mk(parent=pivot, model='cube', color=color.hsv(hue, 0.5, 1), scale=(length * S, 0.2, radius * 1.0 * S), position=(mid, 0.7, 0))
    mk(parent=pivot, model='sphere', color=color.hsv(hue, 0.85, 0.65), scale=(radius * 2 * S, 1.3, radius * 2 * S), position=(dirx * length * S, 0, 0))
    mk(parent=pivot, model='sphere', color=color.hsv(hue, 0.5, 1), scale=(radius * 1.0 * S, 0.3, radius * 1.0 * S), position=(dirx * length * S, 0.7, 0))
    mk(parent=pivot, model='sphere', color=color.hsv(0, 0, 0.95), scale=(radius * 1.3 * S, 0.5, radius * 1.3 * S), position=(0, 0.75, 0))
    flippers.append(dict(body=body, pivot=pivot, side=side, active=False,
                         rest=math.radians(rest_deg), up=math.radians(up_deg)))


# Four flippers: the LOWER stage (long, orange) guards the drain; the UPPER
# stage (shorter, cyan) sits mid-field on the ledges.  Pivots are placed
# symmetrically about the field centre line CX.
make_flipper(CX - 78, -225, 62, 9, 'L', -28, 32, 10)    # lower stage
make_flipper(CX + 78, -225, 62, 9, 'R', 28, -32, 10)
make_flipper(CX - 113, 30, 50, 7, 'L', -28, 32, 195)    # upper stage
make_flipper(CX + 113, 30, 50, 7, 'R', 28, -32, 195)

# --------------------------------------------------------------------------
# Upper-left corner: orbit ring + 3 bonus holes
# --------------------------------------------------------------------------
# Ring geometry: centre RING_C, radius RING_R.  It is approximated by RING_N = 32
# segments of 11.25 degrees; those whose middle angle lies within GAP_HALF
# (70 degrees) of GAP_CENTER (-25 degrees, i.e. pointing right and slightly
# down) are omitted, leaving a 140-degree opening (-95..45 deg) facing the
# playfield.  The remaining 20 segments are static steel colliders (radius 2.5)
# with a purple body and a neon cap (registered in ring_vis).
RING_C = (-112, 226)
RING_R = 46
GAP_CENTER = -25
GAP_HALF = 70
RING_N = 32
ring_vis = []
for i in range(RING_N):
    a0 = i * 360 / RING_N
    a1 = (i + 1) * 360 / RING_N
    mid = (a0 + a1) / 2
    # angular distance from the gap centre, wrapped to -180..180
    if abs(((mid - GAP_CENTER + 180) % 360) - 180) <= GAP_HALF:
        continue
    p0 = (RING_C[0] + RING_R * math.cos(math.radians(a0)), RING_C[1] + RING_R * math.sin(math.radians(a0)))
    p1 = (RING_C[0] + RING_R * math.cos(math.radians(a1)), RING_C[1] + RING_R * math.sin(math.radians(a1)))
    shp = pymunk.Segment(space.static_body, p0, p1, 2.5)
    shp.elasticity, shp.friction = MAT['steel']
    space.add(shp)
    seg_visual(p0, p1, 5, 1.4, color.hsv(270, 0.8, 0.35), extra=2)
    ring_vis.append(seg_visual(p0, p1, 6, 0.4, color.white, y0=1.4, extra=2))
# Rubber end-posts (radius 4) capping the two ends of the ring so the ball does
# not catch on the bare segment ends, plus a gold sphere on each.
for ang in (GAP_CENTER - GAP_HALF, GAP_CENTER + GAP_HALF):
    px_ = RING_C[0] + RING_R * math.cos(math.radians(ang))
    py_ = RING_C[1] + RING_R * math.sin(math.radians(ang))
    post = pymunk.Circle(space.static_body, 4, (px_, py_))
    post.elasticity, post.friction = MAT['rubber']
    space.add(post)
    mk(model='sphere', color=color.hsv(50, 0.9, 1), scale=1.1, position=(px_ * S, 1.0, py_ * S))
# Two flat glowing discs painted inside the ring (outer purple, inner magenta).
mk(model='sphere', color=color.hsv(270, 0.75, 0.30), scale=(RING_R * 2 * S, 0.03, RING_R * 2 * S), position=(RING_C[0] * S, 0.05, RING_C[1] * S))
mk(model='sphere', color=color.hsv(300, 0.8, 0.40), scale=(RING_R * 1.3 * S, 0.03, RING_R * 1.3 * S), position=(RING_C[0] * S, 0.06, RING_C[1] * S))

# Three bonus holes at radius 24 from the ring centre at angles 135, 15, 250
# degrees.  Holes are NOT physical objects: they are detected in pre_step /
# post_step by distance.  Visual: outer glow disc, coloured rim, black pit.
holes = []
for ang in (135, 15, 250):
    hx = RING_C[0] + 24 * math.cos(math.radians(ang))
    hy = RING_C[1] + 24 * math.sin(math.radians(ang))
    glow = mk(model='sphere', color=color.hsv(300, 0.9, 0.5), scale=(4.2, 0.05, 4.2), position=(hx * S, 0.08, hy * S))
    rim = mk(model='sphere', color=color.hsv(300, 0.9, 0.9), scale=(3.0, 0.08, 3.0), position=(hx * S, 0.1, hy * S))
    mk(model='sphere', color=color.black, scale=(2.1, 0.1, 2.1), position=(hx * S, 0.14, hy * S))
    holes.append(dict(x=hx, y=hy, rim=rim, glow=glow))

# --------------------------------------------------------------------------
# 'TILT' lettering on the playfield (pixel font, hidden until a tilt)
# --------------------------------------------------------------------------
# 3-column x 5-row bitmap font for the letters T, I, L ('1' = lit pixel).
TILT_FONT = {'T': ['111', '010', '010', '010', '010'],
             'I': ['111', '010', '010', '010', '111'],
             'L': ['100', '100', '100', '100', '111']}
# Build one flat cube per lit pixel (30 in total).  Each pixel is
# PIX = 9 physics units; letters are 4 columns apart (3 + 1 gap), so the word is
# (4*4 - 1) * 9 = 135 units wide, centred on CX (the _x0 formula gives the
# centre of the first pixel).  Row r = 0 is the top row at y = 10 + 2*9 = 28,
# row 4 the bottom at y = -8.  The pixels lie on the board at height 0.16
# (below the ball) and start hidden.  tilt_px holds (entity, colour phase) with
# phase = letter*40 + row*25 + column*15.
tilt_px = []
PIX = 9
_word = 'TILT'
_x0 = CX - (len(_word) * 4 - 1) * PIX / 2 + PIX / 2
for li, ch in enumerate(_word):
    for r, row in enumerate(TILT_FONT[ch]):
        for c, bit in enumerate(row):
            if bit == '1':
                e = mk(model='cube', color=color.white, scale=(PIX * S * 0.9, 0.15, PIX * S * 0.9),
                       position=((_x0 + (li * 4 + c) * PIX) * S, 0.16, (10 + (2 - r) * PIX) * S))
                e.enabled = False
                tilt_px.append((e, li * 40 + r * 25 + c * 15))

# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------
# Screen-space texts.  Positions are in Ursina UI units (window.top_left etc.
# are the screen corners; origin selects which part of the text is anchored).
# Title at the top centre.
Text(text='P I N B A L L', position=(0, 0.47), origin=(0, 0), scale=2.2, color=color.hsv(300, 0.8, 1))
# Score (top left), physics read-out below it (cyan, small), ball/bonus/hole
# info (top right) and a big centred message line.
score_text = Text(text='', position=window.top_left + Vec2(0.02, -0.02), origin=(-.5, .5), scale=1.8, color=color.white)
phys_text = Text(text='', position=window.top_left + Vec2(0.02, -0.085), origin=(-.5, .5), scale=1.0, color=color.cyan)
info_text = Text(text='', position=window.top_right + Vec2(-0.02, -0.02), origin=(.5, .5), scale=1.4, color=color.yellow)
msg_text = Text(text='', origin=(0, 0), position=(0, 0.3), scale=2.6, color=color.orange)
# Key help line at the bottom left.
Text(text='Arrows/A/D/Shift/Ctrl flippers  SPACE plunger / NUDGE  UP/DOWN table angle  C camera  R restart',
     position=window.bottom_left + Vec2(0.02, 0.04), origin=(-.5, -.5), scale=1.0, color=color.light_gray)
# Right-hand bar: plunger charge.  A grey background quad plus a fill quad
# whose origin is its bottom (origin_y=-.5) so scaling y grows it upward.
Entity(parent=camera.ui, model='quad', color=color.dark_gray, scale=(0.03, 0.3), position=(0.8, -0.1))
bar_fill = Entity(parent=camera.ui, model='quad', color=color.lime, origin_y=-.5, scale=(0.026, 0.0), position=(0.8, -0.25))
# Left-hand bar: tilt (nudge) meter, built the same way, with a label.
Entity(parent=camera.ui, model='quad', color=color.dark_gray, scale=(0.03, 0.3), position=(-0.8, -0.1))
meter_fill = Entity(parent=camera.ui, model='quad', color=color.lime, origin_y=-.5, scale=(0.026, 0.0), position=(-0.8, -0.25))
Text(text='NUDGE', position=(-0.8, -0.27), origin=(0, 0), scale=0.9, color=color.light_gray)
# Cache of the last strings written to the HUD Texts.  Re-assigning Text.text
# rebuilds its geometry, so update() only does it when the string changed.
_last = {'score': None, 'info': None, 'phys': None, 'music': None}

# --------------------------------------------------------------------------
# Music (module docstring section 14)
# --------------------------------------------------------------------------
def find_audio_dir():
    '''Locate the audio folder ("<game root>/audio", i.e. .\\audio next to this script).

    Candidates, in order: <folder of this script>/audio, <current working
    directory>/audio.  The first one that exists is returned; if none exists the
    first candidate path is returned (MusicPlayer.scan() then creates it).
    '''
    here = os.path.dirname(os.path.abspath(__file__))
    for base_dir in (here, os.getcwd()):
        p = os.path.join(base_dir, 'audio')
        if os.path.isdir(p):
            return p
    return os.path.join(here, 'audio')


class MusicPlayer:
    '''Looping music player with a track list read from the audio folder.

    Attributes:
        folder   : directory that is scanned.
        tracks   : list of (display name without extension, full path), sorted.
        index    : index of the loaded track, -1 if none.
        cursor   : highlighted entry of the menu.
        volume   : 0.0 .. 1.0 (starts at 0.6).
        sound    : Panda3D AudioSound while backend == 'panda'.
        backend  : None, 'panda' or 'pygame'.
        playing  : True while a track is supposed to be playing (looping).
        error    : text of the last failure ('' if none), shown in the menu.
    Back-ends: see module docstring section 14.
    '''
    EXTS = ('.mp3', '.ogg', '.wav')

    def __init__(self, folder):
        self.folder = folder
        self.tracks = []
        self.index = -1
        self.cursor = 0
        self.volume = 0.6
        self.sound = None
        self.backend = None
        self.playing = False
        self.error = ''
        self._acc = 0.0
        self.scan()

    def scan(self):
        '''(Re)read the audio folder.

        Creates the folder if it is missing, lists files with a supported
        extension (case-insensitive, sorted by lower-case name) and rebuilds
        `tracks`.  If a track is playing and still present, `index` follows it to
        its new position; if it disappeared, playback is stopped.  The menu
        cursor is clamped into range.  A failure to access the folder is stored
        in `error`.
        '''
        current = self.tracks[self.index][1] if 0 <= self.index < len(self.tracks) else None
        try:
            os.makedirs(self.folder, exist_ok=True)
            names = sorted((f for f in os.listdir(self.folder) if f.lower().endswith(self.EXTS)), key=str.lower)
        except OSError as exc:
            names = []
            self.error = f'audio folder unavailable: {exc}'
        self.tracks = [(os.path.splitext(f)[0], os.path.join(self.folder, f)) for f in names]
        paths = [p for _n, p in self.tracks]
        if current in paths:
            self.index = paths.index(current)
        else:
            if self.playing:
                self.stop()
            self.index = -1
        self.cursor = max(0, min(self.cursor, len(self.tracks) - 1))

    def play(self, i):
        '''Load track number i and start it looping.  Returns True on success.

        Stops whatever is playing, then tries the Panda3D back-end (decode the
        whole file with base.loader.loadSfx; success means the sound is longer
        than 0.5 s), and if that fails the pygame back-end (mixer.music.load +
        play(-1)).  On success sets index/cursor, backend, playing.  If both fail
        `error` explains why (and what to try) and False is returned.  An index
        outside the list does nothing.
        '''
        if not 0 <= i < len(self.tracks):
            return False
        self.stop()
        name, path = self.tracks[i]
        self.index = i
        self.cursor = i
        self.error = ''
        errors = []
        if Filename is not None:
            try:
                snd = base.loader.loadSfx(Filename.from_os_specific(path))
                if snd is not None and snd.length() > 0.5:
                    snd.setLoop(True)
                    snd.setVolume(self.volume)
                    snd.play()
                    self.sound = snd
                    self.backend = 'panda'
                    self.playing = True
                    return True
                errors.append('Panda3D could not decode it')
            except Exception as exc:
                errors.append(f'Panda3D: {exc}')
        try:
            import pygame
            pygame.mixer.init()
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(self.volume)
            pygame.mixer.music.play(-1)
            self.backend = 'pygame'
            self.playing = True
            return True
        except Exception as exc:
            errors.append(f'pygame: {exc}')
        self.error = f'Cannot play {name[:30]} ({"; ".join(errors)[:70]}). Try .ogg/.wav or pip install pygame'
        return False

    def stop(self):
        '''Stop playback on whichever back-end is active and clear the handles.

        `index` is kept so the menu still shows the last track.
        '''
        if self.backend == 'panda' and self.sound is not None:
            try:
                self.sound.stop()
            except Exception:
                pass
        elif self.backend == 'pygame':
            try:
                import pygame
                pygame.mixer.music.stop()
            except Exception:
                pass
        self.sound = None
        self.backend = None
        self.playing = False

    def set_volume(self, v):
        '''Set the volume (clamped to 0..1, rounded to 2 decimals) on the active back-end.'''
        self.volume = round(max(0.0, min(1.0, v)), 2)
        try:
            if self.backend == 'panda' and self.sound is not None:
                self.sound.setVolume(self.volume)
            elif self.backend == 'pygame':
                import pygame
                pygame.mixer.music.set_volume(self.volume)
        except Exception:
            pass

    def next(self):
        '''Play the track after the current one (wraps around; starts at 0 if none).'''
        if not self.tracks:
            return False
        return self.play((self.index + 1) % len(self.tracks))

    def tick(self, dt):
        '''Looping safety net; call every frame.

        Accumulates time and, every 0.5 s, checks whether a track that should be
        playing has stopped (Panda: status() != PLAYING; pygame: not get_busy())
        and restarts it.  Does nothing when nothing should be playing.
        '''
        self._acc += dt
        if self._acc < 0.5:
            return
        self._acc = 0.0
        if not self.playing:
            return
        try:
            if self.backend == 'panda' and self.sound is not None:
                playing_const = AudioSound.PLAYING if AudioSound is not None else 2
                if self.sound.status() != playing_const:
                    self.sound.play()
            elif self.backend == 'pygame':
                import pygame
                if not pygame.mixer.music.get_busy():
                    pygame.mixer.music.play(-1)
        except Exception:
            pass

    def hud_text(self):
        '''One-line description for the bottom-right HUD text.'''
        if self.playing and 0 <= self.index < len(self.tracks):
            return f'MUSIC: {self.tracks[self.index][0][:40]}   (M menu, N next)'
        if not self.tracks:
            return 'MUSIC: put .mp3/.ogg/.wav files in the audio folder   (M menu)'
        return 'MUSIC: stopped   (M menu)'


music = MusicPlayer(find_audio_dir())

# HUD line (bottom right) and the music MENU overlay.  The overlay consists of
# a translucent panel in front of everything (z = -0.5), a title, MENU_LINES
# track lines, a status line and a help line (z = -1, in front of the panel).
music_text = Text(text='', position=window.bottom_right + Vec2(-0.02, 0.04), origin=(.5, -.5), scale=1.0,
                  color=color.hsv(180, 0.5, 1))
MENU_LINES = 10
menu_panel = Entity(parent=camera.ui, model='quad', color=color.hsv(250, 0.7, 0.06, 0.94), scale=(1.1, 0.82), z=-0.5)
menu_title = Text(text='MUSIC MENU', position=(0, 0.34, -1), origin=(0, 0), scale=2.0, color=color.hsv(300, 0.8, 1))
menu_lines = [Text(text='', position=(-0.5, 0.25 - i * 0.045, -1), origin=(-.5, 0), scale=1.15) for i in range(MENU_LINES)]
menu_status = Text(text='', position=(0, -0.28, -1), origin=(0, 0), scale=1.0, color=color.yellow)
menu_help = Text(text='UP/DOWN select  ENTER play  1-9 quick play  LEFT/RIGHT volume  S stop  F5 rescan  M/ESC close',
                 position=(0, -0.34, -1), origin=(0, 0), scale=0.85, color=color.light_gray)
_menu_items = [menu_panel, menu_title, menu_status, menu_help] + menu_lines
for _e in _menu_items:
    _e.enabled = False
_menu_cache = {}


def music_autostart():
    '''Start the first track of the audio folder (if any) when the game starts.'''
    if music.tracks:
        music.play(0)


def show_menu(on):
    '''Open or close the music menu.

    Sets st.menu_open, shows/hides every menu element, and when opening rescans
    the folder and puts the cursor on the playing track.  While the menu is open
    update() freezes the game and only draws the menu.
    '''
    st.menu_open = on
    for e in _menu_items:
        e.enabled = on
    if on:
        music.scan()
        if music.index >= 0:
            music.cursor = music.index
        _menu_cache.clear()
        draw_menu()


def draw_menu():
    '''Refresh the text of the menu lines (only those whose text changed).

    Shows up to MENU_LINES tracks, scrolled so the cursor stays visible: '>'
    marks the cursor, '[PLAYING]' the current track; the cursor line is yellow,
    the playing one green.  An empty folder shows instructions and the folder
    path.  The status line shows volume, track count and the last error.
    Re-assigning Text.text rebuilds its geometry, so a cache avoids needless work.
    '''
    n = len(music.tracks)
    top = 0 if n <= MENU_LINES else max(0, min(music.cursor - MENU_LINES // 2, n - MENU_LINES))
    texts = []
    cols = []
    for k in range(MENU_LINES):
        i = top + k
        if i < n:
            playing = (i == music.index and music.playing)
            texts.append(f"{'>' if i == music.cursor else ' '} {i + 1:2d}. {music.tracks[i][0][:44]}{'  [PLAYING]' if playing else ''}")
            cols.append(color.yellow if i == music.cursor else (color.lime if playing else color.light_gray))
        else:
            texts.append('')
            cols.append(color.light_gray)
    if n == 0:
        texts[0] = 'No tracks found. Put .mp3 / .ogg / .wav files in the folder:'
        texts[1] = music.folder[-60:]
        cols[0] = cols[1] = color.orange
    texts.append(f'Volume {int(music.volume * 100)}%   Tracks {n}   {music.error}'[:110])
    for k, line in enumerate(menu_lines):
        if _menu_cache.get(k) != texts[k]:
            line.text = texts[k]
            line.color = cols[k]
            _menu_cache[k] = texts[k]
    if _menu_cache.get('status') != texts[-1]:
        menu_status.text = texts[-1]
        _menu_cache['status'] = texts[-1]
    for k, line in enumerate(menu_lines):
        line.color = cols[k]


def menu_key(key):
    '''Handle one key press while the menu is open (called from input()).

    m / escape : close;  up / down arrow : move the cursor (wraps);
    enter : play the highlighted track;  1..9 : play that track directly;
    left / right arrow : volume -/+ 10 %;  s : stop the music;  f5 : rescan.
    '''
    n = len(music.tracks)
    if key in ('m', 'escape'):
        show_menu(False)
    elif key == 'up arrow' and n:
        music.cursor = (music.cursor - 1) % n
    elif key == 'down arrow' and n:
        music.cursor = (music.cursor + 1) % n
    elif key in ('enter', 'return') and n:
        music.play(music.cursor)
    elif key == 'left arrow':
        music.set_volume(music.volume - 0.1)
    elif key == 'right arrow':
        music.set_volume(music.volume + 0.1)
    elif key == 's':
        music.stop()
    elif key == 'f5':
        music.scan()
    elif len(key) == 1 and key in '123456789':
        idx = int(key) - 1
        if idx < n:
            music.cursor = idx
            music.play(idx)
    _menu_cache.clear()
    draw_menu()


def show_msg(text, dur=2.0, col=color.orange):
    """Show a big centred message for `dur` seconds.

    Sets msg_text.text / colour and arms st.msg_t; update() decrements st.msg_t
    and clears the text at zero.  A message with dur=999 is effectively
    permanent (used for GAME OVER).  Note that while st.tilted is True (and the
    game is not over) the per-frame tilt block overwrites the text with 'TILT'.

    Parameters:
        text : string to display.
        dur  : seconds to keep it.
        col  : Ursina colour.
    """
    msg_text.text = text
    msg_text.color = col
    st.msg_t = dur


def set_gate(on):
    """Open or close the one-way gate at the plunger-lane exit.

    on = True : add the static `gate` segment to the physics space (if not
                already there) and show its red visual; st.gate_on = True.
    on = False: remove it from the space and hide the visual.
    Idempotent: calling with the current state does nothing.  Called from
    post_step() (close, once the ball is in the field) and respawn_ball() (open).
    Must not be called from inside a pymunk callback; it is always called between
    space.step() calls here.
    """
    if on and not st.gate_on:
        space.add(gate)
        st.gate_on = True
        gate_vis.enabled = True
    elif not on and st.gate_on:
        space.remove(gate)
        st.gate_on = False
        gate_vis.enabled = False


def respawn_ball():
    """Put a fresh ball in the plunger lane and reset the per-ball state.

    * opens the gate;
    * places the ball body at (163, -284) with zero linear and angular velocity;
    * phase -> 'plunger'; plunger charge 0; no hole capture; ring flag cleared;
      stuck timer, trail history and the tilt METER cleared (the tilted FLAG is
      deliberately NOT cleared: it ends at the next launch);
    * makes the ball visible again.
    Called by reset_game(), drain() (balls left) and by post_step() when the ball
    leaves the table area without draining.
    """
    set_gate(False)
    ball_body.position = (163, -284)
    ball_body.velocity = (0, 0)
    ball_body.angular_velocity = 0
    st.phase = 'plunger'
    st.charge = 0.0
    st.captured = None
    st.ring_inside = False
    st.stuck_t = 0.0
    st.hist = []
    st.meter = 0.0
    visual_ball.enabled = True


def reset_game():
    """Start a new game.

    Zeroes the score, gives 3 balls, clears hole/lane lights, multiplier, bonus
    and hole cool-down, clears any tilt (clear_tilt), covers the puzzle again with
    picture 1 (puzzle_reset), spawns the ball (respawn_ball) and shows the
    "HOLD SPACE" hint for 2.5 s.  The music is NOT restarted.
    Called once at start-up and when R is pressed.
    """
    st.score = 0
    st.balls = 3
    st.hole_filled = [False, False, False]
    st.lane_lit = [False, False, False]
    st.mult = 1
    st.bonus = 0
    st.hole_cool = 0.0
    clear_tilt()
    puzzle_reset(0)
    respawn_ball()
    show_msg('HOLD SPACE, RELEASE TO LAUNCH', 2.5, color.cyan)


def drain():
    """Handle the ball being lost down the drain (ball y < -312).

    1. End-of-ball bonus: award = bonus * multiplier, but 0 if st.tilted.  It is
       added to the score; the part above the plain bonus (the multiplier's
       contribution) is also given to add_puzzle().
    2. Message text: 'BONUS <bonus> x<mult> = <award>' if award is non-zero,
       otherwise 'BALL LOST'.
    3. Reset bonus, multiplier and the lit rollover lanes.
    4. st.balls -= 1.  If balls remain: show the message (only when NOT tilted,
       so the TILT display is not disturbed) and respawn the ball.  Otherwise
       phase -> 'over', hide the ball and show 'GAME OVER - press R'.
    """
    award = 0 if st.tilted else st.bonus * st.mult        # no bonus after a tilt
    st.score += award
    if award > st.bonus:                                   # the multiplier part also feeds the puzzle
        add_puzzle(award - st.bonus)
    txt = f'BONUS {st.bonus} x{st.mult} = {award}' if award else 'BALL LOST'
    st.bonus = 0
    st.mult = 1
    st.lane_lit = [False, False, False]
    st.balls -= 1
    if st.balls > 0:
        if not st.tilted:
            show_msg(txt, 2.0, color.red)
        respawn_ball()
    else:
        st.phase = 'over'
        visual_ball.enabled = False
        show_msg('GAME OVER - press R', 999, color.red)


# --------------------------------------------------------------------------
# Nudge / tilt
# --------------------------------------------------------------------------
NUDGE_V0 = 0.35            # m/s   speed a shove gives the cabinet
CAB_FREQ = 5.5             # Hz    cabinet on its legs
CAB_ZETA = 0.22            # damping ratio
OMEGA = 2 * math.pi * CAB_FREQ                      # angular frequency (rad/s)
NUDGE_COUPLING = 0.7       # fraction of the cabinet motion that reaches the ball
VISUAL_GAIN = 3.0          # exaggeration of the cabinet motion on screen
METER_DECAY = 0.6          # tilt-meter units per second
METER_DANGER = 2.0         # meter value at which DANGER! is shown
METER_TILT = 3.0           # meter value at which TILT happens
WORLD_PER_M = 1.0 / 0.0135  # 1 world unit = 13.5 mm  (world units per metre)


def C(h, s, v, ph=0.0):
    """Return the colour for an animated light: normal, or tilt-strobe.

    Normal  : color.hsv(h mod 360, s, v).
    Tilted  : a full-saturation colour whose hue is (st.t*520 + ph*3) mod 360
              (fast colour rotation, different for each light via `ph`) and
              whose brightness alternates between 1.0 and 0.35 every 1/9 s
              (int(st.t*9) even -> bright), i.e. a 4.5 Hz strobe.  The h, s, v
              arguments are ignored while tilted.

    Parameters:
        h, s, v : normal hue (degrees), saturation and value.
        ph      : per-light phase offset (changes the strobe colour).
    Used for the rail LEDs, neon caps, inserts, stars, bumper LEDs, ring and the
    equalizer in update().
    """
    if st.tilted:
        flash = int(st.t * 9) % 2 == 0
        return color.hsv((st.t * 520 + ph * 3) % 360, 1, 1.0 if flash else 0.35)
    return color.hsv(h % 360, s, v)


def trigger_tilt():
    """Enter the TILT state.

    Sets st.tilted, forces every flipper's `active` flag to False (so they drop
    to their rest angles), shows the 30 pixel-letters 'TILT' on the board and
    cancels the current message timer (the flashing 'TILT' text is drawn by
    update() every frame).  Called by nudge() when the meter reaches METER_TILT.
    """
    st.tilted = True
    for f in flippers:
        f['active'] = False
    for e, ph in tilt_px:
        e.enabled = True
    st.msg_t = 0


def clear_tilt():
    """Leave the TILT state.

    Clears st.tilted and the tilt meter, hides the pixel letters, empties the
    message text and cancels its timer.  Called when the player launches the
    next ball with the plunger and from reset_game().
    """
    st.tilted = False
    st.meter = 0.0
    for e, ph in tilt_px:
        e.enabled = False
    msg_text.text = ''
    st.msg_t = 0


def machine_step(sd):
    """Advance the cabinet spring-damper by one physics sub-step of length sd.

    Equation (module docstring 6.9):  s'' = -omega^2 s - 2 zeta omega s'.
    Semi-implicit Euler: first update the velocity with the acceleration
    a(s, v), then the position with the NEW velocity.  The acceleration is
    stored in st.m_acc for pre_step(), which converts it into an inertial force
    on the ball.  Runs every sub-step, even when no nudge is active (it then
    keeps s = v = a = 0).

    Parameters:
        sd : sub-step duration in seconds.
    """
    a = -OMEGA * OMEGA * st.m_s - 2 * CAB_ZETA * OMEGA * st.m_v
    st.m_v += a * sd
    st.m_s += st.m_v * sd
    st.m_acc = a


def nudge():
    """Player shoves the machine (SPACE pressed).  Possibly leads to DANGER/TILT.

    Ignored unless st.phase == 'play', the machine is not already tilted and the
    ball is not in the plunger lane (SPACE then operates the plunger).
    Otherwise:
      1. pick a shove direction (sin phi, cos phi), phi uniform in +/-0.15 rad
         (mostly forward, away from the player), stored in st.m_dir;
      2. v0 = NUDGE_V0 * uniform(0.9, 1.1); the cabinet velocity st.m_v += v0
         (the spring then produces a displacement of about 7 mm and settles);
      3. if the ball is free (not held in a hole), the ball lags behind the
         sudden motion: its velocity changes by -kappa*v0 along m_dir, where
         kappa = NUDGE_COUPLING (the later oscillation force is applied in
         pre_step());
      4. tilt meter += 1.0; at >= METER_TILT call trigger_tilt(); otherwise at
         >= METER_DANGER show 'DANGER!' for 1 s.
    The meter decays at METER_DECAY per second in update().
    """
    bx, by = ball_body.position
    if st.phase != 'play' or st.tilted or (bx > 148 and by < -150):
        return
    phi = random.uniform(-0.15, 0.15)                     # slight sideways component
    st.m_dir = (math.sin(phi), math.cos(phi))
    v0 = NUDGE_V0 * random.uniform(0.9, 1.1)
    st.m_v += v0                                          # shove: cabinet gains speed instantly
    if st.captured is None:                               # ball lags behind: relative velocity -v0
        u = ms_to_units(v0) * NUDGE_COUPLING
        vx, vy = ball_body.velocity
        ball_body.velocity = (vx - st.m_dir[0] * u, vy - st.m_dir[1] * u)
    st.meter += 1.0
    if st.meter >= METER_TILT:
        trigger_tilt()
    elif st.meter >= METER_DANGER:
        show_msg('DANGER!', 1.0, color.red)


def set_camera(mode):
    """Select a camera view; the argument is reduced modulo 4.

    mode 0 : angled front view  - position (0, 62, -72), looking at (0, 10, 4).
             Lower than in v4 so that the bar's back wall is visible behind the
             back box.
    mode 1 : top-down view      - position (0, TABLE_Y + 95, 1), rotation (90, 0, 0).
    mode 2 : side view from the left - position (-72, 22, -26), looking at
             (0, 12, 2); makes the playfield tilt obvious.
    mode 3 : bar view - position (-26, 24, -88), looking at (4, 14, 30); a low
             wide shot of the machine in the pub.
    Stores the reduced mode in st.cam_mode.  Pressing C calls
    set_camera(st.cam_mode + 1).
    """
    st.cam_mode = mode % 4
    if st.cam_mode == 0:
        camera.position = (0, 62, -72)
        camera.look_at(Vec3(0, 10, 4))
    elif st.cam_mode == 1:
        camera.position = (0, TABLE_Y + 95, 1)
        camera.rotation = (90, 0, 0)
    elif st.cam_mode == 2:
        camera.position = (-72, 22, -26)
        camera.look_at(Vec3(0, 12, 2))
    else:
        camera.position = (-26, 24, -88)
        camera.look_at(Vec3(4, 14, 30))


# Initial camera and first game.  These run at import time, after every
# function they depend on (reset_game -> clear_tilt, respawn_ball, show_msg)
# has been defined above.
set_camera(0)
reset_game()
music_autostart()


def input(key):
    """Ursina key-event handler (called once per key press; auto-discovered).

    Parameters:
        key : Ursina key name, e.g. 'space', 'r', 'c', 'm', 'up arrow'.
    While the music menu is open every key goes to menu_key() and nothing else
    happens.  Otherwise:
        'space'      -> nudge()  (the plunger itself is handled in update()
                        through held_keys, not here)
        'r'          -> reset_game()
        'c'          -> next camera view (4 views)
        'm'          -> open the music menu (game pauses)
        'n'          -> next music track
        'up arrow'   -> st.tilt = min(9.0, st.tilt + 0.5), apply_tilt()
        'down arrow' -> st.tilt = max(4.0, st.tilt - 0.5), apply_tilt()
        'escape'     -> stop the music and quit
    This name shadows Python's built-in input(), which is intended: Ursina
    looks for a module-level function called `input`.
    """
    if st.menu_open:
        menu_key(key)
        return
    if key == 'space':
        nudge()
    elif key == 'r':
        reset_game()
    elif key == 'c':
        set_camera(st.cam_mode + 1)
    elif key == 'm':
        show_menu(True)
    elif key == 'n':
        music.next()
    elif key == 'up arrow':
        st.tilt = min(9.0, st.tilt + 0.5)
        apply_tilt()
    elif key == 'down arrow':
        st.tilt = max(4.0, st.tilt - 0.5)
        apply_tilt()
    elif key == 'escape':
        music.stop()
        application.quit()


# --------------------------------------------------------------------------
# Physics logic
# --------------------------------------------------------------------------
def drive_flipper(f, sd):
    """Move one flipper toward its target angle for one sub-step.

    The target is f['up'] if f['active'] else f['rest'].  The angular speed is
    FLIP_UP_SPEED when going up (active) and FLIP_DOWN_SPEED when returning.
    If the remaining angle |target - angle| is no more than speed*sd, the
    angle is set exactly to the target and the angular velocity to 0 (this also
    holds the flipper still at the end stops).  Otherwise the angular velocity
    is set to +/-speed (sign of the remaining angle) and pymunk's integrator
    (inside space.step) rotates the body; because the body is kinematic its real
    velocity is used for collisions, so the ball is struck correctly.

    Parameters:
        f  : a dict from `flippers`.
        sd : sub-step duration in seconds.
    """
    body = f['body']
    target = f['up'] if f['active'] else f['rest']
    speed = FLIP_UP_SPEED if f['active'] else FLIP_DOWN_SPEED
    diff = target - body.angle
    if abs(diff) <= speed * sd:
        body.angular_velocity = 0.0
        body.angle = target
    else:
        body.angular_velocity = math.copysign(speed, diff)


# Alias used by pre_step: rolling-resistance coefficient.
A_RR_FACTOR = C_ROLL            # rolling resistance:  a = C_rr * g * cos(theta)
# Speed limit 6 m/s = 4444 units/s; post_step clamps the ball to it.
MAX_BALL_SPEED = ms_to_units(6.0)


def pre_step(sd):
    """Forces and constraints applied BEFORE each space.step() sub-step.

    Order of operations:
      1. If the ball is held in a hole (st.captured is not None): pin it to the
         hole centre, zero its velocity and return (nothing else applies).
      2. If the cabinet is accelerating (|st.m_acc| > 1e-4): apply the inertial
         force of the nudge,  delta_v = -kappa * ms_to_units(a_cabinet) * sd
         along st.m_dir (module docstring 6.9).
      3. Rolling resistance: reduce the ball speed by
         ms_to_units(C_ROLL * g * cos(tilt)) * sd, never below zero.
      4. Unless a hole cool-down is running or the machine is tilted: the
         "dish" around each hole.  For every hole closer than 27 units
         (and not exactly at its centre) accelerate the ball toward the
         centre by  2 * accel_units(tilt) * (1 - d/27)  integrated over sd.

    Parameters:
        sd : sub-step duration in seconds.
    """
    if st.captured is not None:
        h = holes[st.captured]
        ball_body.position = (h['x'], h['y'])
        ball_body.velocity = (0, 0)
        return
    if abs(st.m_acc) > 1e-4:                             # inertial force from cabinet motion
        ap = -NUDGE_COUPLING * ms_to_units(st.m_acc) * sd
        vx, vy = ball_body.velocity
        ball_body.velocity = (vx + st.m_dir[0] * ap, vy + st.m_dir[1] * ap)
    vx, vy = ball_body.velocity
    sp = math.hypot(vx, vy)
    if sp > 0:                                           # rolling resistance
        a_rr = ms_to_units(A_RR_FACTOR * G_EARTH * math.cos(math.radians(st.tilt)))
        k = max(0.0, sp - a_rr * sd) / sp
        vx, vy = vx * k, vy * k
        ball_body.velocity = (vx, vy)
    if st.hole_cool > 0 or st.tilted:
        return
    bx, by = ball_body.position
    for h in holes:                                      # shallow dish around each hole
        dx, dy = h['x'] - bx, h['y'] - by
        d = math.hypot(dx, dy)
        if 0 < d < 27:
            acc = accel_units(st.tilt) * 2.0 * (1 - d / 27)
            vx, vy = ball_body.velocity
            ball_body.velocity = (vx + dx / d * acc * sd, vy + dy / d * acc * sd)


def post_step(sd):
    """Game logic evaluated AFTER each space.step() sub-step.

    Every scoring event that adds bonus points also calls add_puzzle() with the
    same amount (bumper 100, sling 25, lane 500, ring 150, hole 500) so that the
    picture puzzle opens as bonus is collected.

    Order of operations (everything uses the ball position after the step):
      1. Speed limit: clamp the speed to MAX_BALL_SPEED (6 m/s).
      2. Count down the cool-down timers of every bumper and sling.
      3. Held in a hole: count down st.capture_timer; at zero eject the ball at
         1.1 m/s in a direction GAP_CENTER +/- 25 degrees (through the ring
         opening), set st.captured = None and start the 1.2 s hole cool-down.
         Then RETURN (no other logic runs while the ball is held).
      4. Pop bumpers (skipped when tilted): if the centre distance is
         0 < d < radius + BALL_R + 3 and the bumper is not cooling down: set the
         velocity radially outward with speed max(BUMPER_KICK, 0.9*speed),
         cool-down 0.12 s, flash 0.25 s, +100 score, +100 bonus, sparks.
      5. Slingshots (skipped when tilted): if the distance to the rail is
         < BALL_R + 8 and not cooling down: let vn = velocity component along
         the rail's front normal; add front * max(0, SLING_KICK - max(0, vn))
         to the velocity (so the normal speed becomes at least SLING_KICK);
         cool-down 0.15 s, flash 0.2 s, +25 score, +25 bonus, sparks.
      6. Top lanes (skipped when tilted): an unlit lane whose centre is within
         12 units lights up (+500).  When all three are lit: multiplier + 1
         (max 5), lanes reset, message.
      7. Ring entry: track whether the ball centre is within RING_R - 6 of the
         ring centre.  On the transition outside -> inside (and not tilted):
         +150 and a 0.8 s ring flash.  The st.ring_inside flag is updated even
         when tilted.
      8. Holes: if a cool-down is running, count it down.  Otherwise (and not
         tilted) check each hole: ball within 10 units and speed below 0.9 m/s
         -> capture (hold 1.3 s, zero velocity, 12 sparks).  First visit: hole
         lights, +1000 score, +500 bonus; if all three are lit: +1 ball,
         +5000, holes reset, ring flash 2 s, EXTRA BALL message.  Already lit:
         +250.
      9. Gate: when the ball is in the field (x < 132, y > 160) and the gate is
         not yet in the space, close it.
     10. Out of play: y < -312 -> drain(); otherwise if x < -200, x > 200 or
         y > 380 (escaped the table) -> respawn_ball() without losing a ball.

    Parameters:
        sd : sub-step duration in seconds.
    """
    bx, by = ball_body.position
    vx, vy = ball_body.velocity
    speed = math.hypot(vx, vy)
    if speed > MAX_BALL_SPEED:
        k = MAX_BALL_SPEED / speed
        ball_body.velocity = (vx * k, vy * k)
        speed = MAX_BALL_SPEED

    for b in bumpers:
        b['cool'] -= sd
    for s in slings:
        s['cool'] -= sd

    if st.captured is not None:
        st.capture_timer -= sd
        if st.capture_timer <= 0:
            ang = math.radians(GAP_CENTER + random.uniform(-25, 25))
            ev = ms_to_units(1.1)
            ball_body.velocity = (math.cos(ang) * ev, math.sin(ang) * ev)
            st.captured = None
            st.hole_cool = 1.2
        return

    for b in ([] if st.tilted else bumpers):             # solenoids are dead after a tilt
        dx, dy = bx - b['x'], by - b['y']
        d = math.hypot(dx, dy)
        if 0 < d < b['r'] + BALL_R + 3 and b['cool'] <= 0:
            sp = max(BUMPER_KICK, speed * 0.9)
            ball_body.velocity = (dx / d * sp, dy / d * sp)
            b['cool'] = 0.12
            b['flash'] = 0.25
            st.score += 100
            st.bonus += 100
            add_puzzle(100)
            spawn_sparks(bx, by, b['hue'])

    for s in ([] if st.tilted else slings):
        if dist_pt_seg((bx, by), s['a'], s['b']) < BALL_R + 8 and s['cool'] <= 0:
            fx, fy = s['front']
            vx, vy = ball_body.velocity
            vn = vx * fx + vy * fy
            add = max(0.0, SLING_KICK - max(0.0, vn))
            ball_body.velocity = (vx + fx * add, vy + fy * add)
            s['cool'] = 0.15
            s['flash'] = 0.2
            st.score += 25
            st.bonus += 25
            add_puzzle(25)
            spawn_sparks(bx, by, 30, 5)

    for i, (lx, ly) in enumerate(LANES):                 # top rollover lanes
        if not st.tilted and not st.lane_lit[i] and math.hypot(bx - lx, by - ly) < 12:
            st.lane_lit[i] = True
            st.score += 500
            add_puzzle(500)
            if all(st.lane_lit):
                st.mult = min(5, st.mult + 1)
                st.lane_lit = [False, False, False]
                show_msg(f'BONUS MULTIPLIER x{st.mult}', 1.8, color.magenta)

    inside = math.hypot(bx - RING_C[0], by - RING_C[1]) < RING_R - 6
    if inside and not st.ring_inside and not st.tilted:
        st.score += 150
        add_puzzle(150)
        st.ring_flash = 0.8
    st.ring_inside = inside

    if st.hole_cool > 0:
        st.hole_cool -= sd
    elif not st.tilted:
        for i, h in enumerate(holes):
            if math.hypot(bx - h['x'], by - h['y']) < 10 and speed < ms_to_units(0.9):
                st.captured = i
                st.capture_timer = 1.3
                ball_body.velocity = (0, 0)
                spawn_sparks(h['x'], h['y'], 300, 12)
                if not st.hole_filled[i]:
                    st.hole_filled[i] = True
                    st.score += 1000
                    st.bonus += 500
                    add_puzzle(500)
                    show_msg('HOLE BONUS +1000', 1.5, color.lime)
                    if all(st.hole_filled):
                        st.balls += 1
                        st.score += 5000
                        st.hole_filled = [False, False, False]
                        st.ring_flash = 2.0
                        show_msg('EXTRA BALL!  +5000', 2.5, color.yellow)
                else:
                    st.score += 250
                    show_msg('HOLE ALREADY LIT +250', 1.2, color.cyan)
                break

    if not st.gate_on and bx < 132 and by > 160:
        set_gate(True)

    if by < -312:
        drain()
    elif bx < -200 or bx > 200 or by > 380:
        respawn_ball()


def roll_ball(vx, vy, dt):
    """Rotate the 8 surface dots of the ball as if it rolled without slipping.

    For a ball rolling on a plane with up vector y, the angular velocity is
    omega = (y_hat x v) / r.  In table-local axes (x, y, z) with v = (vx, 0, vy)
    (the physics y is the world z), this gives the unit rotation axis
    (vy, 0, -vx) / speed and the angle speed/BALL_R * dt per frame.
    Each stored vector in roll_vecs is rotated about that axis with Rodrigues'
    formula  v' = v cos a + (k x v) sin a + k (k . v)(1 - cos a)  (k has no y
    component, which is why the y terms are simplified), re-normalised to avoid
    drift, and the matching dot Entity is moved to 0.5 * v' (the surface of the
    unit-diameter sphere model, in the ball's local space).

    Parameters:
        vx, vy : ball velocity in physics units/s.
        dt     : frame time in seconds.
    Returns nothing; does nothing when the speed is below 1 unit/s.
    """
    sp = math.hypot(vx, vy)
    if sp < 1:
        return
    ax, az = vy / sp, -vx / sp                           # unit axis (ay = 0)
    ang = sp / BALL_R * dt
    c, s = math.cos(ang), math.sin(ang)
    for i, v in enumerate(roll_vecs):
        x, y, z = v
        kd = ax * x + az * z
        cx_, cy_, cz_ = -az * y, az * x - ax * z, ax * y
        nx = x * c + cx_ * s + ax * kd * (1 - c)
        ny = y * c + cy_ * s
        nz = z * c + cz_ * s + az * kd * (1 - c)
        n = math.sqrt(nx * nx + ny * ny + nz * nz)
        v[0], v[1], v[2] = nx / n, ny / n, nz / n
        roll_dots[i].position = (v[0] * 0.5, v[1] * 0.5, v[2] * 0.5)


def update():
    """Per-frame main loop (called automatically by Ursina, see section 9).

    Detailed steps:

    A. TIME.  dt = min(time.dt, 1/30) so a long hitch cannot explode the
       simulation.  The music player's looping watchdog runs (music.tick).  If the
       music menu is open the function only redraws the menu and returns (the
       whole game is frozen, including the clock); otherwise st.t += dt.

    B. FLIPPER KEYS.  left_key / right_key are true if any of arrow, A/D, Shift
       or Ctrl of that side is held.  Flippers are only enabled when not tilted
       (left_on = left_key and not st.tilted).  Each flipper's `active` flag is
       set according to its side; the cabinet buttons turn yellow when pressed.

    C. PLUNGER.  in_lane = (x > 148 and y < -150).  While SPACE is held, the
       ball is in the lane and the phase is not 'over', the charge grows at 1.4
       per second up to 1.  When SPACE is released (held last frame, not now):
       if in the lane, the ball is fired upward at plunger_ball_speed(max(charge,
       0.05)) m/s (converted to units), phase -> 'play', any tilt is cleared and
       a message shows the pull in mm and the speed (the pull shown uses the
       real charge, the speed uses at least 0.05).  The charge is reset either way.

    D. PHYSICS.  SUB = max(12, int(dt*960)) sub-steps of sd = dt/SUB.  Each runs:
       drive_flipper for every flipper; machine_step; pre_step (not when 'over');
       space.step(sd); post_step (not when 'over').

    E. CABINET.  Decay the tilt meter by METER_DECAY*dt (not below 0); set
       machine.x/z from the spring displacement:
       s * m_dir * VISUAL_GAIN * WORLD_PER_M.

    F. GAME OVER.  In phase 'over' the ball is parked at (2000, -2000) with zero
       velocity.

    G. BALL STATE.  Read position and velocity; st.speed_ms for the HUD.  Stuck
       rescue: in 'play', not held, speed < 12 units/s and not in the lane for
       more than 3 s -> velocity = (uniform(-150, 150), 350).

    H. VISUALS.
       * Ball: if held in a hole it sinks (height 0.3 + 0.7*sink, scale 55-100 %
         with sink = capture_timer/1.3); otherwise it sits at height 1.0 and
         roll_ball() spins the dots.  The shadow follows with an offset (+0.15, -0.15);
         it is hidden when 'over'.
       * Shadow: two translucent discs (core alpha 0.42, halo 0.16) offset to the
         lower right of the ball.
       * Trail: while playing, free, and faster than 0.9 m/s, the position is
         pushed to the front of st.hist (kept to 2*TRAIL_N = 24 entries);
         otherwise two entries are dropped per frame so the trail fades.  Trail
         disc i (12 of them, flat translucent ellipses at height 0.14) uses
         history entry 2*i + 2, diameter 0.25 + 1.5*k^2 and alpha 0.20*k^2*fade
         with k = 1 - i/12 and fade rising from 0 at 0.6 m/s to 1 at 2.6 m/s, so
         the trail is faint and only visible at speed; discs without a history
         entry are hidden.
       * Flippers: pivot.rotation_y = -degrees(body.angle).
       * Plunger: cap z = (-299 - 28*charge)*S, rod and knob follow; the charge
         bar height is 0.3*charge and its hue goes from green to red.
       * Lights: LEDs ('cycle': hue t*80+phase, brightness pulsing 0.55-1;
         'chase': a hue-t*40+190 sawtooth wave), neon caps, inserts (a travelling
         sine wave), stars, the lane lamps (yellow when lit, blue-grey when not),
         equalizer bars (height from products of sines, base at y = 18.1),
         bumper caps/skirts/LEDs (white flash for 0.25 s after a hit), sling
         caps (white flash or a hue cycle), ring caps (fast rainbow while
         st.ring_flash > 0), hole rims and glows (green pulse when lit, else
         rainbow).  Most of these go through C() so they strobe when tilted.
       * Sparks: for each live spark: life -= dt; move by v*dt; gravity
         25 units/s^2 on vy; floor bounce at y < 0.1 with restitution 0.4;
         scale 0.4 * life/mx; hide at the end of life.

    I. UI.  Score text and info text (balls, multiplier, holes as [X]/[ ], puzzle
       progress n/24) and the music line are rewritten only when the string
       changes.  The physics read-out (tilt angle,
       rolling acceleration, ball mass, speed) refreshes every 0.1 s.  The
       message timer clears msg_text at zero.  The nudge meter bar is
       0.3 * min(1, meter/METER_TILT) tall with hue green -> red.  Finally,
       while st.tilted: every TILT pixel gets hue (t*700 + phase*4) and the
       centred message is forced to 'TILT' with a rainbow colour (not when the
       game is over, so GAME OVER stays readable).
    """
    dt = min(time.dt, 1 / 30)
    music.tick(dt)
    if st.menu_open:                                      # menu open: game frozen, only the menu is drawn
        draw_menu()
        return
    st.t += dt
    t = st.t

    # ---- B. flipper keys ----
    left_key = bool(held_keys['left arrow'] or held_keys['a'] or held_keys['left shift'] or held_keys['left control'])
    right_key = bool(held_keys['right arrow'] or held_keys['d'] or held_keys['right shift'] or held_keys['right control'])
    left_on = left_key and not st.tilted                  # flippers are dead while tilted
    right_on = right_key and not st.tilted
    for f in flippers:
        f['active'] = left_on if f['side'] == 'L' else right_on
    btn_l.color = color.yellow if left_on else color.red
    btn_r.color = color.yellow if right_on else color.red

    # ---- C. plunger ----
    bx, by = ball_body.position
    in_lane = bx > 148 and by < -150
    space_down = bool(held_keys['space'])
    if st.phase != 'over':
        if space_down and in_lane:
            st.charge = min(1.0, st.charge + dt * 1.4)
        elif st.space_prev and not space_down:
            if in_lane:
                v = plunger_ball_speed(max(st.charge, 0.05))
                ball_body.velocity = (0, ms_to_units(v))
                st.phase = 'play'
                clear_tilt()                              # next ball shot ends the tilt
                show_msg(f'PLUNGER {st.charge * PULL_MAX_M * 1000:.0f} mm  ->  {v:.1f} m/s', 1.2, color.cyan)
            st.charge = 0.0
    st.space_prev = space_down

    # ---- D. physics sub-steps ----
    SUB = max(12, int(dt * 960))                          # sub-steps keep fast balls from tunnelling
    sd = dt / SUB
    for _ in range(SUB):
        for f in flippers:
            drive_flipper(f, sd)
        machine_step(sd)
        if st.phase != 'over':
            pre_step(sd)
        space.step(sd)
        if st.phase != 'over':
            post_step(sd)

    # ---- E. cabinet / tilt meter ----
    st.meter = max(0.0, st.meter - METER_DECAY * dt)
    machine.x = st.m_s * st.m_dir[0] * VISUAL_GAIN * WORLD_PER_M
    machine.z = st.m_s * st.m_dir[1] * VISUAL_GAIN * WORLD_PER_M

    # ---- F. game over: park the ball ----
    if st.phase == 'over':
        ball_body.position = (2000, -2000)
        ball_body.velocity = (0, 0)

    # ---- G. ball state, speed read-out, stuck rescue ----
    bx, by = ball_body.position
    vx, vy = ball_body.velocity
    speed = math.hypot(vx, vy)
    st.speed_ms = units_to_ms(speed)
    if st.phase == 'play' and st.captured is None and speed < 12 and not (bx > 148 and by < -150):
        st.stuck_t += dt
        if st.stuck_t > 3:
            ball_body.velocity = (random.uniform(-150, 150), 350)
            st.stuck_t = 0
    else:
        st.stuck_t = 0

    # ---------------- H. visuals ----------------
    if st.captured is not None:
        sink = max(0.0, min(1.0, st.capture_timer / 1.3))
        visual_ball.position = (bx * S, 0.3 + 0.7 * sink, by * S)
        visual_ball.scale = BALL_R * 2 * S * (0.55 + 0.45 * sink)
    else:
        visual_ball.position = (bx * S, 1.0, by * S)
        visual_ball.scale = BALL_R * 2 * S
        if st.phase != 'over':
            roll_ball(vx, vy, dt)
    ball_shadow.position = (bx * S + 0.15, 0.12, by * S - 0.15)
    ball_shadow2.position = (bx * S + 0.22, 0.11, by * S - 0.22)
    ball_shadow.enabled = ball_shadow2.enabled = st.phase != 'over'

    # trail
    if st.phase == 'play' and st.captured is None and speed > ms_to_units(0.9):
        st.hist.insert(0, (bx, by))
        st.hist = st.hist[:TRAIL_N * 2]
    else:
        st.hist = st.hist[:-2] if len(st.hist) > 2 else []
    # subtle trail: flat translucent discs, fading with distance and with low speed
    fade = max(0.0, min(1.0, (speed - ms_to_units(0.6)) / ms_to_units(2.0)))
    for i, e in enumerate(trail):
        idx = i * 2 + 2
        if idx < len(st.hist):
            hx, hy = st.hist[idx]
            e.enabled = True
            e.position = (hx * S, 0.14, hy * S)
            k = 1 - i / TRAIL_N
            d = 0.25 + 1.5 * k * k
            e.scale = (d, 0.03, d)
            e.color = color.hsv(205 + 20 * k, 0.35, 0.95, 0.20 * k * k * fade)
        else:
            e.enabled = False

    # flipper models follow the physics angle
    for f in flippers:
        f['pivot'].rotation_y = -math.degrees(f['body'].angle)

    # plunger pull animation and charge bar
    pull = st.charge
    plunger_cap.z = (-299 - 28 * pull) * S
    plunger_rod.z = plunger_cap.z - 2.8
    plunger_knob.z = plunger_cap.z - 5.6
    bar_fill.scale_y = 0.3 * st.charge
    bar_fill.color = color.hsv(120 - 120 * st.charge, 0.9, 0.95)

    # light animation (via C() so everything strobes when tilted)
    for e, kind, ph in leds:
        if kind == 'cycle':
            e.color = C(t * 80 + ph, 0.85, 0.55 + 0.45 * abs(math.sin(t * 2.5 + ph * 0.05)), ph)
        else:
            v = 1.0 - ((t * 2.0 - ph) % 1.0)
            e.color = C(t * 40 + 190, 0.9, 0.15 + 0.85 * v, ph * 60)
    for e, ph in neon:
        e.color = C(t * 70 + ph, 0.75, 1, ph)
    for e, ph in inserts:
        v = 0.25 + 0.75 * max(0.0, math.sin((t * 1.5 - ph) * 2 * math.pi))
        e.color = C(t * 50 + ph * 360, 0.85, v, ph * 360)
    for parts, ph in stars:
        c = C(t * 90 + ph, 0.8, 0.6 + 0.4 * math.sin(t * 4 + ph), ph)
        for p in parts:
            p.color = c
    for i, e in enumerate(lane_vis):
        if st.lane_lit[i]:
            e.color = color.hsv(55, 0.9, 0.75 + 0.25 * math.sin(t * 8))
        else:
            e.color = color.hsv(200, 0.6, 0.35)
    # equalizer strip along the bottom of the back box (heights 0.3 .. 1.7)
    for e, i in eq_bars:
        h = 0.3 + 0.9 * abs(math.sin(t * 2.2 + i * 0.7)) * abs(math.sin(t * 1.3 + i * 0.31)) + 0.5 * abs(math.sin(t * 5 + i))
        e.scale_y = h
        e.y = 17.9 + h / 2
        e.color = C(i * 21 + t * 60, 0.85, 1, i * 20)
    # chevron arrows: a brightness wave travelling along each group
    for parts, ph in arrows:
        v = max(0.2, 1.0 - ((t * 1.6 - ph) % 1.0))
        c = C(t * 50 + 300, 0.8, v, ph * 300)
        for p in parts:
            p.color = c
    # candles and lamp bulbs: warm flicker (strobe when tilted)
    for e, ph in warm:
        e.color = C(38, 0.55, 0.85 + 0.12 * math.sin(t * 3 + ph), ph)
    # puzzle: tile flips, finished-picture timer, frame colours
    puzzle_update(dt)
    for i, e in enumerate(puz_frame):
        if st.puz_flash > 0:
            e.color = color.hsv((t * 500 + i * 60) % 360, 1, 1)
        else:
            e.color = C(t * 60 + i * 90, 0.8, 1, i * 50)

    # bumpers: white flash right after a hit, else their own hue
    for b in bumpers:
        if b['flash'] > 0:
            b['flash'] -= dt
            b['cap'].color = color.white
            b['cap'].scale = (4.4, 2.9, 4.4)
            b['skirt'].color = color.white
            for e in b['leds']:
                e.color = color.white
        else:
            b['cap'].color = color.hsv(b['hue'], 0.9, 0.95)
            b['cap'].scale = (3.8, 2.4, 3.8)
            b['skirt'].color = color.hsv(b['hue'], 0.8, 0.55)
            for k, e in enumerate(b['leds']):
                e.color = C(t * 140 + k * 30 + b['hue'], 0.9, 1, k * 30)
    # slingshot caps
    for s in slings:
        if s['flash'] > 0:
            s['flash'] -= dt
            s['vis'].color = color.white
        else:
            s['vis'].color = color.hsv((t * 90) % 360, 0.9, 1)

    # orbit ring
    if st.ring_flash > 0:
        st.ring_flash -= dt
    for i, v in enumerate(ring_vis):
        if st.ring_flash > 0:
            v.color = color.hsv((t * 600 + i * 12) % 360, 0.9, 1)
        else:
            v.color = C(t * 60 + i * 11, 0.8, 0.95, i * 11)
    # holes
    for i, h in enumerate(holes):
        if st.hole_filled[i]:
            pulse = 0.6 + 0.4 * math.sin(t * 6)
            h['rim'].color = color.hsv(120, 0.9, pulse)
            h['glow'].color = color.hsv(120, 0.9, 0.5 * pulse)
        else:
            h['rim'].color = color.hsv((t * 100 + i * 120) % 360, 0.9, 0.9)
            h['glow'].color = color.hsv((t * 100 + i * 120) % 360, 0.9, 0.4)

    # sparks
    for s in sparks:
        if s['life'] > 0:
            s['life'] -= dt
            e = s['e']
            e.x += s['vx'] * dt
            e.z += s['vz'] * dt
            e.y += s['vy'] * dt
            s['vy'] -= 25 * dt
            if e.y < 0.1:
                e.y = 0.1
                s['vy'] = abs(s['vy']) * 0.4
            e.scale = 0.4 * max(0.0, s['life'] / s['mx'])
            if s['life'] <= 0:
                e.enabled = False

    # ---------------- I. UI ----------------
    s_txt = f'SCORE {st.score:07d}'
    if s_txt != _last['score']:
        score_text.text = s_txt
        _last['score'] = s_txt
    marks = ''.join('[X]' if f else '[ ]' for f in st.hole_filled)
    i_txt = f'BALLS {st.balls}   BONUS x{st.mult}   HOLES {marks}   PUZZLE {st.puz_open}/{len(puz_tiles)}'
    if i_txt != _last['info']:
        info_text.text = i_txt
        _last['info'] = i_txt
    st.hud_t += dt
    if st.hud_t > 0.1:
        st.hud_t = 0.0
        a_ms2 = G_EARTH * math.sin(math.radians(st.tilt)) * ROLL_FACTOR
        p_txt = (f'TILT {st.tilt:.1f} deg   a = {a_ms2:.2f} m/s2 (rolling)   '
                 f'ball 27 mm / 80.5 g   speed {st.speed_ms:.2f} m/s')
        if p_txt != _last['phys']:
            phys_text.text = p_txt
            _last['phys'] = p_txt
    if st.msg_t > 0:
        st.msg_t -= dt
        if st.msg_t <= 0:
            msg_text.text = ''

    # current music track (bottom right)
    m_txt = music.hud_text()
    if m_txt != _last['music']:
        music_text.text = m_txt
        _last['music'] = m_txt

    # nudge (tilt) meter bar
    frac = min(1.0, st.meter / METER_TILT)
    meter_fill.scale_y = 0.3 * frac
    meter_fill.color = color.hsv(120 - 120 * frac, 0.9, 0.95)

    if st.tilted:                                         # flashing colourful TILT on board + screen
        for e, ph in tilt_px:
            e.color = color.hsv((t * 700 + ph * 4) % 360, 1, 1)
        if st.phase != 'over':                            # keep 'GAME OVER' readable after a tilted last ball
            msg_text.text = 'TILT'
            msg_text.color = color.hsv((t * 600) % 360, 1, 1)


# Start the Ursina main loop: opens the window, then calls update() every frame
# and input(key) for each key press until the window is closed.
app.run()
