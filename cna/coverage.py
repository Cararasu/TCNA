"""Rule coverage: how much of the rulebook the program carries out.

Usage (from the project folder):
  python -m cna.coverage               every section: done, partly done, not needed, missing
  python -m cna.coverage --missing 8   the cases of Section 8 still missing
  python -m cna.coverage --show 7      every case of Section 7, with its status and what covers it

The items to cover are those of data/rules/cases.json: each case, each
subsection or section without cases, and each case the addenda add. The marks
come from cna.rules (implements, not_needed) in the modules of MODULES. A mark
naming a number that isn't in cases.json is an error, and the exit status is 1.
"""
import argparse
import importlib
import json
import pkgutil
import sys

from . import rules
from .paths import DATA

CASES = DATA / 'rules' / 'cases.json'
MODULES = ['cna.joined', 'cna.engine', 'cna.rules']  # packages are searched whole
GAMES = [('Introduction', 1, 5), ('Land Game', 6, 32), ('Air Game', 33, 47), ('Logistics Game', 48, 58),
         ('Scenarios', 59, 65)]
STATUSES = ('done', 'partly', 'not needed', 'missing')


def load_marks():
    for name in MODULES:
        mod = importlib.import_module(name)
        for info in pkgutil.walk_packages(getattr(mod, '__path__', []), f'{name}.'):
            importlib.import_module(info.name)
    return rules.MARKS


def load_cases():
    with open(CASES, encoding='utf-8') as f:
        return json.load(f)


def index(cases):
    """The items in order, and for each number (section, subsection, case or
    addendum heading) the items it stands for."""
    items, under = [], {}

    def add(item, *parents):
        items.append(item)
        for p in (*parents, item):
            under.setdefault(p, []).append(item)

    titles = {}
    for s in cases['sections']:
        titles[s['id']] = s['title']
        under.setdefault(s['id'], [])
        if not s['subsections']:
            add(s['id'])
        for u in s['subsections']:
            titles[u['id']] = u['title']
            if not u['cases']:
                add(u['id'], s['id'])
            for c in u['cases']:
                add(c, s['id'], u['id'])
    added = [a['case'] for a in cases['addenda'] if a['kind'] == 'addition']
    for a in added:
        if a in under:
            continue
        if any(b != a and b.startswith(a) for b in added):  # a heading: its added cases are the items
            under[a] = []
            titles[a] = '(added by the addenda)'
            continue
        parents = [p for p in (a.split('.')[0], a[:-1], *[b for b in added if b != a and a.startswith(b)])
                   if p in under]
        add(a, *dict.fromkeys(parents))
    return items, under, titles


def statuses(cases, marks):
    """Each item's status and the marks behind it; and the errors."""
    items, under, _ = index(cases)
    by = {i: [] for i in items}
    errors = []
    for m in marks:
        for c in m['cases']:
            if c not in under:
                errors.append(f'{m["where"]}: {c} is not a case in {CASES.name}')
                continue
            for i in under[c]:
                by[i].append(m)
    status = {}
    for i in items:
        kinds = {m['kind'] for m in by[i]}
        status[i] = next((k for k in STATUSES[:3] if k in kinds), 'missing')
        if 'not needed' in kinds and kinds & {'done', 'partly'}:
            errors.append(f'{i} is marked both as carried out and as needing no code')
    return status, by, errors


def section_of(item):
    return int(item.split('.')[0])


def counts(status, items):
    out = dict.fromkeys(STATUSES, 0)
    for i in items:
        out[status[i]] += 1
    return out


def row(name, n, c, width=46):
    cells = ''.join(f'{(c[k] or "-"):>{len(k) + 2}}' for k in STATUSES)
    return f'{name[:width]:<{width}}{n:>6}{cells}'


def report(cases, status, out=sys.stdout):
    items, _, titles = index(cases)
    head = f'{"":<46}{"items":>6}' + ''.join(f'  {k}' for k in STATUSES)
    total = counts(status, items)
    done = (total['done'] + total['not needed']) / len(items)
    print(f'Rule coverage: {len(items)} items, {total["done"]} done, {total["partly"]} partly, '
          f'{total["not needed"]} need no code, {total["missing"]} missing ({done:.0%} done or not needed)\n', file=out)
    print(head, file=out)
    for name, lo, hi in GAMES:
        mine = [i for i in items if lo <= section_of(i) <= hi]
        print(row(f'{name} ({lo}-{hi})', len(mine), counts(status, mine)), file=out)
    print(f'\n{head}', file=out)
    for s in cases['sections']:
        mine = [i for i in items if section_of(i) == int(s['id'])]
        print(row(f'{s["id"]:>2} {titles[s["id"]]}', len(mine), counts(status, mine)), file=out)


def detail(cases, status, by, section, only=None, out=sys.stdout):
    items, _, titles = index(cases)
    mine = [i for i in items if section_of(i) == section]
    if not mine:
        print(f'There is no Section {section}.', file=out)
        return
    print(f'Section {section}: {titles[str(section)]}', file=out)
    sub = None
    for i in mine:
        if only and status[i] != only:
            continue
        parent = next((t for t in (i[:-1], i) if t in titles and '.' in t), None)
        if parent and parent != sub:
            sub = parent
            print(f'  {parent} {titles[parent]}', file=out)
        where = '; '.join(m['where'] for m in by[i])
        print(f'    {i:<8}{status[i]:<12}{where}', file=out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--missing', type=int, metavar='SECTION', help="list the section's missing cases")
    ap.add_argument('--show', type=int, metavar='SECTION', help="list the section's cases with their status")
    a = ap.parse_args(argv)
    cases = load_cases()
    status, by, errors = statuses(cases, load_marks())
    if a.missing is not None:
        detail(cases, status, by, a.missing, only='missing')
    elif a.show is not None:
        detail(cases, status, by, a.show)
    else:
        report(cases, status)
    for e in errors:
        print(f'error: {e}', file=sys.stderr)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
