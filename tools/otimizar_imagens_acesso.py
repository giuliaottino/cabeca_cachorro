"""Gera versões web (JPEG progressivo) das imagens da página de acesso. Reexecutável."""
from pathlib import Path
from PIL import Image, ImageOps

SRC = Path(__file__).resolve().parents[1] / "figures" / "conservacao"
OUT = SRC / "web"
OUT.mkdir(exist_ok=True)
# nome -> largura máxima (fundos de largura total maiores; cartões menores)
ALVOS = {
    "conservacaotitlebg.png": 2000, "wallace.jpg": 1200, "spruce.jpg": 1200, "ducke.jpg": 760,
    "expedicao_recente.jpg": 1200, "herbario.png": 1200, "fanerogama_campo.jpg": 800,
    "criptogama_campo.jpeg": 800, "fungo_campo.jpg": 1000, "herbarium_blitz.jpg": 1400,
    "exsicata_fanerogama.jpg": 800, "exsicata_criptogama.jpg": 800, "exsicata_fungo.jpg": 800,
}
total_antes = total_depois = 0
for nome, largura in ALVOS.items():
    src = SRC / nome
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    if im.width > largura:
        im = im.resize((largura, round(im.height * largura / im.width)), Image.LANCZOS)
    dst = OUT / (src.stem + ".jpg")
    im.save(dst, "JPEG", quality=78, optimize=True, progressive=True)
    a, d = src.stat().st_size, dst.stat().st_size
    total_antes += a; total_depois += d
    print(f"{nome:28s} {a/1024:7.0f} KB -> {d/1024:5.0f} KB  ({im.width}x{im.height})")
print(f"TOTAL {total_antes/1e6:.1f} MB -> {total_depois/1e6:.2f} MB")
