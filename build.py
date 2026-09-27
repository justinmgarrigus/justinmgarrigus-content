# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "markdown-it-py>=4.2,<5",
#     "mdit-py-plugins>=0.6.1,<0.7",
# ]
# ///
"""
Compiles the content repository into a static site.

    uv run build.py                      # build into _site/ (first [sites] entry)
    uv run build.py --site sophiegarrigus.github.io --serve   # preview another
    uv run build.py --out ../justinmgarrigus.github.io        # publish

One content repo serves several hostnames, each with its own name: see
[sites] in site.toml. A publish picks the site from the output folder's name
(which is the hostname), so each published repo has only its own name in it.

Dependencies are declared in the "# /// script" block above; uv installs
them into its own cache on first run, pinned by build.py.lock.

Inputs (all relative to this file):

    site.toml       site-wide settings: title, nav, sidebar, theme colors
    pages/**/*.md   one page each; TOML front matter between "+++" lines
    data/*.toml     structured lists (news, publications, 88x31 buttons) that
                    pages pull in with shortcodes like {{ news }}
    static/         copied verbatim to the root of the output
    theme/          layout.html (page skeleton), style.css, sparkle.js

Page URLs are "pretty": pages/research.md -> /research/index.html, while
pages/index.md -> /index.html and pages/404.md -> /404.html (GitHub Pages
serves that one for missing URLs).

See README.md for the Markdown extensions (effects, containers, shortcodes).
"""

import argparse
import html
import http.server
import os
import re
import shlex
import shutil
import socketserver
import subprocess
import sys
import tomllib
from datetime import date, datetime, timedelta
from functools import partial
from pathlib import Path

from markdown_it import MarkdownIt
from mdit_py_plugins.anchors import anchors_plugin
from mdit_py_plugins.attrs import attrs_block_plugin, attrs_plugin
from mdit_py_plugins.container import container_plugin
from mdit_py_plugins.footnote import footnote_plugin

ROOT = Path(__file__).resolve().parent
PAGES = ROOT / "pages"
DATA = ROOT / "data"
STATIC = ROOT / "static"
SITE_STATIC = ROOT / "static-sites"     # static-sites/<hostname>/..., per site
THEME = ROOT / "theme"

# Files in the publish target that a publish never deletes.
ALWAYS_KEEP = {".git", "CNAME", ".nojekyll", "README.md"}


class BuildError(Exception):
    pass


# --------------------------------------------------------------------------
# Loading content
# --------------------------------------------------------------------------

def load_toml(path: Path) -> dict:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise BuildError(f"{path.relative_to(ROOT)}: {e}") from None


def load_data() -> dict:
    """Every data/NAME.toml becomes data[NAME]."""
    return {p.stem: load_toml(p) for p in sorted(DATA.glob("*.toml"))}


def split_front_matter(path: Path) -> tuple[dict, str]:
    """
    Splits "+++\\n<toml>\\n+++\\n<markdown>" into (meta, markdown). Front
    matter is optional.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("+++"):
        return {}, text
    try:
        _, fm, body = text.split("+++", 2)
    except ValueError:
        raise BuildError(f"{path.relative_to(ROOT)}: unclosed +++ front matter")
    try:
        return tomllib.loads(fm), body
    except tomllib.TOMLDecodeError as e:
        raise BuildError(f"{path.relative_to(ROOT)}: front matter: {e}") from None


def output_path(md_path: Path) -> Path:
    """pages/a/b.md -> a/b/index.html; index.md and 404.md stay flat."""
    rel = md_path.relative_to(PAGES).with_suffix("")
    if rel.name == "index":
        return rel.parent / "index.html"
    if rel.name == "404" and rel.parent == Path("."):
        return Path("404.html")
    return rel / "index.html"


def url_for(out: Path) -> str:
    url = "/" + out.as_posix()
    return url[: -len("index.html")] if url.endswith("/index.html") else url


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------

# What counts as "the site changed" for the site-wide Updated date.
CONTENT = ["pages", "data", "static", "static-sites", "site.toml"]


def parse_date(value, where: str) -> tuple[date, str]:
    """
    Accepts a TOML date or a string like "2026-01-15", "2026-01",
    "January 15, 2026" or "January 2026". Returns (date, display text);
    month-only dates count as the 1st and display as "January 2026".
    """
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value, f"{value:%B} {value.day}, {value.year}"
    text = str(value).strip()
    for fmt, precise in (("%Y-%m-%d", True), ("%B %d, %Y", True),
                         ("%Y-%m", False), ("%B %Y", False)):
        try:
            d = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        return d, (f"{d:%B} {d.day}, {d.year}" if precise else f"{d:%B %Y}")
    raise BuildError(f'{where}: can\'t read date "{text}" (try 2026-01-15, '
                     f'2026-01, "January 15, 2026" or "January 2026")')


def last_changed(paths: list[Path]) -> date:
    """
    When any of these files/directories last changed: the newest git commit
    touching them, or the modification time of any with uncommitted edits.
    Outside git, just the newest modification time (unreliable after a
    fresh clone, which resets them all).
    """
    rel = [str(p.relative_to(ROOT)) for p in paths if p.exists()]

    def mtime(p: Path) -> date:
        return datetime.fromtimestamp(p.stat().st_mtime).date()

    def git(*args) -> str:
        return subprocess.run(["git", *args, "--", *rel], cwd=ROOT, check=True,
                              capture_output=True, text=True).stdout

    try:
        committed = git("log", "-1", "--format=%cs").strip()
        dirty = git("status", "--porcelain", "--untracked-files=all").splitlines()
    except (OSError, subprocess.CalledProcessError):
        files = [f for p in paths if p.exists()
                 for f in ([p] if p.is_file() else p.rglob("*")) if f.is_file()]
        return max(map(mtime, files), default=date.today())

    dates = [date.fromisoformat(committed)] if committed else []
    for line in dirty:
        f = ROOT / line[3:].split(" -> ")[-1].strip('"')
        dates.append(mtime(f) if f.exists() else date.today())   # deleted: today
    return max(dates, default=date.today())


def display_date(d: date) -> str:
    return f"{d:%B} {d.day}, {d.year}"


# --------------------------------------------------------------------------
# Markdown: {.class} attributes on headings
# --------------------------------------------------------------------------

# "## News {.blink-colors #news}" -- only if the braces start with . or # or
# key=, so ordinary text ending in "}" (or a "{{ shortcode }}") is untouched.
HEADING_ATTRS = re.compile(r"\s*(?<!\{)\{\s*((?:[.#]|[\w-]+=)[^{}]*)\}\s*$")


def parse_attrs(spec: str) -> dict:
    attrs, classes = {}, []
    for part in shlex.split(spec):
        if part.startswith("."):
            classes.append(part[1:])
        elif part.startswith("#"):
            attrs["id"] = part[1:]
        elif "=" in part:
            k, v = part.split("=", 1)
            attrs[k] = v
    if classes:
        attrs["class"] = " ".join(classes)
    return attrs


def heading_attrs_rule(state):
    tokens = state.tokens
    for i, tok in enumerate(tokens):
        if tok.type != "heading_open":
            continue
        inline = tokens[i + 1]
        m = HEADING_ATTRS.search(inline.content)
        if not m:
            continue
        inline.content = inline.content[: m.start()]
        for k, v in parse_attrs(m[1]).items():
            if k == "class":
                tok.attrJoin("class", v)
            else:
                tok.attrSet(k, v)


# --------------------------------------------------------------------------
# Markdown: shortcodes, "{{ name arg key=value }}"
# --------------------------------------------------------------------------

SHORTCODES = {}


def shortcode(fn):
    SHORTCODES[fn.__name__] = fn
    return fn


def run_shortcode(source: str, env: dict) -> str:
    try:
        name, *parts = shlex.split(source)
    except ValueError as e:
        raise BuildError(f"{env['page_src']}: bad shortcode {{{{ {source} }}}}: {e}")
    fn = SHORTCODES.get(name)
    if fn is None:
        raise BuildError(
            f"{env['page_src']}: unknown shortcode {{{{ {name} }}}} "
            f"(have: {', '.join(sorted(SHORTCODES))})")
    args = [p for p in parts if "=" not in p]
    kwargs = dict(p.split("=", 1) for p in parts if "=" in p)
    try:
        return fn(env, *args, **kwargs)
    except TypeError as e:
        raise BuildError(f"{env['page_src']}: {{{{ {source} }}}}: {e}") from None


def shortcode_inline(state, silent):
    if not state.src.startswith("{{", state.pos):
        return False
    end = state.src.find("}}", state.pos + 2)
    if end < 0:
        return False
    if not silent:
        tok = state.push("shortcode", "", 0)
        tok.content = state.src[state.pos + 2 : end].strip()
    state.pos = end + 2
    return True


def shortcode_block(state, start, end, silent):
    """A shortcode alone on its line renders without a wrapping <p>."""
    if state.sCount[start] - state.blkIndent >= 4:
        return False
    line = state.src[state.bMarks[start] + state.tShift[start] : state.eMarks[start]]
    line = line.strip()
    if not (line.startswith("{{") and line.endswith("}}")) or "}}" in line[2:-2]:
        return False
    if silent:
        return True
    tok = state.push("shortcode", "", 0)
    tok.content = line[2:-2].strip()
    tok.block = True
    tok.map = [start, start + 1]
    state.line = start + 1
    return True


def render_shortcode(self, tokens, idx, options, env):
    # "inline" tells shortcodes whether they sit inside a line of text.
    out = run_shortcode(tokens[idx].content, {**env, "inline": not tokens[idx].block})
    return out + "\n" if tokens[idx].block else out


# --------------------------------------------------------------------------
# Markdown: ::: containers
# --------------------------------------------------------------------------

def container_args(tokens, idx, name):
    return tokens[idx].info.strip()[len(name):].strip()


def render_box(self, tokens, idx, options, env):
    """::: box Optional Title  ->  a Windows-95-style window."""
    if tokens[idx].nesting == -1:
        return "</div></div>\n"
    title = container_args(tokens, idx, "box")
    bar = (f'<div class="box-title"><span>{md_inline(title, env)}</span>'
           f'<span class="box-buttons" aria-hidden="true">'
           f'<i>_</i><i>&#9633;</i><i>&times;</i></span></div>') if title else ""
    return f'<div class="box">{bar}<div class="box-body">\n'


MARQUEE_SPEED = 80   # pixels per second


def render_marquee(self, tokens, idx, options, env):
    """
    ::: marquee [SPEED]  ->  scrolling text at SPEED pixels/second (default
    80), however much text there is. sparkle.js sets the exact duration from
    the measured width; the duration written here is a no-JS estimate.
    """
    if tokens[idx].nesting == -1:
        return "</div></div>\n"
    arg = container_args(tokens, idx, "marquee")
    try:
        speed = float(arg) if arg else MARQUEE_SPEED
        assert speed > 0
    except (ValueError, AssertionError):
        raise BuildError(f"{env['page_src']}: '::: marquee {arg}': give a speed in "
                         f"pixels per second, e.g. '::: marquee 80'") from None
    # Estimate: a ~700px box plus the text, at ~0.6em (9.6px) per monospace
    # character.
    chars = 0
    for tok in tokens[idx + 1:]:
        if tok.type == "container_marquee_close":
            break
        if tok.type == "inline":   # count what shows: one per &entity;, no tags
            chars += len(re.sub(r"<[^>]*>", "", re.sub(r"&#?\w+;", "x", tok.content)))
    duration = (700 + chars * 9.6) / speed
    return (f'<div class="marquee" data-speed="{speed:g}" '
            f'style="--marquee-duration:{duration:.1f}s"><div class="marquee-inner">\n')


def render_construction(self, tokens, idx, options, env):
    """::: construction  ->  the obligatory UNDER CONSTRUCTION banner."""
    if tokens[idx].nesting == -1:
        return "</div></div>\n"
    return ('<div class="construction"><div class="construction-stripe" '
            'aria-hidden="true"></div><div class="construction-body">\n')


def simple_container(cls):
    def render(self, tokens, idx, options, env):
        return f'<div class="{cls}">\n' if tokens[idx].nesting == 1 else "</div>\n"
    return render


# --------------------------------------------------------------------------
# Markdown engine
# --------------------------------------------------------------------------

def make_markdown() -> MarkdownIt:
    md = (
        MarkdownIt("commonmark", {"html": True, "typographer": True})
        .enable(["table", "strikethrough", "replacements", "smartquotes"])
        .use(footnote_plugin)
        .use(attrs_plugin, spans=True)      # [text]{.blink}, ![img](x){.pixel}
        .use(attrs_block_plugin)            # {.center} on the line above a block
        .use(anchors_plugin, min_level=2, max_level=3)
        .use(container_plugin, name="box", render=render_box)
        .use(container_plugin, name="marquee", render=render_marquee)
        .use(container_plugin, name="construction", render=render_construction)
        .use(container_plugin, name="center", render=simple_container("center"))
        .use(container_plugin, name="columns", render=simple_container("columns"))
    )
    md.core.ruler.before("inline", "heading_attrs", heading_attrs_rule)
    md.inline.ruler.before("emphasis", "shortcode", shortcode_inline)
    md.block.ruler.before("paragraph", "shortcode_block", shortcode_block,
                          {"alt": ["paragraph"]})
    md.add_render_rule("shortcode", render_shortcode)
    return md


MD = make_markdown()


def fresh(env: dict) -> dict:
    """
    A copy of env for a separate render. The footnote plugin collects
    footnotes into env, so sharing one would repeat the page's footnotes
    after every title, sidebar and data entry.
    """
    return {k: v for k, v in env.items() if k != "footnotes"}


def md_block(text: str, env: dict) -> str:
    return MD.render(text, fresh(env))


def md_inline(text: str, env: dict) -> str:
    return MD.renderInline(text, fresh(env))


# --------------------------------------------------------------------------
# Shortcodes. Each takes the render env first, then the shortcode's words.
# --------------------------------------------------------------------------

def esc(s) -> str:
    return html.escape(str(s), quote=True)


def img_tag(src, alt="", cls="", width=None, height=None, title=None) -> str:
    attrs = [f'src="{esc(src)}"', f'alt="{esc(alt)}"']
    if cls:
        attrs.append(f'class="{esc(cls)}"')
    if width:
        attrs.append(f'width="{esc(width)}"')
    if height:
        attrs.append(f'height="{esc(height)}"')
    if title:
        attrs.append(f'title="{esc(title)}"')
    return f'<img {" ".join(attrs)} loading="lazy">'


@shortcode
def gif(env, src, alt="", width=None, cls=""):
    """
    {{ gif star-blink.gif }} -- looks in /gifs/ unless given a path. Inside
    a line of text it sits on the text line like a character (gif-inline);
    alone on its line it's a plain image.
    """
    if "/" not in src:
        src = "/gifs/" + src
    classes = ["gif", "gif-inline" if env.get("inline") else "", cls]
    return img_tag(src, alt, " ".join(c for c in classes if c), width)


def button_html(b: dict) -> str:
    img = img_tag(b["img"], b.get("alt", b.get("title", "")), "button88",
                  88, 31, b.get("title"))
    return f'<a href="{esc(b["href"])}">{img}</a>' if b.get("href") else img


@shortcode
def buttons(env, group="friends"):
    """{{ buttons }} / {{ buttons group=me }} -- an 88x31 wall from data/buttons.toml."""
    items = env["data"].get("buttons", {}).get(group)
    if items is None:
        raise TypeError(f"data/buttons.toml has no [[{group}]] entries")
    return ('<div class="button-wall">'
            + "".join(button_html(b) for b in items) + "</div>")


def new_marker(d: date) -> str:
    """
    A placeholder that sparkle.js fills with the NEW! GIF while `d` is within
    new_for_months (site.toml) of the visitor's today, so badges expire on
    their own without rebuilding. Without JS, no badge.
    """
    return f'<span class="new-if-recent" data-date="{d.isoformat()}"></span>'


def news_items(env) -> list[tuple[date, str, dict]]:
    return [(*parse_date(it["date"], f"data/news.toml item {i + 1}"), it)
            for i, it in enumerate(env["data"].get("news", {}).get("item", []))]


@shortcode
def news(env, limit=None):
    """{{ news }} / {{ news limit=5 }} -- a dated table from data/news.toml."""
    items = news_items(env)
    if limit:
        items = items[: int(limit)]
    rows = []
    for d, shown, it in items:
        rows.append(f'<tr><td class="news-date"><time datetime="{d.isoformat()}">'
                    f'{esc(shown)}</time></td>'
                    f'<td>{md_inline(it["text"], env)} {new_marker(d)}</td></tr>')
    return f'<table class="news">{"".join(rows)}</table>'


def pub_items(env, kind=None) -> list[tuple[date | None, dict]]:
    """Publications (optionally one kind) with their parsed `date`, if any."""
    items = env["data"].get("publications", {}).get("pub", [])
    out = []
    for i, p in enumerate(items):
        if kind and p.get("kind") != kind:
            continue
        d = parse_date(p["date"], f"data/publications.toml pub {i + 1}")[0] if p.get("date") else None
        out.append((d, p))
    return out


@shortcode
def new(env, when=None, **kwargs):
    """
    {{ new 2026-01-15 }}                   -- NEW! badge while that date is recent.
    {{ new from=news }}                    -- ...while the newest news item is.
    {{ new from=publications kind=paper }} -- ...while the newest dated paper is
                                              (kind optional: any publication).
    """
    source = kwargs.pop("from", None)
    kind = kwargs.pop("kind", None)
    if kwargs or (when is None) == (source is None) or (kind and source != "publications"):
        raise TypeError("use {{ new DATE }}, {{ new from=news }} or "
                        "{{ new from=publications [kind=...] }}")
    if source is None:
        return new_marker(parse_date(when, env["page_src"])[0])
    if source == "news":
        dates = [d for d, _, _ in news_items(env)]
    elif source == "publications":
        dates = [d for d, _ in pub_items(env, kind) if d]
    else:
        raise TypeError(f"from={source}: expected news or publications")
    return new_marker(max(dates)) if dates else ""


@shortcode
def publications(env, kind=None):
    """{{ publications }} / {{ publications kind=thesis }} -- from data/publications.toml."""
    me = env["site"].get("author", "")
    out = []
    for d, p in pub_items(env, kind):
        authors = ", ".join(
            f"<b>{esc(a)}</b>" if a == me else esc(a) for a in p.get("authors", []))
        authors = authors or f'<span class="pub-role">{md_inline(p.get("role", ""), env)}</span>'
        links = " ".join(f'[<a href="{esc(url)}">{esc(label)}</a>]'
                         for label, url in p.get("links", {}).items())
        venue = f'<i>{md_inline(p["venue"], env)}</i>' if p.get("venue") else ""
        year = p.get("year") or (d.year if d else "")
        where = ", ".join(x for x in (venue, esc(year)) if x)
        note = f' &mdash; <span class="pub-note">{md_inline(p["note"], env)}</span>' if p.get("note") else ""
        links = f'<br><span class="pub-links">{links}</span>' if links else ""
        out.append(
            f'<li><span class="pub-title">{md_inline(p["title"], env)}</span>'
            f'{new_marker(d) if d else ""}<br>'
            f'{authors}<br>{where}{note}{links}</li>')
    return f'<ul class="publications">{"".join(out)}</ul>'


@shortcode
def counter(env, start="2026-01-01", per_day="100"):
    """
    {{ counter start=2026-01-01 per_day=100 }} -- a pretend visitor counter.
    sparkle.js extrapolates it from the visitor's clock: per_day visitors a
    day since midnight UTC on `start`. Shows "∞" without JS.
    """
    d = parse_date(start, env["page_src"])[0]
    try:
        rate = float(per_day)
    except ValueError:
        raise TypeError(f"per_day={per_day!r} is not a number") from None
    return (f'<span class="visitor-counter" data-start="{d.isoformat()}" '
            f'data-per-day="{rate:g}">&infin;</span>')


@shortcode
def updated(env):
    """{{ updated }} -- the page's last-updated date."""
    return esc(env["page_updated"])


@shortcode
def webring(env, name, home, prev, next):
    """{{ webring "Arch Webring" https://ring https://prev https://next }}"""
    return (f'<div class="webring">&lt;&lt; <a href="{esc(prev)}">prev</a> | '
            f'<a href="{esc(home)}">{esc(name)}</a> | '
            f'<a href="{esc(next)}">next</a> &gt;&gt;</div>')


@shortcode
def hr(env, img="divider.gif"):
    """{{ hr }} -- a gif divider bar instead of a plain rule."""
    return f'<div class="gif-hr">{gif(env, img)}</div>'


# --------------------------------------------------------------------------
# Per-site variables ({{ name }}, {{ first_name }}, ...)
# --------------------------------------------------------------------------

def site_vars(site: dict, host: str) -> dict:
    """The [sites."<host>"] table from site.toml, plus {{ domain }}."""
    sites = site.get("sites", {})
    if host not in sites:
        raise BuildError(f'no [sites."{host}"] in site.toml (have: {", ".join(sites)})')
    vars = {**sites[host], "domain": host}
    clash = set(vars) & set(SHORTCODES)
    if clash:
        raise BuildError(f"[sites] variable(s) {sorted(clash)} clash with shortcodes")
    return {k: str(v) for k, v in vars.items()}


def personalize(value, vars: dict):
    """
    Replaces {{ key }} for each site variable in every string of a loaded
    TOML value or page. Other {{ ... }} (shortcodes) are left alone.
    """
    if isinstance(value, str):
        return re.sub(r"\{\{\s*(\w+)\s*\}\}",
                      lambda m: vars.get(m[1], m[0]), value)
    if isinstance(value, dict):
        return {k: personalize(v, vars) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(personalize(v, vars) for v in value)
    return value


def other_names(site: dict, host: str) -> list[str]:
    """Names belonging to the *other* sites, which must not leak into this one."""
    return sorted({str(v) for h, t in site.get("sites", {}).items() if h != host
                   for k, v in t.items() if k in ("name", "first_name")})


def check_leaks(out_dir: Path, names: list[str]) -> list[str]:
    """Output text files mentioning another site's name (case-insensitive)."""
    hits = []
    for f in sorted(out_dir.rglob("*")):
        if ".git" in f.parts or f.suffix not in (".html", ".css", ".js", ".svg", ".txt", ".md", ".xml", ".json"):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for n in names:
            for m in re.finditer(re.escape(n), text, re.IGNORECASE):
                context = text[max(0, m.start() - 30) : m.end() + 30].replace("\n", " ")
                hits.append(f"/{f.relative_to(out_dir).as_posix()}: ...{context}...")
    return hits


# --------------------------------------------------------------------------
# Page assembly
# --------------------------------------------------------------------------

def render_nav(site: dict, current_url: str) -> str:
    items = []
    for n in site.get("nav", []):
        href = n["href"]
        here = href == current_url or (href != "/" and current_url.startswith(href))
        icon = img_tag(n["icon"], "", "nav-icon") if n.get("icon") else ""
        cur = ' aria-current="page"' if here else ""
        items.append(f'<li><a href="{esc(href)}"{cur}>{icon}{esc(n["label"])}</a></li>')
    return "<ul>" + "".join(items) + "</ul>"


def grid_svg(color: str) -> str:
    """
    The graph-paper background tile: 2px lines every 86px, 1px lines every
    ~17px. Served as an image rather than drawn with CSS gradients because
    the browser rasterizes an image tile once and reuses it, while gradients
    are re-evaluated per pixel on every repaint (about 5x the raster cost
    while scrolling, measured).
    """
    minor = "".join(f'<rect x="{x}" width="1" height="86"/><rect y="{x}" width="86" height="1"/>'
                    for x in (17, 34, 52, 69))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="86" height="86" '
            f'shape-rendering="crispEdges"><g fill="{esc(color)}">'
            f'<rect width="2" height="86"/><rect width="86" height="2"/>{minor}</g></svg>\n')


def theme_css(site: dict) -> str:
    """[theme] keys in site.toml become CSS custom properties."""
    decls = "".join(f"--{k}:{v};" for k, v in site.get("theme", {}).items())
    return f":root{{{decls}}}" if decls else ""


def fill(template: str, ctx: dict) -> str:
    """Single-pass {{ key }} substitution, so inserted content isn't rescanned."""
    def sub(m):
        if m[1] not in ctx:
            raise BuildError(f"theme/layout.html uses unknown {{{{ {m[1]} }}}}")
        return ctx[m[1]]
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", sub, template)


def page_updated(meta: dict, path: Path) -> str:
    """The page's own date: `updated` in front matter, else last change."""
    if meta.get("updated"):
        return parse_date(meta["updated"], str(path.relative_to(ROOT)))[1]
    return display_date(last_changed([path]))


def site_updated(site: dict) -> date:
    """Site-wide date for the banner: `updated` in site.toml, else last change."""
    if site.get("updated"):
        return parse_date(site["updated"], "site.toml")[0]
    return last_changed([ROOT / p for p in CONTENT])


def build_page(path: Path, site: dict, data: dict, layout: str) -> tuple[Path, str]:
    meta, body = personalize(split_front_matter(path), site["_vars"])
    out = output_path(path)
    url = url_for(out)
    env = {
        "site": site, "data": data, "page": meta, "url": url,
        "page_src": str(path.relative_to(ROOT)),
        "page_updated": page_updated(meta, path),
    }
    content = md_block(body, env)
    sidebar = md_block(site.get("sidebar", ""), env)
    footer = md_block(site.get("footer", ""), env)
    title = meta.get("title", site["title"])
    title_full = site["title"] if url == "/" else f"{title} - {site['title']}"
    body_class = " ".join(["page-" + (url.strip("/").replace("/", "-") or "home"),
                           *meta.get("classes", [])])
    heading = "" if meta.get("hide_title") else (
        f'<h1 class="{esc(meta.get("title_class", site.get("title_class", "")))}">'
        f'{md_inline(title, env)}</h1>')
    ctx = {
        "title": esc(title_full),
        "description": esc(meta.get("description", site.get("description", ""))),
        "theme_css": theme_css(site),
        "page_css": meta.get("css", ""),   # raw CSS, author-controlled
        "body_class": esc(body_class),
        "site_title": md_inline(site["title"], env),
        "site_title_class": esc(site.get("site_title_class", "")),
        "tagline": md_inline(site.get("tagline", ""), env),
        "nav": render_nav(site, url),
        "sidebar": sidebar,
        "heading": heading,
        "content": content,
        "footer": footer,
        "updated": esc(env["page_updated"]),
        "trail": "true" if site.get("cursor_trail") else "false",
        "new_months": esc(site.get("new_for_months", 3)),
        "site_updated": display_date(site["_updated"]),
        "site_updated_iso": site["_updated"].isoformat(),
    }
    return out, fill(layout, {**site["_vars"], **ctx})


def build(out_dir: Path, drafts: bool, host: str) -> list[Path]:
    raw = load_toml(ROOT / "site.toml")
    vars = site_vars(raw, host)
    site = personalize(raw, vars)
    site["_vars"] = vars
    site["_updated"] = site_updated(site)
    data = personalize(load_data(), vars)
    layout = (THEME / "layout.html").read_text(encoding="utf-8")

    if out_dir.exists():
        for child in out_dir.iterdir():
            if child.name in ALWAYS_KEEP or child.name in site.get("keep", []):
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)

    if STATIC.exists():
        shutil.copytree(STATIC, out_dir, dirs_exist_ok=True)
    # Per-site files (e.g. an 88x31 with that site's name) layered on top.
    if (SITE_STATIC / host).exists():
        shutil.copytree(SITE_STATIC / host, out_dir, dirs_exist_ok=True)
    shutil.copytree(THEME, out_dir / "theme", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("layout.html"))
    (out_dir / "theme" / "grid.svg").write_text(
        grid_svg(site.get("theme", {}).get("bg-2", "#e8c2ca")), encoding="utf-8")
    (out_dir / ".nojekyll").touch()   # GitHub Pages: serve files as-is

    written = []
    for path in sorted(PAGES.rglob("*.md")):
        meta, _ = split_front_matter(path)
        if meta.get("draft") and not drafts:
            continue
        rel, text = build_page(path, site, data, layout)
        dest = out_dir / rel
        if dest.exists():
            raise BuildError(f"{path.relative_to(ROOT)}: two pages map to /{rel}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        written.append(rel)
    return written


LINK_ATTR = re.compile(r'(?:href|src)="(/[^"#?]*)')


def check_links(out_dir: Path, written: list[Path]) -> list[str]:
    """Site-internal href/src targets that don't exist in the output."""
    broken = []
    for rel in written:
        for target in set(LINK_ATTR.findall((out_dir / rel).read_text(encoding="utf-8"))):
            path = out_dir / target.lstrip("/")
            if not (path.is_file() or (path / "index.html").is_file()):
                broken.append(f"/{rel.as_posix()} -> {target}")
    return sorted(broken)


def check_publish_target(target: Path, force: bool):
    """Publishing wipes the target, so insist it looks like the site repo."""
    if not (target / ".git").exists() and not force:
        raise BuildError(
            f"{target} is not a git repository. Publishing deletes everything "
            f"in the target except {sorted(ALWAYS_KEEP)} and site.toml's keep "
            f"list; pass --force if you really mean it.")


class PreviewHandler(http.server.SimpleHTTPRequestHandler):
    """Like GitHub Pages: a missing path gets /404.html, with status 404."""

    def send_error(self, code, message=None, explain=None):
        page = Path(self.directory) / "404.html"
        if code != 404 or not page.is_file():
            return super().send_error(code, message, explain)
        body = page.read_bytes()
        self.send_response(404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


def serve(out_dir: Path, port: int):
    handler = partial(PreviewHandler, directory=str(out_dir))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        print(f"Serving {out_dir} at http://localhost:{port}/  (Ctrl-C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "_site",
                    help="output directory (default: _site/)")
    ap.add_argument("--site", metavar="HOSTNAME",
                    help="which [sites] entry to build (default: the --out folder's "
                         "name, or for _site/ the first entry)")
    ap.add_argument("--drafts", action="store_true",
                    help="also build pages with draft = true")
    ap.add_argument("--serve", action="store_true",
                    help="serve the output on localhost after building")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--force", action="store_true",
                    help="allow --out to be a directory that isn't a git repo")
    args = ap.parse_args()
    out_dir = args.out.resolve()

    try:
        sites = list(load_toml(ROOT / "site.toml").get("sites", {}))
        if not sites:
            raise BuildError('site.toml needs at least one [sites."<hostname>"] table')
        publishing = out_dir != ROOT / "_site"
        host = args.site or (out_dir.name if publishing else sites[0])
        if publishing and host not in sites:
            raise BuildError(f"can't tell which site {out_dir.name} is; name the "
                             f"folder after a hostname in [sites] or pass --site")
        if publishing:
            check_publish_target(out_dir, args.force)
        written = build(out_dir, args.drafts, host)
        leaks = check_leaks(out_dir, other_names(load_toml(ROOT / "site.toml"), host))
    except BuildError as e:
        sys.exit(f"build failed: {e}")

    print(f"Built {len(written)} pages for {host} into {out_dir}")
    for rel in written:
        print(f"  /{rel.as_posix()}")
    broken = check_links(out_dir, written)
    if broken:
        print(f"\nWarning: {len(broken)} broken internal link(s):")
        for b in broken:
            print(f"  {b}")
    if leaks:
        print(f"\nWarning: another site's name appears in {len(leaks)} place(s):")
        for hit in leaks:
            print(f"  {hit}")
    if args.serve:
        serve(out_dir, args.port)


if __name__ == "__main__":
    main()
