"""List every rule of the rulebook by number, for the rule coverage report.

Usage (from the project folder, with the rulebook transcription present):
  python -I tools/rules/cases.py [--check]

Reads "The Campaign for North Africa.md" and writes data/rules/cases.json:

  sections     every section (8.0) with its subsections (8.2) and their cases
               (8.21; some cases have their own, 9.141), with the titles of
               sections and subsections
  addenda      the designers' clarifications and additions printed at the end
               of Section 32, by the case each amends
  charts       the charts and tables, by number
  gaps         numbers skipped in a run of cases and found nowhere in the
               transcription: check them against the printed rulebook

Only numbers and headings are written, no rule text, so the file can be
committed while the transcription stays local.

The transcription comes from OCR. Case markers are often merged into the
paragraph before them ("... of it. [14.43] The Player ...") or damaged
("({14.23]", "(S9.12]"), and a few numbers are misread; FIXES corrects those,
each confirmed by the gap it fills. Cases are grouped by their number, not by
where they appear, since the transcription sometimes mixes up the order of a
page's columns. --check lists anything that still does not fit.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULEBOOK = ROOT / 'The Campaign for North Africa.md'
OUT = ROOT / 'data' / 'rules' / 'cases.json'

# (section the marker is printed in, number as read) -> the number printed in the rulebook
FIXES = {
    ('9', '9.141'): '9.11',     # the first case after the 9.1 heading, before 9.12; no 9.141 exists
    ('10', '16.14'): '10.14',   # fills 10.13 -> 10.15
    ('10', '20.33'): '10.33',   # fills 10.32 -> 10.34
    ('11', '14.12'): '11.12',   # fills 11.11 -> 11.13
    ('20', '26.64'): '20.64',   # fills 20.63 -> 20.65
    ('47', '42.7'): '47.7',     # follows 47.6; "Bombardment of the Commonwealth Fleet", as 32.7
    ('47', '42.8'): '47.8',     # "Stacking Modifications", as 32.9
    ('47', '42.81'): '47.81',
    ('47', '42.82'): '47.82',
    ('56', '86.14'): '56.14',   # fills 56.13 -> 56.15
    ('59', '9.12'): '59.12',    # printed "(S9.12]"; follows 59.11
    ('59', '39.2'): '59.2',     # "How to Read the Scenario Set-ups", between 59.1 and 59.3
}

# Subsection titles the transcription garbles or lacks, from the printed rulebook.
TITLES = {
    '11.2': 'Capability Point Expenditures for Combat',  # heading split over two lines
    '15.5': "Effect of Assaulting Force's Organizational Size on Close Assault",  # "FORC Lal"
    '27.7': 'Commandos: Layforce',
    '51.2': 'Effects of Lack of Stores',  # no heading in the transcription; from the rulebook's contents
    # From the rulebook's contents page, where the headings are garbled:
    '10.3': 'ZOC Combat Requirements (Holding Off)',
    '13.2': 'How to Retreat Before Assault',
    '15.1': 'Which Units May Participate in Close Assault',
    '18.1': 'Which Units May Be Placed in Reserve',
    '19.1': 'Difference Between "Assigned" and "Attached" Units',
    '21.3': 'How Breakdown Is Determined',
    '44.2': 'Axis Air Raids on Malta',
    '50.1': 'Consumption of Ammunition',
    '53.1': 'First, Second, and Third-Line Trucks',
    '54.2': 'Truck Characteristics Chart',
}

# Cases the marker pattern cannot read, with how they are printed; each is
# added if the text has it.
UNMARKED = {
    '11.21': 'EXPENDITURES FOR COMBAT (11.21) A non-Phasing unit',  # in parentheses, after its heading
}

SECTION = re.compile(r'^## \[(\d+)\.0\] (.*)')
HEADING = re.compile(r'^#{3,4} \[(\d+\.\d+)\] ?(.*)')
# A case marker: [8.21] where a sentence starts, in bold or not, with OCR damage
# around the bracket: "({14.23]", "(S9.12]", "[412.15]" (a "(" read as 4: no
# section has three digits). A reference ("see Case 8.21") has no brackets.
MARKER = re.compile(r'(?:^|(?<=[\s.;:)]))(?:\*\*)?[({]*[S5]?\{?\[?(?:4(?=\d{2}\.\d))?(\d{1,2}\.\d{1,3})\](?:\*\*)? ?\**([^\n\[]{0,60})')
CHART_TITLE = re.compile(r'\b(CHART|TABLE|SCHEDULE)S?\b')
ADDENDUM = re.compile(r'^\((\w[\w ]*?)\)')
KIND = re.compile(r'\((addition|clarification|correction|change)\)', re.I)
CHART = re.compile(r'^#### \[(\d+\.\d+[A-Za-z]?)\] (.*)')
CONTENTS = re.compile(r'^ {2,4}- \[(\d+\.\d)\] (.*)')  # a subsection or chart in the Contents list


SMALL = {'a', 'an', 'and', 'as', 'at', 'by', 'for', 'from', 'in', 'into', 'of', 'on', 'or', 'the', 'to', 'vs', 'with'}


ACRONYMS = {'AA', 'CAP', 'CNA', 'CP', 'CPA', 'CRT', 'CW', 'HQ', 'II', 'III', 'LRDG', 'OA', 'POW', 'SAS', 'SGSU',
            'TEC', 'TOE', 'ZOC'}


def title(s):
    """A heading's upper-case words in Title Case, acronyms kept:
    "THE SEQUENCE OF PLAY (Land Game)" -> "The Sequence of Play (Land Game)";
    "ANTI-ARMOR COMBAT" -> "Anti-Armor Combat"."""
    s = re.sub(r'\s+', ' ', s.replace('*', '')).strip()

    def part(w, first):
        core = re.sub(r'[^A-Za-z]', '', w)
        if not core.isupper() or core in ACRONYMS:
            return w
        w = w.lower()
        if not first and core.lower() in SMALL:
            return w
        k = next((j for j, ch in enumerate(w) if ch.isalpha()), 0)
        return w[:k] + w[k].upper() + w[k + 1:]
    words, out = s.split(' '), []
    for i, w in enumerate(words):
        first = i == 0 or words[i - 1].endswith(':')  # "Group One: The Italians"
        out.append('-'.join(part(p, first or j > 0) for j, p in enumerate(w.split('-'))))
    return ' '.join(out)


def marker_title(rest):
    """A subsection's title from the text after its bold marker, if it has one.

    The title is the run of upper-case words, and after a colon the words in
    Title Case that follow: "**[16.6]** PATROL SURVIVAL TABLE (see Charts and
    Tables)" -> "Patrol Survival Table"; "COMMANDOS: The Special Air Service
    Brigade" -> "Commandos: The Special Air Service Brigade". A heading run into
    its first sentence ("THE ITALIAN PASTA RULE One of the ...") keeps the
    heading. A marker followed by a sentence has no title.
    """
    t = re.split(r'\s*\(see\b|\s*\[\d', rest.replace('*', ''), maxsplit=1)[0]
    words = re.sub(r'\s*\((Air|Logistics|Land) Game[^)]*\)?', '', t).split()
    letters = lambda w: re.sub(r'[^A-Za-z]', '', w)  # noqa: E731
    head = []
    for w in words:
        if letters(w).isupper() and (len(letters(w)) > 1 or head):
            head.append(w)
        else:
            break
    if not head:
        return None
    tail = []
    if head[-1].endswith(':'):
        for w in words[len(head):]:
            if not letters(w)[:1].isupper():
                break
            tail.append(w)
    return ' '.join([title(' '.join(head))] + tail).strip(' .:') or None


def section_of(num):
    return num.split('.')[0]


def subsection_of(num):
    a, b = num.split('.')
    return f'{a}.{b[0]}'


def read(lines):
    """Every marker in the rules (Sections 1-65), classified."""
    sections, found, headings, addenda, charts, problems = {}, {}, {}, [], [], []
    contents = {m.group(1): title(m.group(2)) for m in map(CONTENTS.match, lines) if m}
    sec, in_addenda, in_charts = None, False, False
    for n, line in enumerate(lines, 1):
        if line.startswith('## Counter Sheets'):
            in_charts = True
        if in_charts:
            m = CHART.match(line)
            if m:
                charts.append({'id': m.group(1), 'title': title(m.group(2))})
            continue
        m = SECTION.match(line)
        if m:
            sec, in_addenda = m.group(1), False
            sections[sec] = title(m.group(2))
            continue
        if sec is None or line.startswith('<!--'):
            continue
        if line.strip() == 'ADDENDA':
            in_addenda = True
            continue
        h = HEADING.match(line)
        marks = [(h.group(1), h.group(2), True)] if h else [(m.group(1), m.group(2), False) for m in MARKER.finditer(line)]
        for num, rest, is_heading in marks:
            num = FIXES.get((sec, num), num)
            if num.endswith('.0') and not in_addenda:
                continue  # a reference to a whole section
            if in_addenda:
                # The kind is printed in parentheses: "(clarification) ..." or "LIMITED
                # INTELLIGENCE (addition)"; the cases of an added subsection are additions too.
                a = ADDENDUM.match(rest.strip()) or KIND.search(rest)
                kind = a.group(1).lower() if a else None
                parent = next((x for x in reversed(addenda) if num.startswith(x['case']) and x['case'] != num), None)
                if kind is None and parent and parent['kind'] == 'addition':
                    kind = 'addition'
                addenda.append({'case': num, 'kind': kind})
                continue
            if section_of(num) != sec:
                if CHART_TITLE.search(rest.upper()) and (is_heading or rest.isupper() or '**' in line):
                    charts.append({'id': num, 'title': title(rest)})  # a chart page printed among the rules
                else:
                    problems.append(f'line {n}: [{num}] in Section {sec}: {line[:70]}')
                continue
            if is_heading or len(num.split('.')[1]) == 1:
                if is_heading or not headings.get(num):
                    headings[num] = title(rest) if is_heading else marker_title(rest)
            found.setdefault(num, n)
    text = '\n'.join(lines)
    for num, printed in UNMARKED.items():
        if printed in text:
            found.setdefault(num, None)
        else:
            problems.append(f'[{num}] is no longer printed as {printed!r}')
    # Subsections without a heading of their own take their title from the Contents.
    for num in headings:
        headings[num] = headings[num] or contents.get(num)
    headings.update(TITLES)
    return sections, found, headings, addenda, charts, problems


def build(sections, found, headings):
    """The hierarchy by number: section -> subsection -> cases (-> sub-cases)."""
    out = []
    by_section = {s: {} for s in sections}
    for num in found:
        a, b = num.split('.')
        if len(b) == 1:
            by_section[a].setdefault(num, [])
        else:
            by_section[a].setdefault(subsection_of(num), []).append(num)
    key = lambda num: [int(x) for x in num.split('.')[0:1]] + [int(d) for d in num.split('.')[1]]  # noqa: E731
    for s, t in sections.items():
        subs = [{'id': sub, 'title': headings.get(sub), 'cases': sorted(cases, key=key)}
                for sub, cases in sorted(by_section[s].items(), key=lambda kv: key(kv[0]))]
        out.append({'id': s, 'title': t, 'subsections': subs})
    return out


def gaps(sections, text):
    """Numbers skipped in a run of cases that appear nowhere in the text."""
    out = []
    for sec in sections:
        for sub in sec['subsections']:
            two = sorted(int(c.split('.')[1]) for c in sub['cases'] if len(c.split('.')[1]) == 2)
            # A run starts at the subsection's first case: 8.2 -> 8.21.
            first = int(sub['id'].split('.')[1]) * 10
            two = [first] + two if two and two[0] != first + 1 else two
            for a, b in zip(two, two[1:]):
                for k in range(a + 1, b):
                    num = f'{sec["id"]}.{k}'
                    if not re.search(rf'(?<![\d.]){re.escape(num)}(?!\d)', text):
                        out.append(num)
                    else:
                        out.append(num + '?')  # mentioned, but not found as a case: look at it
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--check', action='store_true', help='only report problems; write nothing')
    a = ap.parse_args()
    if not RULEBOOK.exists():
        sys.exit(f'{RULEBOOK.name} is not in the project folder')
    text = RULEBOOK.read_text(encoding='utf-8')
    sections, found, headings, addenda, charts, problems = read(text.split('\n'))
    tree = build(sections, found, headings)
    missing = gaps(tree, text[:text.index('## Counter Sheets')])
    for p in problems:
        print(p)
    if missing:
        print('gaps:', ' '.join(missing))
    n_subs = sum(len(s['subsections']) for s in tree)
    n_cases = sum(len(u['cases']) for s in tree for u in s['subsections'])
    print(f'{len(tree)} sections, {n_subs} subsections, {n_cases} cases, {len(addenda)} addenda, '
          f'{len(charts)} charts; {len(problems)} problems, {len(missing)} gaps')
    if a.check:
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        json.dump({'about': 'Every section, subsection and case of the CNA rules by number, with the titles of '
                            'sections and subsections; the addenda by the case they amend; the charts and '
                            'tables; and numbers skipped in the transcription. Generated by '
                            'tools/rules/cases.py from the rulebook transcription; no rule text.',
                   'sections': tree, 'addenda': addenda,
                   'charts': sorted({c['id']: c for c in charts}.values(), key=lambda c: c['id']),
                   'gaps': [g.rstrip('?') for g in missing]}, f, indent=1, ensure_ascii=False)
        f.write('\n')
    print(f'wrote {OUT.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
