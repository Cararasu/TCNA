"""Give every copy of a hex or hexside shared by two sections the same correction.

Usage (from the project folder):
  python -m cna.sync

The server does this on start and on every save; run it after editing
correction files by hand.
"""
from .joined import sync_all

if __name__ == '__main__':
    n, written = sync_all()
    print(f'synchronized {n} corrections' if n else 'all corrections are in sync',
          f'(rewrote {", ".join(written)})' if written else '')
