"""mergen logosu: Göktürk "m" harfi (𐰢, U+10C22), Segoe UI Historic yazı tipinden çizilir.

Üretir: mergen/assets/logo.png (beyaz harf, saydam; arayüzde tema rengine boyanır) ve logo.ico
(kamug gibi açık gri yuvarlak kare üstünde koyu harf, 16-256 px). Logo değişirse bir kez çalıştırılır:
    python packaging/make_logo.py
"""
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "mergen", "assets")
GLYPH = "\U00010C22"
FONT = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "seguihis.ttf")
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def glyph(size, color=(255, 255, 255, 255)):
    font = ImageFont.truetype(FONT, size)
    im = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((size // 2, size // 4), GLYPH, font=font, fill=color)
    return im.crop(im.getbbox())


def fit(g, h):
    return g.resize((max(1, round(g.width * h / g.height)), h), Image.LANCZOS)


def tile(size, ss=8):
    """Açık gri (üstten alta hafif koyulaşan) yuvarlak kare + koyu harf."""
    n = size * ss
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    grad = Image.new("RGBA", (n, n))
    gd = ImageDraw.Draw(grad)
    for yy in range(n):
        v = int(236 - (236 - 191) * yy / max(1, n - 1))
        gd.line([(0, yy), (n, yy)], fill=(v, v, v, 255))
    mask = Image.new("L", (n, n), 0)
    r = int(n * 0.19)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, n - 1, n - 1], r, fill=255)
    img.paste(grad, (0, 0), mask)
    ImageDraw.Draw(img).rounded_rectangle([ss // 2, ss // 2, n - 1 - ss // 2, n - 1 - ss // 2], r,
                                          outline=(150, 150, 150, 255), width=max(1, ss // 2))
    gh = int(n * 0.58)
    s = fit(glyph(max(64, gh * 2), (24, 24, 24, 255)), gh)
    img.alpha_composite(s, ((n - s.width) // 2, (n - gh) // 2))
    return img.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(ASSETS, exist_ok=True)
    fit(glyph(420), 306).save(os.path.join(ASSETS, "logo.png"))
    imgs = [tile(s) for s in SIZES]
    imgs[-1].save(os.path.join(ASSETS, "logo.ico"), sizes=[(s, s) for s in SIZES], append_images=imgs[:-1])
    print("logo tamam")


if __name__ == "__main__":
    main()
