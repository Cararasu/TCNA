"""Proposes the OA unit for each listing of data/scenarios.json, for review.

Usage (from the project folder):
  python -I tools/units/link.py [--setup ID] [--json FILE]

A set-up names its units in free text ("1 CCNN Div", "4th RHA" with "7 Spt/7"
in its text). For each listing this proposes the OA units (data/units/) it
most likely means, with a score, and does the same for each name in the
text's Less, Assg, Att, Det and Consists of clauses (59.2). It prints the
proposals, and with --json also writes them as data. It never changes
scenarios.json: each proposal is to be checked against the set-up in the
rulebook (60.3x-63.4x), and only confirmed links go into scenarios.json.
A listing already linked shows its link, marked ! where no proposal names it.

The match compares a name's words with each counter's name and abbreviation,
after spelling out the charts' abbreviations (Armd, Bde, Fld, Hus, ...). The
numbers in a name must match; the parent designation (7 Spt/7, 5 Le, 2 NZ)
and the listing's type (Ar, AT, T, ...) break ties.
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data'
CHARTS = ('cw', 'it', 'gm')
SIDE_CHARTS = {'cw': ('cw',), 'axis': ('it', 'gm')}

# Spellings of the same word, in the set-ups and on the OA sheets.
SAME = {
    'armoured': 'armd', 'armored': 'armd', 'arm': 'armd', 'amr': 'armd', 'armor': 'armd',
    'brigade': 'bde', 'bdg': 'bde', 'division': 'div', 'divisione': 'div', 'regiment': 'regt', 'rgt': 'regt',
    'regimental': 'regt', 'battalion': 'bn', 'company': 'coy', 'koy': 'coy', 'co': 'coy',
    'artillery': 'arty', 'artiglieri': 'arty', 'artiglieria': 'arty', 'artigliera': 'arty', 'artiglierie': 'arty',
    'field': 'fld', 'medium': 'med', 'hussars': 'hus', 'guards': 'gds', 'gd': 'gds',
    'infantry': 'inf', 'fanteria': 'inf', 'fanterie': 'inf', 'australian': 'aus', 'indian': 'in',
    'zealand': 'nz', 'african': 'sa', 'africa': 'sa', 'machinegun': 'mg', 'machinegewehr': 'mg',
    'antitank': 'at', 'anti-tank': 'at', 'panzerjaeger': 'at', 'panzerjager': 'at', 'flak': 'aa',
    'anti-aircraft': 'aa', 'anti-air': 'aa', 'antiaircraft': 'aa', 'aufklarungs': 'recce', 'reconnaissance': 'recce',
    'recon': 'recce', 'cavalry': 'cav', 'cv': 'cav', 'cp': 'corps', 'pioneer': 'eng', 'engineer': 'eng',
    'engineers': 'eng', 'schutzen': 'rifle', 'rfl': 'rifle', 'rifles': 'rifle', 'rflbde': 'rifle',
    'kradschutzen': 'krad', 'kradschuetzen': 'krad', 'gebergs': 'mountain', 'support': 'spt',
    'motor': 'mtr', 'motorized': 'mtr', 'rajputana': 'rajrf', 'rajput': 'rajpt', 'gurkha': 'grka',
    'coldstream': 'cldgds', 'royal': 'ryl', 'tank': 'tank', 'tanks': 'tank', 'lancers': 'lancr',
    'yeomanry': 'yeo', 'yeoman': 'yeo', 'lt': 'light', 'hy': 'heavy', 'sikh': 'skh', 'sikhs': 'skh',
    'punjab': 'pjb', 'baluch': 'bal', 'baluchis': 'bal', 'baluchies': 'bal', 'mahratta': 'mah',
    'fusiliers': 'fslr', 'fusilier': 'fslr', 'rfslr': 'fslr', 'essx': 'essex', 'grys': 'greys', 'grays': 'greys',
    'scotts': 'scots', 'sctsgry': 'scots greys', 'kings': 'king', "king's": 'king', 'own': 'own',
    'sherwood': 'frstrs', 'forresters': 'frstrs', 'foresters': 'frstrs', 'bersaglieri': 'brs', 'berg': 'brs',
    'heavy-weapons': 'hw', 'schwinf': 'hw', 'articelere': 'artc', 'raggruppamento': 'ar', 'ragruppamento': 'ar',
    'rgppmnto': 'ar', 'rha': 'rha', 'rtr': 'rtr', 'hq': 'hq', 'headquarters': 'hq', 'mg': 'mg',
}
# Expansions of the charts' compressed abbreviations, as words.
SPELL = {
    'laa': 'light aa', 'haa': 'heavy aa', 'nzfld': 'nz fld', 'afld': 'aus fld', 'infld': 'in fld',
    'grkfld': 'greek fld', 'auscav': 'aus cav', 'polcv': 'polish cav', 'kdgd': 'king dragoon gds',
    'deryeo': 'derbyshire yeo', 'thrf': 'tower hamlet rifle', 'sctgds': 'scots gds', 'cldgds': 'coldstream gds',
    'sostff': 'south staffordshires', 'rnf': 'ryl northumberland fslr', 'krrc': 'king ryl rifle corps',
    'kor': 'king own ryl regt', 'cih': 'central india horse', 'a&s': 'argyll sutherland',
    'dur': 'durham', 'durlt': 'durham light', 'mtr': 'mtr', 'freefr': 'free french', 'lgetr': 'legion',
    'nottyeo': 'nottingham yeo', 'stffyeo': 'staffordshire yeo', 'rwiyeo': 'ryl wiltshire yeo',
    'wkyeo': 'warwick yeo', 'bdbg': 'brandenburg', 'nvl': 'naval eng', 'le': 'light', 'af': 'afrika',
    'tst': 'trieste', 'trn': 'trento', 'pav': 'pavia', 'bol': 'bologna', 'bre': 'brescia', 'sav': 'savona',
    'cat': 'catanzaro', 'pist': 'pistoia', 'folg': 'folgore', 'sab': 'sabratha', 'artc': 'artc regt',
    'ggff': 'ggff', 'gaf': 'gaf', 'son': 'sonderverband', 'arko': 'arko', 'afr': 'afrika arty',
}
# Words that say what kind of unit it is, rather than which one: they count for less.
GENERIC = {'div', 'bde', 'regt', 'bn', 'coy', 'hq', 'inf', 'arty', 'unit', 'units', 'the', 'of', 'and', 'group',
           'ryl', 'light', 'heavy', 'fld', 'med', 'mtr', 'tank', 'armd', 'aa', 'at', 'recce', 'mg', 'eng', 'spt',
           'rifle', 'corps', 'cav', 'own', 'king', 'gds', 'regt', 'hus', 'detachment', 'det', 'battery', 'bty'}
ROMAN = re.compile(r'^(?=[ivxlcdm]+$)m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$')
TYPES = {'T': ('tank',), 'Ar': ('artillery',), 'AT': ('anti-tank',), 'AA': ('anti-air',), 'E': ('engineer', 'construction'),
         'R': ('recce', 'recon'), 'HQ': ('headquarters',), 'I': ('infantry',), 'TR': ()}
CLAUSES = ('less', 'assg', 'att', 'det', 'consists')


def words(s):
    s = s.lower().replace('’', "'").replace('"', ' ')
    s = re.sub(r'(\d+)(st|nd|rd|th|sth)\b', r'\1', s)
    s = re.sub(r'(\d)([a-z])', r'\1 \2', s)  # 1/1AR, 8Brs, 1Spt
    s = re.sub(r'\b([ivxl]+)\((l|m)\)', r'\1-\2', s)  # I(L), LII(M): the tank battalions
    out = []
    for w in re.findall(r"[a-z0-9&'/.-]+", s):
        w = w.strip("'.-")
        if not w:
            continue
        for part in SPELL.get(w, w).split():
            out.extend(SAME.get(part, part).split())
    return out


def is_key(w):
    """A word that names which unit: a number, a roman numeral, a compound (2/13)."""
    return bool(re.search(r'\d', w)) or bool(ROMAN.match(w.split('-')[0])) and len(w) > 0


def tokens(s):
    toks = set()
    for w in words(s):
        toks.add(w)
        if '/' in w:  # 2/13 matches 2/13, and 7 Spt/7 gives 7 and 7
            toks.update(p for p in w.split('/') if p)
    return toks


class Charts:
    def __init__(self):
        self.units, self.codes, self.sheet_of = {}, {}, {}
        for c in CHARTS:
            with open(DATA / 'units' / f'oa-{c}.json', encoding='utf-8') as f:
                oa = json.load(f)
            with open(DATA / 'tables' / f'units-{c}.json', encoding='utf-8') as f:
                self.codes[c] = json.load(f)['codes']
            for s in oa['sheets']:
                for u in s['units']:
                    self.units[u['id']] = {**u, 'chart': c, 'sheet': s, 'nat': u.get('nat', s['nat'])}
        for u in self.units.values():
            text = f'{u["name"]} {u["abbr"] or ""}'
            if not u.get('parent'):  # a formation's HQ also goes by the sheet's title
                text += ' ' + u['sheet']['title']
            u['tokens'] = tokens(text)
            u['keys'] = {w for w in words(f'{u["name"]} {u["abbr"] or ""}') if is_key(w)}
            u['type'] = self.codes[u['chart']][u['code']]['type'].lower()

    def chain(self, u):
        """The tokens of a unit's parents, up to the top of its sheet."""
        out = set()
        while u.get('parent'):
            u = self.units[u['parent']]
            out |= tokens(f'{u["name"]} {u["abbr"] or ""} {u["sheet"]["title"]}')
        return out | tokens(u['sheet']['title'])

    def propose(self, name, charts, nat=None, type_=None, parent=None, n=3):
        """The n likeliest OA units for a name: [(score, id)], best first."""
        want = tokens(name)
        keys = {w for w in words(name) if is_key(w)}
        weight = {w: (0.3 if w in GENERIC else 2.0 if is_key(w) else 1.0) for w in want}
        total = sum(weight.values()) or 1
        hint = tokens(parent) if parent else set()
        out = []
        for uid, u in self.units.items():
            if u['chart'] not in charts:
                continue
            if keys and not (keys & u['tokens']):
                continue  # the numbers must match
            score = sum(weight[w] for w in want & u['tokens']) / total
            if u['keys'] - keys - hint:
                score *= 0.8  # the counter has a number the name doesn't give
            if nat and u['nat'] != nat:
                score *= 0.7
            if type_ and TYPES.get(type_) and not any(t in u['type'] for t in TYPES[type_]):
                score *= 0.7
            if hint:
                score *= 1 + 0.3 * len(hint & self.chain(u)) / len(hint)
            if score > 0.2:
                out.append((round(score, 2), uid))
        out.sort(key=lambda x: -x[0])
        return out[:n]


def split_text(text):
    """A listing text's clauses: (parent designation or None, {clause: [names]}, the rest)."""
    parent, found, rest, kind = None, {}, [], None
    parts = [p.strip() for p in re.split(r';|\.\s', text) if p.strip()]
    for i, p in enumerate(parts):
        m = re.match(r'(?i)(less(?: its own)?|assg(?: in (?:its|their) places?)?|att|det|consists of)\s*:?\s*(.*)', p)
        if m:
            kind = m.group(1).lower().split()[0]
            p = m.group(2)
        elif kind and len(p) < 40:  # a list goes on past the semicolon
            pass
        elif i == 0 and len(p) < 16 and not re.search(r'(?i)toe|training|trucks', p):
            parent = p
            continue
        else:
            rest.append(p)
            kind = None
            continue
        # Bracketed designations go, but not a tank battalion's (L) or (M)
        names = re.split(r',\s*|\s+and\s+', re.sub(r'\[[^\]]*\]|\((?![LM]\))[^)]*\)', '', p))
        found.setdefault(kind, []).extend(x.strip() for x in names if x.strip())
    return parent, found, rest


def proposals(cat, charts, only=None):
    out = []
    for sid, su in cat['setups'].items():
        if only and sid != only:
            continue
        for i, e in enumerate(su['deploy']):
            for k, u in enumerate(e['units']):
                nat = u.get('nat') or e.get('nat')
                parent, clauses, rest = split_text(u.get('text', ''))
                side = SIDE_CHARTS[e['side']]
                p = {'setup': sid, 'deployment': i, 'unit': k, 'rule': e['rule'], 'name': u['name'],
                     'type': u['type'], 'text': u.get('text', ''), 'parent': parent, 'linked': u.get('oa'),
                     'oa': charts.propose(u['name'], side, nat, u['type'], parent),
                     'clauses': {c: [{'name': x, 'oa': charts.propose(x, side, None, None, None, 2)} for x in xs]
                                 for c, xs in clauses.items()}}
                if rest:
                    p['rest'] = rest
                out.append(p)
    return out


def show(props):
    for p in props:
        best = ', '.join(f'{uid} {s}' for s, uid in p['oa']) or '—'
        print(f'{p["setup"]} {p["deployment"]}.{p["unit"]} [{p["rule"]}] {p["name"]!r} ({p["type"]}'
              f'{"; " + p["parent"] if p["parent"] else ""}) -> {best}')
        if p['linked']:
            mark = '' if p['linked'] in {uid for _, uid in p['oa']} else ' !'
            print(f'    linked: {p["linked"]}{mark}')
        for c, xs in p['clauses'].items():
            for x in xs:
                print(f'    {c}: {x["name"]!r} -> {", ".join(f"{uid} {s}" for s, uid in x["oa"]) or "—"}')
        for r in p.get('rest', ()):
            print(f'    text: {r}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--setup', help='only this setup')
    ap.add_argument('--json', type=Path, help='also write the proposals to this file')
    args = ap.parse_args()
    with open(DATA / 'scenarios.json', encoding='utf-8') as f:
        cat = json.load(f)
    props = proposals(cat, Charts(), args.setup)
    show(props)
    if args.json:
        args.json.write_text(json.dumps(props, indent=1, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
