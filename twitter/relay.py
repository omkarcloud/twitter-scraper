"""Reader for the Relay store that x.com's logged-out server-rendered pages
(the new "x-web" app: /<user>, /<user>/status/<id>, /i/communities/<id>)
inline into their HTML.

The data is NOT JSON. TanStack Router streams it as a JavaScript literal
with shared-reference bookkeeping:

    ($R=>$R[66].next($R[68]={relayRecords:$R[69]={"client:root":$R[70]={
        __id:"client:root",__typename:"__Root",
        "user_result_by_screen_name(safety_level:\\"UserScopedTimeline\\",screen_name:\\"elonmusk\\")":$R[71]={__ref:"VXNlclJlc3VsdHM6NDQxOTYzOTc="}},
      ...}}))($R["tsr"])

  * `$R[n]=<value>` defines slot n while producing the value; a bare `$R[n]`
    later is a back-reference to that same object
  * keys are bare identifiers or double-quoted strings
  * booleans are `!0` / `!1`, `void 0` is undefined, plus null / numbers /
    strings / arrays / objects
  * records link to each other through {__ref: "<id>"} and
    {__refs: ["<id>", ...]}, and a field that took GraphQL arguments is
    stored under "<field>(<args>)"

`parse_literal(text, pos)` is a small recursive-descent parser for that
subset; `page_records(html)` finds every `relayRecords:` store in a page
and merges them; `materialize(records, root_id)` follows the refs and
strips the argument suffixes so the result looks like an ordinary GraphQL
response object (user.core.screen_name, tweet.legacy.full_text, ...), which
lets the same normalizers serve the SSR pages and the GraphQL endpoints.
The router's loader data (`$_TSR.router=...` with the same `$R[n]=`
notation) is read by `router_matches(html)`.
"""
import re

_WS = " \t\r\n"
_IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_NUM_RE = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_SLOT_RE = re.compile(r"\$R\[(\d+)\]")
_ARGS_RE = re.compile(r"^([A-Za-z0-9_]+)\(.*\)$", re.S)

UNDEFINED = object()


class Missing:
    """A `$R[n]` back-reference to a slot this parse never saw (the page
    defined it in an earlier stream chunk); behaves like nothing."""

    def __repr__(self):
        return "<missing>"


class LiteralParser:
    def __init__(self, text, slots=None):
        self.text = text
        self.slots = slots if slots is not None else {}

    def _skip(self, pos):
        text = self.text
        n = len(text)
        while pos < n and text[pos] in _WS:
            pos += 1
        return pos

    def value(self, pos):
        """Parse one value at `pos` -> (value, end)."""
        text = self.text
        pos = self._skip(pos)
        if pos >= len(text):
            raise ValueError("unexpected end of literal")
        ch = text[pos]
        if ch == "$":
            slot = _SLOT_RE.match(text, pos)
            if slot:
                key = int(slot.group(1))
                end = self._skip(slot.end())
                if end < len(text) and text[end] == "=" and text[end + 1: end + 2] != "=":
                    # definition: $R[n]=<value>. Objects/arrays are registered
                    # before their body is parsed so self-references resolve.
                    inner = self._skip(end + 1)
                    if inner < len(text) and text[inner] in "{[":
                        container = {} if text[inner] == "{" else []
                        self.slots[key] = container
                        if text[inner] == "{":
                            _, after = self.obj(inner, into=container)
                        else:
                            _, after = self.arr(inner, into=container)
                        return container, after
                    value, after = self.value(inner)
                    self.slots[key] = value
                    return value, after
                return self.slots.get(key, Missing()), end
            ident = _IDENT_RE.match(text, pos)
            if ident:
                return ident.group(0), ident.end()
        if ch == "{":
            return self.obj(pos)
        if ch == "[":
            return self.arr(pos)
        if ch == '"' or ch == "'":
            return self.string(pos)
        if ch == "!":
            nxt = text[pos + 1: pos + 2]
            if nxt == "0":
                return True, pos + 2
            if nxt == "1":
                return False, pos + 2
        num = _NUM_RE.match(text, pos)
        if num and (ch.isdigit() or ch in "-."):
            raw = num.group(0)
            try:
                return (float(raw) if any(c in raw for c in ".eE") else int(raw)), num.end()
            except ValueError:
                pass
        ident = _IDENT_RE.match(text, pos)
        if ident:
            word = ident.group(0)
            end = ident.end()
            if word == "null":
                return None, end
            if word == "true":
                return True, end
            if word == "false":
                return False, end
            if word == "void":
                nxt = self._skip(end)
                num = _NUM_RE.match(text, nxt)
                return UNDEFINED, (num.end() if num else nxt)
            if word == "undefined" or word == "NaN" or word == "Infinity":
                return UNDEFINED, end
            return word, end
        raise ValueError(f"unexpected character {ch!r} at {pos}")

    def string(self, pos):
        text = self.text
        quote = text[pos]
        pos += 1
        out = []
        n = len(text)
        while pos < n:
            ch = text[pos]
            if ch == quote:
                return "".join(out), pos + 1
            if ch == "\\":
                nxt = text[pos + 1]
                if nxt == "u":
                    code = int(text[pos + 2: pos + 6], 16)
                    pos += 6
                    # surrogate pair
                    if 0xD800 <= code <= 0xDBFF and text[pos: pos + 2] == "\\u":
                        low = int(text[pos + 2: pos + 6], 16)
                        if 0xDC00 <= low <= 0xDFFF:
                            code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)
                            pos += 6
                    out.append(chr(code))
                    continue
                if nxt == "x":
                    out.append(chr(int(text[pos + 2: pos + 4], 16)))
                    pos += 4
                    continue
                out.append({"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "0": "\0",
                            "v": "\v"}.get(nxt, nxt))
                pos += 2
                continue
            out.append(ch)
            pos += 1
        raise ValueError("unterminated string")

    def obj(self, pos, into=None):
        text = self.text
        out = {} if into is None else into
        pos = self._skip(pos + 1)
        while pos < len(text):
            if text[pos] == "}":
                return out, pos + 1
            if text[pos] in '"\'':
                key, pos = self.string(pos)
            else:
                ident = _IDENT_RE.match(text, pos)
                if not ident:
                    num = _NUM_RE.match(text, pos)
                    if not num:
                        raise ValueError(f"bad object key at {pos}")
                    key, pos = num.group(0), num.end()
                else:
                    key, pos = ident.group(0), ident.end()
            pos = self._skip(pos)
            if text[pos] != ":":
                raise ValueError(f"expected ':' at {pos}")
            value, pos = self.value(pos + 1)
            if value is not UNDEFINED:
                out[key] = value
            pos = self._skip(pos)
            if text[pos] == ",":
                pos = self._skip(pos + 1)
        raise ValueError("unterminated object")

    def arr(self, pos, into=None):
        text = self.text
        out = [] if into is None else into
        pos = self._skip(pos + 1)
        while pos < len(text):
            if text[pos] == "]":
                return out, pos + 1
            if text[pos] == ",":
                out.append(None)
                pos = self._skip(pos + 1)
                continue
            value, pos = self.value(pos)
            out.append(None if value is UNDEFINED else value)
            pos = self._skip(pos)
            if text[pos] == ",":
                pos = self._skip(pos + 1)
        raise ValueError("unterminated array")


def parse_literal(text, pos=0, slots=None):
    """Parse the JS value starting at `pos` -> (value, end)."""
    return LiteralParser(text, slots).value(pos)


_SCRIPT_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.S)
_RECORDS_MARK = "relayRecords:"
_ROUTER_MARK = "$_TSR.router="


def page_records(html):
    """Every Relay record in a page's inline scripts, merged into one
    {record id: record dict} store (later chunks win)."""
    records = {}
    slots = {}
    for script in _SCRIPT_RE.findall(html):
        start = 0
        while True:
            idx = script.find(_RECORDS_MARK, start)
            if idx < 0:
                break
            try:
                store, end = parse_literal(script, idx + len(_RECORDS_MARK), slots)
            except (ValueError, IndexError):
                break
            if isinstance(store, dict):
                for rid, rec in store.items():
                    # a page streams several stores; client:root (and any
                    # shared record) is merged, not replaced
                    if isinstance(rec, dict) and isinstance(records.get(rid), dict):
                        merged = dict(records[rid])
                        merged.update(rec)
                        records[rid] = merged
                    else:
                        records[rid] = rec
            start = end
    return records


def router_matches(html):
    """The TanStack router's loader data for the page: a list of
    {i: route id, l: loader data, b: ...} dicts (empty when absent). Only
    the `matches:` array is parsed — the rest of the router literal holds
    stream plumbing with function bodies."""
    for script in _SCRIPT_RE.findall(html):
        idx = script.find(_ROUTER_MARK)
        if idx < 0:
            continue
        pos = script.find("matches:", idx)
        if pos < 0:
            continue
        try:
            matches, _ = parse_literal(script, pos + len("matches:"))
        except (ValueError, IndexError):
            continue
        return [m for m in (matches or []) if isinstance(m, dict)]
    return []


def field_name(key):
    """'timeline(cards_platform:"Web-12",count:20)' -> 'timeline'."""
    match = _ARGS_RE.match(key)
    return match.group(1) if match else key


def materialize(records, node, _depth=0, _seen=None):
    """Follow __ref / __refs links from `node` (a record id or a record) and
    return plain nested dicts/lists with argument suffixes stripped from the
    keys. Cycles are cut (a node already on the current path becomes its
    bare __id string)."""
    if _depth > 60:
        return None
    if _seen is None:
        _seen = set()
    if isinstance(node, str):
        record = records.get(node)
        if record is None:
            return None
        return materialize(records, record, _depth, _seen)
    if isinstance(node, list):
        # plain strings in a list are data (edit_tweet_ids, facepile urls),
        # not record ids — Relay links plural records through __refs
        return [item if isinstance(item, str) else materialize(records, item, _depth + 1, _seen)
                for item in node]
    if not isinstance(node, dict):
        return node if not isinstance(node, Missing) else None
    if "__ref" in node and len(node) == 1:
        ref = node["__ref"]
        if ref in _seen:
            # a cycle (a user's timeline -> its tweets -> their author = the
            # same user): re-expand the node shallowly (~10 levels, enough for
            # core/avatar/counts) instead of following its timeline again
            return materialize(records, ref, max(_depth, 50), _seen)
        return materialize(records, ref, _depth + 1, _seen | {ref})
    if "__refs" in node and len(node) == 1:
        out = []
        for ref in node["__refs"] or []:
            if ref in _seen:
                out.append(materialize(records, ref, max(_depth, 50), _seen))
            else:
                out.append(materialize(records, ref, _depth + 1, _seen | {ref}))
        return out
    out = {}
    for key, value in node.items():
        if key in ("__id",):
            continue
        name = field_name(key)
        if isinstance(value, (dict, list)):
            value = materialize(records, value, _depth + 1, _seen)
        elif isinstance(value, Missing):
            value = None
        # a field that appears both bare and with args: prefer the richer one
        if name in out and isinstance(out[name], dict) and isinstance(value, dict):
            merged = dict(out[name])
            merged.update(value)
            value = merged
        out[name] = value
    return out


def records_of_type(records, typename):
    """Record ids whose __typename is `typename`, in page order."""
    return [rid for rid, rec in records.items()
            if isinstance(rec, dict) and rec.get("__typename") == typename]


def root(records):
    """The materialized client:root, i.e. the page's query result."""
    return materialize(records, "client:root") or {}
