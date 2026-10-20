"""Rule coverage: which cases of the rulebook the program carries out.

  @implements('7.11')                   the function or class that carries out these cases
  @implements('59.2', partial=True)     carries out part of them; the rest comes later
  implements('4.26', where='...')       the same, for code that isn't a Python function
  not_needed('2.4', why='...')          a case that needs no code, and why

A number names a section ('1'), a subsection ('5.2') or a case ('7.11'); a
section or subsection stands for everything in it. python -m cna.coverage
checks the numbers against data/rules/cases.json and reports, section by
section, what is done and what is still missing.
"""
MARKS = []  # {'cases': (number, ...), 'kind': 'done' | 'partly' | 'not needed', 'where': text}


def implements(*cases, partial=False, where=None):
    kind = 'partly' if partial else 'done'
    if where is not None:
        MARKS.append({'cases': cases, 'kind': kind, 'where': where})
        return lambda fn: fn

    def mark(fn):
        MARKS.append({'cases': cases, 'kind': kind, 'where': f'{fn.__module__}.{fn.__qualname__}'})
        return fn
    return mark


def not_needed(*cases, why):
    MARKS.append({'cases': cases, 'kind': 'not needed', 'where': why})
