"""Regenerate the MSIX logo set in installer/msix/Images from assets/cwatm_small.ico.

Run from the repository root (needs Pillow, which the venv has through matplotlib):

    python installer/msix/make_images.py

The PNGs are committed, so a release build does not run this. Run it again only
when the icon changes. File names carry MRT qualifiers (scale-*, targetsize-*,
altform-unplated); build_release.ps1's msix step indexes them into resources.pri,
and the manifest refers to the unqualified names (Images\\Square44x44Logo.png).

- Square44x44Logo.targetsize-N[_altform-unplated]: taskbar, Start list, Alt+Tab.
  Full-bleed like a normal icon; the hand-made 16/24/32/48 px frames of the .ico
  are used as they are, so the small sizes stay as crisp as the classic exe icon.
- Square44x44Logo.scale-N: the same icon for the app list at display scale N %.
- Square150x150Logo.scale-N: the Start tile. The logo fills about two thirds of
  the tile, as the tile guidelines ask, on a transparent background.
- StoreLogo.scale-N: the package logo shown by the installer and in Settings.
"""

import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SOURCE = os.path.join(ROOT, "assets", "cwatm_small.ico")
OUT = os.path.join(HERE, "Images")

TARGET_SIZES = (16, 24, 32, 48, 256)
SCALES = (100, 200)
TILE_FILL = 0.66         # share of a Start tile the logo covers
ICON_FILL = 1.0          # icons and the Store logo are full-bleed


def ico_frames(path):
    """{size: RGBA image} for every square frame in the .ico."""
    ico = Image.open(path)
    frames = {}
    for size in sorted(ico.info.get("sizes", ())):
        if size[0] != size[1]:
            continue
        ico.size = size
        frames[size[0]] = ico.convert("RGBA")
    if not frames:
        raise SystemExit(f"no square frames in {path}")
    return frames


def render(frames, canvas, fill):
    """The icon centred on a transparent `canvas` x `canvas` image, `fill` of it."""
    target = max(1, round(canvas * fill))
    if target in frames and fill == ICON_FILL:
        return frames[target].copy()
    # Downscale from the smallest frame that is at least as big; upscaling only
    # happens when the request exceeds the largest frame.
    bigger = [s for s in frames if s >= target]
    src = frames[min(bigger)] if bigger else frames[max(frames)]
    logo = src.copy()
    logo.thumbnail((target, target), Image.LANCZOS)
    out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    out.paste(logo, ((canvas - logo.width) // 2, (canvas - logo.height) // 2), logo)
    return out


def main():
    frames = ico_frames(SOURCE)
    os.makedirs(OUT, exist_ok=True)
    for name in os.listdir(OUT):
        if name.lower().endswith(".png"):
            os.remove(os.path.join(OUT, name))

    written = []

    def save(img, name):
        img.save(os.path.join(OUT, name), optimize=True)
        written.append(name)

    for size in TARGET_SIZES:
        img = render(frames, size, ICON_FILL)
        save(img, f"Square44x44Logo.targetsize-{size}.png")
        save(img, f"Square44x44Logo.targetsize-{size}_altform-unplated.png")
    for scale in SCALES:
        save(render(frames, 44 * scale // 100, ICON_FILL),
             f"Square44x44Logo.scale-{scale}.png")
        save(render(frames, 150 * scale // 100, TILE_FILL),
             f"Square150x150Logo.scale-{scale}.png")
        save(render(frames, 50 * scale // 100, ICON_FILL),
             f"StoreLogo.scale-{scale}.png")

    print(f"{len(written)} images written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
