"""Rule text from the local rulebook transcription, when it is present.

The transcription is copyrighted and kept out of version control; without
it the game names the cases it cites but cannot show their text.
"""
import re
import threading

from .paths import RULEBOOK

_CACHE = (None, None)  # (mtime, lines)
_LOCK = threading.Lock()


def available():
    return RULEBOOK.exists()


def _lines():
    global _CACHE
    mtime = RULEBOOK.stat().st_mtime_ns
    with _LOCK:
        if _CACHE[0] != mtime:
            _CACHE = (mtime, RULEBOOK.read_text(encoding='utf-8').split('\n'))
        return _CACHE[1]


def rule_text(case):
    """The text of a rulebook section or case (e.g. 60.8 or 60.81) as Markdown, or None.

    A section (### [60.8]) runs to the next heading of its level or above; a
    case (**[60.81]**) to the next case or heading.
    """
    if not available():
        return None
    lines = _lines()
    tag = f'[{case}]'
    for i, line in enumerate(lines):
        head = re.match(r'(#+) \[', line)
        if head and line[len(head.group(1)) + 1:].startswith(tag):
            level = len(head.group(1))
            stop = lambda s: (m := re.match(r'(#+) ', s)) and len(m.group(1)) <= level  # noqa: E731
            break
        if line.startswith(f'**{tag}'):
            stop = lambda s: s.startswith('**[') or s.startswith('#')  # noqa: E731
            break
    else:
        return None
    end = next((k for k in range(i + 1, len(lines)) if stop(lines[k])), len(lines))
    body = [s for s in lines[i:end] if not s.startswith('<!--')]
    return '\n'.join(body).strip()
