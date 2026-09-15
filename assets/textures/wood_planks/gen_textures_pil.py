import os, random
from PIL import Image, ImageChops, ImageDraw, ImageFilter

OUT = "/Users/admin/Projects/unreal-agent/assets/textures/wood_planks"
os.makedirs(OUT, exist_ok=True)
S = 1024
N_BOARDS = 8
BW = S // N_BOARDS
random.seed(42)

# ---------- helpers ----------
def streak_noise(stretch, seed):
    """Vertical streaks: 1D-ish noise stretched along Y."""
    random.seed(seed)
    w = max(4, S // stretch)
    img = Image.effect_noise((w, S), 60).resize((S, S), Image.BILINEAR)
    return img

def blob_noise(scale, seed):
    """Large soft mottle."""
    random.seed(seed)
    img = Image.effect_noise((S // scale, S // scale), 70).resize((S, S), Image.BILINEAR)
    return img.filter(ImageFilter.GaussianBlur(3))

# ---------- per-board tone bands ----------
tone = Image.new("L", (BW * N_BOARDS, 1))
td = ImageDraw.Draw(tone)
for b in range(N_BOARDS):
    g = int(128 + random.uniform(-42, 52))
    td.rectangle([b * BW, 0, (b + 1) * BW - 1, 0], fill=g)
tone = tone.resize((S, S), Image.NEAREST)

# ---------- grain ----------
g1 = streak_noise(28, 7)                  # long streaks
g2 = streak_noise(56, 11)                 # short fiber
grain = ImageChops.add(ImageChops.multiply(g1, Image.new("L", (S, S), 170)),
                       ImageChops.multiply(g2, Image.new("L", (S, S), 85)))

# ---------- knots ----------
knot = Image.new("L", (S, S), 0)
kd = ImageDraw.Draw(knot)
for b in range(N_BOARDS):
    if random.random() < 0.65:
        cx = b * BW + random.uniform(0.3, 0.7) * BW
        cy = random.uniform(0.15, 0.85) * S
        rx, ry = random.uniform(10, 18), random.uniform(26, 48)
        kd.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=random.randint(140, 210))
knot = knot.filter(ImageFilter.GaussianBlur(9))

# ---------- seams (vertical board gaps + horizontal joints) ----------
seam = Image.new("L", (S, S), 0)
sd = ImageDraw.Draw(seam)
for b in range(1, N_BOARDS):
    sd.line([(b * BW, 0), (b * BW, S)], fill=210, width=3)
for b in range(N_BOARDS):
    jy = random.uniform(0.25, 0.9) * S
    sd.line([(b * BW + 4, jy), ((b + 1) * BW - 4, jy)], fill=130, width=2)
seam = seam.filter(ImageFilter.GaussianBlur(1.6))

# ---------- mottle / grime ----------
mottle = blob_noise(9, 23)

# ---------- luminance composition ----------
L = ImageChops.multiply(tone, grain)                                   # tone * grain
L = ImageChops.multiply(L, ImageChops.subtract(Image.new("L", (S, S), 255),
                                               ImageChops.multiply(knot, Image.new("L", (S, S), 140))))  # * (1 - 0.55*knot)
L = ImageChops.subtract(L, ImageChops.multiply(seam, Image.new("L", (S, S), 90)))  # - 0.35*seam
L = ImageChops.add(L, ImageChops.multiply(mottle, Image.new("L", (S, S), 46)))     # + 0.18*mottle

# ---------- BaseColor channels (aged oak brown, sRGB) ----------
def chan(img, mult, gamma):
    return img.point(lambda v: min(255, int(((v / 255.0) ** gamma) * 255 * mult)))
BC = Image.merge("RGB", [chan(L, 0.44, 0.92), chan(L, 0.285, 0.95), chan(L, 0.165, 1.0)])
BC.save(f"{OUT}/T_WoodPlanks_BC.png")

# ---------- Normal (height -> normals, G flipped for Unreal) ----------
S_N = 512
Hs = L.resize((S_N, S_N), Image.BILINEAR)
hp = Hs.load()
norm = Image.new("RGB", (S_N, S_N))
np_ = norm.load()
STR = 5.0
for yy in range(S_N):
    ym = (yy - 1) % S_N
    yp = (yy + 1) % S_N
    for xx in range(S_N):
        xm = (xx - 1) % S_N
        xp = (xx + 1) % S_N
        dx = (hp[xp, yy] - hp[xm, yy]) / 510.0
        dy = (hp[xx, yp] - hp[xx, ym]) / 510.0
        nx, ny, nz = -dx * STR * 16, dy * STR * 16, 1.0   # +dy: G flipped for UE
        ln = (nx * nx + ny * ny + nz * nz) ** 0.5
        np_[xx, yy] = (int((nx / ln * 0.5 + 0.5) * 255),
                       int((ny / ln * 0.5 + 0.5) * 255),
                       int((nz / ln * 0.5 + 0.5) * 255))
norm = norm.resize((S, S), Image.BILINEAR)
norm.save(f"{OUT}/T_WoodPlanks_N.png")

# ---------- Roughness ----------
R = ImageChops.subtract(Image.new("L", (S, S), 199),
                        ImageChops.multiply(grain, Image.new("L", (S, S), 30)))
R = ImageChops.add(R, ImageChops.multiply(seam, Image.new("L", (S, S), 38)))
R = ImageChops.add(R, ImageChops.multiply(knot, Image.new("L", (S, S), 25)))
R.save(f"{OUT}/T_WoodPlanks_R.png")

# ---------- AO ----------
AO = ImageChops.subtract(Image.new("L", (S, S), 255),
                         ImageChops.multiply(seam, Image.new("L", (S, S), 178)))
AO = ImageChops.subtract(AO, ImageChops.multiply(knot, Image.new("L", (S, S), 90)))
AO.save(f"{OUT}/T_WoodPlanks_AO.png")

# ---------- packed ORM (R=AO, G=Rough, B=Metal) ----------
ORM = Image.merge("RGB", [AO, R, Image.new("L", (S, S), 0)])
ORM.save(f"{OUT}/T_WoodPlanks_ORM.png")

print("TEXTURES WRITTEN:", sorted(os.listdir(OUT)))
