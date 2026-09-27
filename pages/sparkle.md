+++
title = "Sparkle Reference"
title_class = "rainbow"
draft = true      # a cheat sheet: only built with `python build.py --drafts`
description = "Every effect, container and shortcode this site supports."
+++

This page shows every trick the build supports, with the Markdown that makes
it. It's a draft, so it never gets published.

## Text effects {.blink-colors}

Put `{.class}` after a heading, or wrap words as `[words]{.class}`:

| Markdown | Result |
|---|---|
| `[text]{.blink}` | [BLINKING]{.blink} |
| `[text]{.blink-colors}` | [color cycle]{.blink-colors} |
| `[text]{.rainbow}` | [rainbow text]{.rainbow} |
| `[text]{.glow}` | [glowing]{.glow} |
| `[text]{.shake}` | [shaky!!]{.shake} |
| `[text]{.wobble}` | [wobbly]{.wobble} |
| `[text]{.sparkle}` | [sparkly]{.sparkle} |
| `[text]{.comic}` | [Comic Sans]{.comic} |
| `[text]{.wordart}` | [WordArt]{.wordart} |
| `[text]{.new-badge}` | [NEW]{.new-badge} |

Classes stack: `## Heading {.rainbow .wobble}`. Colors for blink/glow come
from `blink-1` … `blink-4` in `[theme]`.

## Heading with rainbow {.rainbow}

## Heading with WordArt {.wordart}

### A sparkly subheading {.sparkle}

## GIFs and 88x31s

`{{ gif star-blink.gif }}` → {{ gif star-blink.gif }} &nbsp;
`{{ gif new.gif alt="new!" }}` → {{ gif new.gif alt="new!" }}

Bare filenames are looked up in `/gifs/`; give a path (`/media/x.gif`) to use
anything else. Add `width=48` to scale (pixels stay crisp).

A button wall from `data/buttons.toml`: `{{ buttons group=friends }}`

{{ buttons group=friends }}

Images get attributes too: `![me](/media/profile-pic.jpg){.pixel width=80}`

![me](/media/profile-pic.jpg){.pixel width=80}

## Dividers

A normal `---` rule:

---

A GIF divider, `{{ hr }}` (or `{{ hr img=other.gif }}`):

{{ hr }}

## Containers

```
::: box Welcome!
Contents of a **window**.
:::
```

::: box Welcome!
Contents of a **window**. Leave off the title for a plain bevelled box.
:::

```
::: marquee 120
Scrolling text; the number is the speed in pixels per second (default 80).
:::
```

::: marquee 120
Scrolling text; the number is the speed in pixels per second (default 80). ★ ★ ★
:::

::: marquee 120
Same speed, much less text.
:::

::: construction
`::: construction` — the obligatory **UNDER CONSTRUCTION** banner.
:::

`::: center` centers its contents. `::: columns` lays out children side by
side (stacks on phones):

::::: columns
::: box Left
One
:::
::: box Right
Two
:::
:::::

## Data shortcodes

`{{ news limit=2 }}`

{{ news limit=2 }}

`{{ publications kind=thesis }}`

{{ publications kind=thesis }}

`{{ webring "Arch Webring" https://example.com https://example.com/prev https://example.com/next }}`

{{ webring "Arch Webring" https://example.com https://example.com/prev https://example.com/next }}

`{{ new 2026-09-01 }}` → {{ new 2026-09-01 }} (a NEW! badge while the
date is within `new_for_months` of today, checked in the browser;
`{{ new from=news }}` uses the newest news item, as on the News heading;
`{{ new from=publications kind=paper }}` the newest dated paper, as on the
Research page). News rows, and publications with a `date`, get this
automatically.

`{{ counter start=2026-01-01 per_day=100 }}` → {{ counter start=2026-01-01 per_day=100 }}
(a pretend visitor counter, extrapolated in the browser from the start date
and daily rate; "∞" without JS).

`{{ updated }}` → {{ updated }} (from `updated = 2026-09-26` in front
matter, else the file's modification time).

## Research-y things

Footnotes work[^1], as do tables, `inline code` and fenced blocks:

```c
for (int i = 0; i < n; i++) y[i] += a * x[i];
```

> Blockquotes are for quoting reviewers.

[^1]: Like this one.

## Front matter keys

```
+++
title = "Page title"          # <h1> and <title>
title_class = "rainbow"        # effect classes for the <h1>
hide_title = true              # skip the <h1>
description = "..."            # <meta name="description">
updated = 2026-09-26           # shown as "Last updated"
draft = true                   # only built with --drafts
classes = ["dark-page"]        # extra <body> classes
css = "h2 { background: green }"   # extra CSS for this page only
+++
```

Raw HTML is allowed anywhere, so anything not covered here (an `<iframe>`,
a `<details>` block, a real `<marquee>`) can be written directly.
