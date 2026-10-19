"""The scanned map sections: downloaded once, cached as zoom levels, served as tiles.

The scans come from the Internet Archive's original upload of the rulebook,
which holds each map section as a full 300 dpi JPEG stored landscape. The
text PDF next to it recompresses them (Map A's colour layer to ~100 dpi).
The grids were fitted on renders of the text PDF, which line up with the
originals to within a pixel once rotated, but are up to a pixel larger; the
originals' last row and column are repeated to make up the difference.

Extracting needs pdfimages (Poppler or Xpdf) on PATH.
"""
import io
import math
import os
import shutil
import subprocess
import threading
import urllib.request

from PIL import Image

from .joined import MALTA
from .paths import CACHE

Image.MAX_IMAGE_PIXELS = None

ORIGINAL_PDF = ('https://archive.org/download/campaign-for-north-africa/'
                'The%20Campaign%20for%20North%20Africa.pdf')
SCANS = {  # map -> (PDF page, rotation to upright, size the grid was fitted on)
    'A': (188, Image.ROTATE_90, (6669, 10595)),
    'B': (189, Image.ROTATE_270, (6682, 10596)),
    'C': (190, Image.ROTATE_90, (6687, 10586)),
    'D': (191, Image.ROTATE_90, (6689, 10586)),
    'E': (192, Image.ROTATE_270, (6693, 10586)),
}
TILE = 256
FETCH_LOCK = threading.Lock()
# A full scan takes ~200 MB decoded and seconds to decode, so one is decoded
# at a time, the reduced levels are cached as files, and only the most
# recently used scans keep their two largest levels loaded.
MAX_LOADED = 2
LOADED = []  # MapImages holding their large levels, least recently used first
LOADED_LOCK = threading.Lock()
DECODE_LOCK = threading.Lock()


def fetch_scans():
    """Download the original PDF once and extract every scan not yet cached."""
    with FETCH_LOCK:
        missing = [m for m in SCANS if not IMAGES[m].path.exists()]
        if not missing:
            return
        if not shutil.which('pdfimages'):
            raise RuntimeError('pdfimages (Poppler or Xpdf) is needed on PATH to extract the map scans')
        maps = CACHE / 'maps'
        maps.mkdir(parents=True, exist_ok=True)
        print('downloading the map scans from the Internet Archive (134 MB, once)...', flush=True)
        tmp = maps / 'original.pdf.download'
        urllib.request.urlretrieve(ORIGINAL_PDF, tmp)
        for m in missing:
            page, rotation, size = SCANS[m]
            prefix = maps / f'page{m}'
            subprocess.run(['pdfimages', '-j', '-f', str(page), '-l', str(page), str(tmp), str(prefix)],
                           check=True)
            src = maps / f'page{m}-000.jpg'
            im = Image.open(src).convert('RGB').transpose(rotation)
            full = Image.new('RGB', size)
            full.paste(im, (0, 0))
            for x in range(im.width, size[0]):
                full.paste(full.crop((im.width - 1, 0, im.width, size[1])), (x, 0))
            for y in range(im.height, size[1]):
                full.paste(full.crop((0, im.height - 1, size[0], im.height)), (0, y))
            full.save(IMAGES[m].path)
            src.unlink()
        tmp.unlink()


class MapImage:
    """One map section's scan: lazily extracted, loaded and tiled."""

    def __init__(self, map_id):
        self.id = map_id
        self.path = CACHE / 'maps' / f'map{map_id}.png'
        self.lock = threading.Lock()
        self.levels = {}  # zoom -> PIL image at that zoom's scale
        self._size = None
        self._version = None

    def size(self):
        if self._size is None:
            if not self.path.exists():
                fetch_scans()
            with Image.open(self.path) as im:
                self._size = im.size
            self._version = self.path.stat().st_mtime_ns
        return self._size

    def zmax(self):
        w, h = self.size()
        return math.ceil(math.log2(max(w, h) / TILE))

    def level(self, z):
        """The scan at zoom z: full resolution at zmax, halved per level below."""
        with self.lock:
            im = self._level(z)
        if z >= self.zmax() - 1:
            with LOADED_LOCK:
                if self in LOADED:
                    LOADED.remove(self)
                LOADED.append(self)
                while len(LOADED) > MAX_LOADED:
                    old = LOADED.pop(0)
                    old.levels = {k: v for k, v in old.levels.items() if k < old.zmax() - 1}
        return im

    def version(self):
        """Changes whenever the cached scan is replaced; keys the tile cache."""
        self.size()
        return self._version

    def level_path(self, z):
        return self.path.with_name(f'{self.path.stem}.z{z}.png')

    def _level(self, z):
        if z not in self.levels:
            path = self.level_path(z)
            if z == self.zmax():
                with DECODE_LOCK:
                    im = Image.open(self.path).convert('RGB')
                    im.load()
            elif path.exists() and path.stat().st_mtime_ns >= self.version():
                im = Image.open(path).convert('RGB')
                im.load()
            else:
                im = self._level(z + 1).reduce(2)
                im.save(path, compress_level=1)
            self.levels[z] = im
        return self.levels[z]

    def warm(self):
        """Cache every reduced level as a file, so no zoom needs the full scan."""
        if not self.level_path(0).exists() or self.level_path(0).stat().st_mtime_ns < self.version():
            print(f'building zoom levels for map {self.id} (once)...', flush=True)
            for z in range(self.zmax() - 1, -1, -1):
                self.level(z)
            self.levels = {k: v for k, v in self.levels.items() if k < self.zmax() - 1}

    def tile(self, z, x, y):
        """One 256 px JPEG tile, or None outside the scan."""
        out = CACHE / 'tiles' / self.id / str(self.version()) / str(z) / f'{x}_{y}.jpg'
        if out.exists():
            return out.read_bytes()
        if not 0 <= z <= self.zmax():
            return None
        im = self.level(z)
        x0, y0 = x * TILE, y * TILE
        if x0 >= im.width or y0 >= im.height or x < 0 or y < 0:
            return None
        crop = im.crop((x0, y0, min(x0 + TILE, im.width), min(y0 + TILE, im.height)))
        canvas = Image.new('RGB', (TILE, TILE), (230, 230, 230))
        canvas.paste(crop, (0, 0))
        buf = io.BytesIO()
        canvas.save(buf, 'JPEG', quality=88)
        body = buf.getvalue()
        # Neighbouring tiles of the joined map ask for the same tile at once.
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f'{out.stem}.{threading.get_ident()}.tmp')
        try:
            tmp.write_bytes(body)
            os.replace(tmp, out)
        except OSError:
            tmp.unlink(missing_ok=True)
        return body


IMAGES = {m: MapImage(m) for m in SCANS}
IMAGES[MALTA] = IMAGES['A']  # the Malta inset is printed on Map A's sheet


def warm_all():
    for m in SCANS:
        IMAGES[m].warm()
