"""A scenario's units at its start, as its set-up brings them (setup.py), for
checking against the rulebook by eye.

Usage (from the project folder):
  python -m cna.engine.roster <scenario or setup>

prints each side's counters place by place, each with the units it carries,
their TOE and current morale, the formation each is assigned to where that is
not the unit carrying it, and the listing's printed text.
"""
import argparse
import sys

from . import oa, setup
from .board import board


def _toe_text(toe):
    def one(t):
        if 'w' in t:
            return f'{t["n"]}×{oa.charts().weapons[t["w"]]["name"]}' + (f' ({t["land"]} on land)' if 'land' in t else '')
        return f'{t["n"]}×{t["code"]}' if 'code' in t else f'{t["n"]}'
    return ', '.join(one(t) for t in toe) or 'no TOE'


def roster(name, out=sys.stdout):
    """Prints the set-up of a scenario (or of a setup, at its first scenario's start)."""
    cat = setup.catalog()
    scenario = next((s for s in cat['scenarios'] if name in (s['id'], s['setup'])), None)
    if scenario is None:
        raise SystemExit(f'There is no scenario or setup {name!r}.')
    su = cat['setups'][scenario['setup']]
    b = board()
    state = {'units': setup.units(scenario['setup'], su, b, scenario['start'])}
    units = state['units']
    labels = {}  # a hex where map sections overlap has a label on each
    for label, hid in sorted(b.labels.items()):
        labels[hid] = f'{labels[hid]} = {label}' if hid in labels else label

    def where(loc):
        return {'hex': lambda: labels.get(loc['id'], loc['id']), 'zone': lambda: f'box {loc["id"]}',
                'pool': lambda: 'to be placed'}[loc['kind']]()

    def line(uid, depth):
        u = units[uid]
        f = oa.face(u)
        notes = []
        if u['parent'] and u['parent'] != u['attached']:
            p = units.get(u['parent'])
            notes.append(f'assigned to {oa.face(p)["abbr"] if p else oa.unit(u["parent"])["name"] + " (not in play)"}')
        m = u['morale'] and u['morale']['current']
        text = '  ' * depth + f'{f["abbr"]:<10} {f["name"]}  [{f["type"]} {f["size"]}]  {_toe_text(u["toe"])}'
        text += f'  morale {m:+d}' if m is not None else ''
        print(text + (f'  ({"; ".join(notes)})' if notes else ''), file=out)
        for node in oa.carried(state, uid):
            line(node['id'], depth + 1)

    print(f'{scenario["name"]}: Game-Turn {scenario["start"]["turn"]}, OpStage {scenario["start"]["stage"]}', file=out)
    for side in ('axis', 'cw'):
        counters = [u for u in units.values() if u['side'] == side and u['attached'] is None]
        print(f'\n=== {side}: {len(counters)} counters, {sum(1 for u in units.values() if u["side"] == side)} units', file=out)
        for i, e in enumerate(su['deploy']):
            here = [u for u in counters if u['deployment'] == i]
            if not here:
                continue
            at = e['at']
            print(f'\n--- {e["rule"]} {at.get("label") or at.get("area") or ""} '
                  f'{at.get("hex") or at.get("near") or at.get("box") or ", ".join(at.get("hexes", []))}'.rstrip(), file=out)
            for u in here:
                listing = e['units'][u['listing']]
                if listing.get('text') and listing.get('oa') == u['oa']:
                    print(f'  "{listing["text"]}"', file=out)
                print(f'  @ {where(u["loc"])}', end=' ', file=out)
                line(u['id'], 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('scenario', help='a scenario or setup id, as in data/scenarios.json')
    roster(ap.parse_args().scenario)


if __name__ == '__main__':
    main()
