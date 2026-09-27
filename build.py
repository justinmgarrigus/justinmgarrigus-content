# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "markdown-it-py>=4.2,<5",
#     "mdit-py-plugins>=0.6.1,<0.7",
# ]
# ///
"""
Compiles the content repository into a static site.

    uv run build.py                      # build into _site/
    uv run build.py --serve              # build, then preview at localhost:8000
    uv run build.py --out ../justinmgarrigus.github.io   # publish

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
import sys
import tomllib
from datetime import date, datetime
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
    out = run_shortcode(tokens[idx].content, env)
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


def render_marquee(self, tokens, idx, options, env):
    """::: marquee  ->  scrolling text (static under reduced motion)."""
    if tokens[idx].nesting == -1:
        return "</div></div>\n"
    speed = container_args(tokens, idx, "marquee") or "18s"
    return (f'<div class="marquee" style="--marquee-speed:{html.escape(speed)}">'
            f'<div class="marquee-inner">\n')


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
    """{{ gif star-blink.gif }} -- looks in /gifs/ unless given a path."""
    if "/" not in src:
        src = "/gifs/" + src
    return img_tag(src, alt, ("gif " + cls).strip(), width)


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


@shortcode
def news(env, limit=None):
    """{{ news }} / {{ news limit=5 }} -- a dated table from data/news.toml."""
    items = env["data"].get("news", {}).get("item", [])
    if limit:
        items = items[: int(limit)]
    rows = []
    for it in items:
        badge = (" " + gif(env, "new.gif", "new!")) if it.get("new") else ""
        rows.append(f'<tr><td class="news-date">{esc(it["date"])}</td>'
                    f'<td>{md_inline(it["text"], env)}{badge}</td></tr>')
    return f'<table class="news">{"".join(rows)}</table>'


@shortcode
def publications(env, kind=None):
    """{{ publications }} / {{ publications kind=thesis }} -- from data/publications.toml."""
    items = env["data"].get("publications", {}).get("pub", [])
    if kind:
        items = [p for p in items if p.get("kind") == kind]
    me = env["site"].get("author", "")
    out = []
    for p in items:
        authors = ", ".join(
            f"<b>{esc(a)}</b>" if a == me else esc(a) for a in p.get("authors", []))
        authors = authors or f'<span class="pub-role">{md_inline(p.get("role", ""), env)}</span>'
        links = " ".join(f'[<a href="{esc(url)}">{esc(label)}</a>]'
                         for label, url in p.get("links", {}).items())
        venue = f'<i>{md_inline(p["venue"], env)}</i>' if p.get("venue") else ""
        where = ", ".join(x for x in (venue, esc(p.get("year", ""))) if x)
        note = f' &mdash; <span class="pub-note">{md_inline(p["note"], env)}</span>' if p.get("note") else ""
        links = f'<br><span class="pub-links">{links}</span>' if links else ""
        out.append(
            f'<li><span class="pub-title">{md_inline(p["title"], env)}</span><br>'
            f'{authors}<br>{where}{note}{links}</li>')
    return f'<ul class="publications">{"".join(out)}</ul>'


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
    when = meta.get("updated")
    if isinstance(when, (date, datetime)):
        return when.strftime("%B %-d, %Y")
    if when:
        return str(when)
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%B %-d, %Y")


def build_page(path: Path, site: dict, data: dict, layout: str) -> tuple[Path, str]:
    meta, body = split_front_matter(path)
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
    }
    return out, fill(layout, ctx)


def build(out_dir: Path, drafts: bool) -> list[Path]:
    site = load_toml(ROOT / "site.toml")
    data = load_data()
    layout = (THEME / "layout.html").read_text(encoding="utf-8")

    if out_dir.exists():
        for child in out_dir.iterdir():
            if child.name in ALWAYS_KEEP or child.name in site.get("keep", []):
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)

    if STATIC.exists():
        shutil.copytree(STATIC, out_dir, dirs_exist_ok=True)
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


def serve(out_dir: Path, port: int):
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(out_dir))
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
        if out_dir != ROOT / "_site":
            check_publish_target(out_dir, args.force)
        written = build(out_dir, args.drafts)
    except BuildError as e:
        sys.exit(f"build failed: {e}")

    print(f"Built {len(written)} pages into {out_dir}")
    for rel in written:
        print(f"  /{rel.as_posix()}")
    broken = check_links(out_dir, written)
    if broken:
        print(f"\nWarning: {len(broken)} broken internal link(s):")
        for b in broken:
            print(f"  {b}")
    if args.serve:
        serve(out_dir, args.port)


if __name__ == "__main__":
    main()
