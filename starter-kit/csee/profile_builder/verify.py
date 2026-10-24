"""Guards on LLM output: every cited ID must exist; every key quote must be verbatim in its document."""

import difflib
import re

from .common import ID_RE, id_exists
from .sources import item_text

LIST_FIELDS_WITH_IDS = ("pressures", "likely_tradeables", "arguments_that_should_land")


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").replace("’", "'").replace("“", '"').replace("”", '"')).strip()


def repair_id(pkg, ref, known=()):
    """An ID as cited -> an existing ID, or None. Fixes trailing junk, '.md' suffixes, case and near-misses."""
    ref = (ref or "").strip().strip("`'\"()[],.;")
    ref = re.sub(r"\.md$", "", ref)
    if id_exists(pkg, ref):
        return ref
    for cand in (ref.lower(), ref.replace(" ", "")):
        if id_exists(pkg, cand):
            return cand
    pool = [k for k in known if k.split(":")[0] == ref.split(":")[0]]
    close = difflib.get_close_matches(ref, pool, n=1, cutoff=0.92)
    return close[0] if close else None


class Checker:
    def __init__(self, pkg, known=()):
        self.pkg = pkg
        self.known = list(known)
        self.log = []  # human-readable record of every repair / drop

    def ids(self, refs, where):
        out = []
        for r in refs or []:
            fixed = repair_id(self.pkg, r, self.known)
            if fixed is None:
                self.log.append(f"dropped unknown ID `{r}` in {where}")
            else:
                if fixed != r:
                    self.log.append(f"repaired ID `{r}` -> `{fixed}` in {where}")
                if fixed not in out:
                    out.append(fixed)
        return out

    def text(self, s, where):
        """Free text: unknown IDs mentioned inline are repaired or removed."""
        if not isinstance(s, str):
            return s

        def sub(m):
            fixed = repair_id(self.pkg, m.group(0), self.known)
            if fixed is None:
                self.log.append(f"removed unknown inline ID `{m.group(0)}` in {where}")
                return "[unverified]"
            return fixed

        return ID_RE.sub(sub, s)

    def entries(self, items, where, need_ids=True):
        """List of dicts with 'ids': check ids; an entry whose IDs were all invalid is dropped."""
        out = []
        for i, e in enumerate(items or []):
            if not isinstance(e, dict):
                continue
            had = list(e.get("ids") or [])
            e = {k: self.text(v, f"{where}[{i}].{k}") if isinstance(v, str) else v for k, v in e.items()}
            if "ids" in e or need_ids:
                e["ids"] = self.ids(had, f"{where}[{i}]")
                if need_ids and had and not e["ids"]:
                    self.log.append(f"dropped {where}[{i}] (no valid IDs left): {str(e)[:120]}")
                    continue
            out.append(e)
        return out

    def quotes(self, quotes, where="key_quotes"):
        """Keep a quote only if it is a verbatim substring of its document (whitespace-normalised).
        Near-verbatim quotes are repaired to the exact span of the document."""
        out = []
        for q in quotes or []:
            ref = repair_id(self.pkg, q.get("id"), self.known)
            quote = (q.get("quote") or "").strip().strip('"').strip()
            if not ref or not quote:
                self.log.append(f"dropped quote with unknown doc `{q.get('id')}`")
                continue
            doc = item_text(self.pkg, ref)
            if _norm(quote) in _norm(doc):
                # keep the document's own spelling
                start = _norm(doc).find(_norm(quote))
                out.append({"id": ref, "quote": _norm(doc)[start : start + len(_norm(quote))]})
                continue
            fixed = _closest_span(doc, quote)
            if fixed:
                self.log.append(f"repaired quote in {ref}: '{quote[:60]}' -> '{fixed[:60]}'")
                out.append({"id": ref, "quote": fixed})
            else:
                self.log.append(f"dropped non-verbatim quote in {ref}: '{quote[:80]}'")
        return out


def _closest_span(doc, quote, cutoff=0.88):
    """The sentence (or sentence pair) of `doc` closest to `quote`, if similar enough."""
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", _norm_keep_lines(doc)) if s.strip()]
    cands = sents + [f"{a} {b}" for a, b in zip(sents, sents[1:], strict=False)]
    best, score = None, 0.0
    for c in cands:
        r = difflib.SequenceMatcher(None, _norm(quote).lower(), _norm(c).lower()).ratio()
        if r > score:
            best, score = c, r
    return _norm(best) if best and score >= cutoff else None


def _norm_keep_lines(s):
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in (s or "").splitlines())


def all_ids_valid(pkg, obj):
    """IDs mentioned anywhere in obj that do not exist (for the final audit)."""
    from .common import ids_in

    return sorted(i for i in ids_in(obj) if not id_exists(pkg, i))
