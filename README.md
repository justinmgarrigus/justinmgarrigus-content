# justinmgarrigus.github.io — content

Markdown source for https://justinmgarrigus.github.io. `build.py` compiles it
into the separate `justinmgarrigus.github.io` repo, which GitHub Pages serves.

## Setup

Just [uv](https://docs.astral.sh/uv/). `build.py` declares its own
dependencies (the `# /// script` block at the top), and uv fetches them on
first run, pinned by `build.py.lock`. To upgrade them: `uv lock --script build.py --upgrade`.

## Everyday use

    uv run build.py --drafts --serve             # preview at http://localhost:8000
    ./publish.sh                                 # build into ../justinmgarrigus.github.io,
                                                 # review, commit, push

Publishing **replaces** the contents of the site repo (except `.git`,
`CNAME`, `.nojekyll`, `README.md`, and anything in `keep` in `site.toml`),
so everything the live site needs must live here. The build warns about
internal links that point at nothing.

## Layout

| Path | What it is |
|---|---|
| `site.toml` | Title, tagline, nav, sidebar, footer, theme colors |
| `pages/*.md` | One page each. `pages/foo.md` → `/foo/` |
| `data/*.toml` | News, publications, 88x31 buttons |
| `static/` | Copied as-is to the site root (`static/cv/resume.pdf` → `/cv/resume.pdf`) |
| `static/gifs/`, `static/buttons/` | GIF icons and 88x31s |
| `theme/` | `layout.html` skeleton, `style.css`, `sparkle.js` |
| `tools/make-gifs.sh` | Regenerates the placeholder GIFs/buttons |

## Writing pages

The full cheat sheet, rendered, is `pages/sparkle.md` (a draft; view it at
`/sparkle/` with `--drafts`). In short:

    +++
    title = "Research"
    title_class = "wordart"
    +++

    ## News {.blink-colors}           effects on headings
    Some [blinking]{.blink} words.     ...or on any span of text
    {{ gif star-blink.gif }}           a GIF from static/gifs/
    {{ news limit=5 }}                 data/news.toml as a table (recent rows get NEW!)
    {{ new from=news }}                NEW! while the latest news is recent
    {{ new from=publications kind=paper }}   ...or the latest dated paper
    {{ new 2026-09-01 }}               NEW! while that date is recent
    {{ counter start=2026-01-01 per_day=100 }}   pretend visitor counter
    {{ publications kind=paper }}      data/publications.toml
    {{ buttons group=friends }}        a wall of 88x31s from data/buttons.toml

    ::: box Window Title               Win95 window
    ::: marquee                        scrolling text
    ::: construction                   UNDER CONSTRUCTION banner
    ::: center / ::: columns

Effects: `blink`, `blink-colors`, `rainbow`, `glow`, `shake`, `wobble`,
`sparkle`, `comic`, `wordart`, `new-badge`.

Raw HTML also works anywhere in a page.

## Readability rules the theme keeps

- Body text is on a solid panel, capped at ~44rem wide; decoration stays in
  the frame and headings.
- `prefers-reduced-motion` turns every animation off. The footer's "Reduce
  movement" button does the same (and freezes GIFs) for anyone, remembered
  per browser.
- Under 760px wide the layout is one column with the nav as a row of buttons.
- The site works with JavaScript off; `sparkle.js` only adds the toggle and
  the cursor trail.

## Keeping it fast

Measured with Chrome tracing, the costly things on a page like this are
repaints, not layout or JS:

- The background grid is an image tile (`/theme/grid.svg`, written by
  `build.py` in the `bg-2` color). As CSS gradients it cost ~5x the raster
  time, since it's redrawn under anything that repaints.
- Continuous effects animate only `transform`, `opacity` or `filter:
  hue-rotate()`, which run on the compositor. Animating `background-position`,
  `text-shadow`, `color` or `drop-shadow()` repaints every frame.
- `blink`/`blink-colors` are stepped by `sparkle.js` a few times a second
  instead of a CSS `steps()` animation, which re-runs style every frame.

New effects should follow the same rules.

## Adding a shortcode

Write a function in `build.py` decorated with `@shortcode`. It receives
`env` (with `env["site"]`, `env["data"]`, `env["page"]`) followed by the
shortcode's words; `key=value` words arrive as keyword arguments. Return HTML.
