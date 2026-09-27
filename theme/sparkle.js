// Small client-side extras. The site works fully without this file.
//
//  - "Reduce movement" button: toggles html.calm (CSS animations off) and
//    freezes animated GIFs on their first frame. Remembered per browser.
//  - Fills in the pretend visitor counter.
//  - Animates a GIF favicon in browsers that don't (all but Firefox).
//  - Times marquees so they scroll at a constant speed.
//  - Shows NEW! badges on recently dated items (news rows, {{ new }}).
//  - Drives .blink and .blink-colors from a timer, and sets up .glow, so
//    those effects avoid per-frame work (see style.css "effects").
//  - Optional star trail behind the mouse (site.toml: cursor_trail = true).

(function () {
  var root = document.documentElement;
  var script = document.currentScript || document.querySelector("script[data-trail]");
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

  function isCalm() {
    return root.classList.contains("calm") || reduced.matches;
  }

  // Freezing GIFs: each is swapped for a still of the frame showing at the
  // time, drawn to a canvas. Cross-origin GIFs can't be captured this way
  // and keep animating. GIFs used from CSS must go through one of these
  // custom properties (style.css) to be frozen.
  var CSS_GIF_VARS = ["--gif-star", "--bullet", "--bg-image"];

  function stillOf(img) {
    try {
      if (!img.naturalWidth) return null;
      var c = document.createElement("canvas");
      c.width = img.naturalWidth; c.height = img.naturalHeight;
      c.getContext("2d").drawImage(img, 0, 0);
      return c.toDataURL();
    } catch (e) { return null; }
  }

  function whenLoaded(img, fn) {
    img.complete ? fn() : img.addEventListener("load", fn, { once: true });
  }

  function freezeGifs(freeze) {
    // <img> GIFs; the original src waits in data-src for unfreezing.
    document.querySelectorAll('img[src$=".gif"], img[data-src$=".gif"]').forEach(function (img) {
      if (freeze && !img.dataset.src) {
        // Lazy images below the fold load later: re-check calm by then.
        whenLoaded(img, function () {
          if (!isCalm() || img.dataset.src) return;
          var url = stillOf(img);
          if (url) { img.dataset.src = img.src; img.src = url; }
        });
      } else if (!freeze && img.dataset.src) {
        img.src = img.dataset.src;
        delete img.dataset.src;
      }
    });
    // CSS GIFs (list bullets, .sparkle stars, tiled backgrounds): override
    // the custom property on <html>; removing the override unfreezes.
    CSS_GIF_VARS.forEach(function (name) {
      if (!freeze) { root.style.removeProperty(name); return; }
      var value = getComputedStyle(root).getPropertyValue(name);
      var m = /url\(\s*["']?([^"')]+\.gif)["']?\s*\)/i.exec(value);
      if (!m) return;
      var img = new Image();
      img.src = m[1];
      whenLoaded(img, function () {
        var url = isCalm() && stillOf(img);
        if (url) root.style.setProperty(name, value.replace(m[0], 'url("' + url + '")'));
      });
    });
  }

  // NEW! badges. The build marks dated things (news rows, {{ new }}) with
  // <span class="new-if-recent" data-date="YYYY-MM-DD">; show the GIF while
  // that date is within new_for_months (site.toml) of the visitor's today, so
  // badges appear and expire without a rebuild. Runs before freezeGifs.
  (function () {
    var months = Number(script && script.dataset.newMonths) || 3;
    var now = new Date();
    var y = now.getFullYear(), m = now.getMonth() - months;
    var lastDay = new Date(y, m + 1, 0).getDate();   // clamp May 31 -> Feb 28
    var cutoff = new Date(y, m, Math.min(now.getDate(), lastDay));
    document.querySelectorAll(".new-if-recent[data-date]").forEach(function (el) {
      var p = el.dataset.date.split("-").map(Number);
      var when = new Date(p[0], p[1] - 1, p[2]);        // local midnight, not UTC
      if (when >= cutoff) {                              // future dates count too
        el.innerHTML = '<img src="/gifs/new.gif" alt="new!" class="gif" width="30" height="13">';
      }
    });
  })();

  // Marquees scroll at a constant speed (data-speed, px/s): the duration is
  // the distance travelled, which is the inner strip's full width (its
  // run-in padding is the box width, plus the text), over the speed.
  // Recomputed when the box resizes; the build wrote an estimate.
  var marquees = document.querySelectorAll(".marquee[data-speed]");
  function timeMarquee(m) {
    var inner = m.querySelector(".marquee-inner");
    if (inner && inner.offsetWidth) {
      m.style.setProperty("--marquee-duration", inner.offsetWidth / Number(m.dataset.speed) + "s");
    }
  }
  marquees.forEach(timeMarquee);
  if (window.ResizeObserver && marquees.length) {
    var ro = new ResizeObserver(function (entries) {
      entries.forEach(function (e) { timeMarquee(e.target); });
    });
    marquees.forEach(function (m) { ro.observe(m); });
  }

  // Pretend visitor counter ({{ counter }}): per_day visitors a day since
  // midnight UTC on the start date, extrapolated to the visitor's clock.
  document.querySelectorAll(".visitor-counter[data-start]").forEach(function (el) {
    var p = el.dataset.start.split("-").map(Number);
    var days = (Date.now() - Date.UTC(p[0], p[1] - 1, p[2])) / 864e5;
    var n = Math.max(1, Math.floor(days * Number(el.dataset.perDay)) + 1);
    el.textContent = n.toLocaleString("en-US");
  });

  // Blink phases: html[data-blink] = color phase 1-4 + "v"isible/"h"idden.
  // Only written when the phase changes (~4 times a second), so the page
  // does no per-frame work. Periods match the CSS fallback animations.
  var blinkTimer = null, blinkPhase = "";
  function blinkTick() {
    var t = Date.now();
    var phase = (Math.floor(t / 300) % 4 + 1) + (t % 1000 < 500 ? "v" : "h");
    if (phase !== blinkPhase) root.setAttribute("data-blink", blinkPhase = phase);
    // Sleep until the next color (300ms) or visibility (500ms) boundary.
    blinkTimer = setTimeout(blinkTick, Math.min(300 - t % 300, 500 - t % 500) + 1);
  }
  function runBlink(on) {
    if (on && !blinkTimer && document.querySelector(".blink, .blink-colors")) {
      blinkTick();
    } else if (!on && blinkTimer) {
      clearTimeout(blinkTimer);
      blinkTimer = null;
      blinkPhase = "";
      root.removeAttribute("data-blink");
    }
  }

  // .glow fades a pre-blurred copy of its text (style.css), read from here.
  document.querySelectorAll(".glow").forEach(function (el) {
    el.dataset.text = el.textContent;
  });

  // Animated favicon. Only Firefox animates a GIF favicon by itself; Chrome,
  // Edge and Safari show its first frame. Where the browser can decode GIF
  // frames (ImageDecoder: Chromium), cycle the icon through them, honoring
  // each frame's delay. Elsewhere leave the GIF as-is. Calm mode shows a
  // still frame either way.
  var icon = document.querySelector('link[rel~="icon"][href$=".gif"]');
  var iconSrc = icon && icon.href, iconFrames = null, iconTimer = null, iconRun = 0;

  function loadIconFrames() {
    if (iconFrames) return iconFrames;
    iconFrames = !window.ImageDecoder ? Promise.resolve([]) :
      fetch(iconSrc).then(function (r) { return r.arrayBuffer(); }).then(async function (buf) {
        var dec = new ImageDecoder({ data: buf, type: "image/gif" });
        await dec.tracks.ready;       // the frame list...
        await dec.completed;          // ...and all of the data
        var frames = [];
        for (var i = 0; i < dec.tracks.selectedTrack.frameCount; i++) {
          var f = (await dec.decode({ frameIndex: i })).image;   // fully composited
          var c = document.createElement("canvas");
          c.width = f.displayWidth; c.height = f.displayHeight;
          c.getContext("2d").drawImage(f, 0, 0);
          // Durations are in microseconds; like browsers, treat ~0 as 100ms.
          var ms = (f.duration || 0) / 1000;
          frames.push({ url: c.toDataURL(), ms: ms < 20 ? 100 : ms });
          f.close();
        }
        dec.close();
        return frames;
      }).catch(function () { return []; });
    return iconFrames;
  }

  function animateIcon(on) {
    if (!icon) return;
    var run = ++iconRun;              // a later call supersedes this one
    clearTimeout(iconTimer);
    loadIconFrames().then(function (frames) {
      if (run !== iconRun) return;
      if (!frames.length) {           // no decoder: the GIF itself, or a still
        if (on) { icon.href = iconSrc; return; }
        var img = new Image();
        img.src = iconSrc;
        whenLoaded(img, function () {
          var url = run === iconRun && stillOf(img);
          if (url) icon.href = url;
        });
        return;
      }
      if (!on || frames.length === 1) { icon.href = frames[0].url; return; }
      var i = 0;
      (function step() {
        icon.href = frames[i].url;
        iconTimer = setTimeout(step, frames[i].ms);
        i = (i + 1) % frames.length;
      })();
    });
  }

  var button = document.getElementById("calm-toggle");
  function sync() {
    var calm = root.classList.contains("calm");
    if (button) {
      button.setAttribute("aria-pressed", calm ? "true" : "false");
      button.textContent = calm ? "Produce motion" : "Reduce motion";
    }
    freezeGifs(isCalm());
    runBlink(!isCalm());
    animateIcon(!isCalm());
  }
  if (button) {
    button.addEventListener("click", function () {
      root.classList.toggle("calm");
      try { localStorage.setItem("calm", root.classList.contains("calm") ? "1" : "0"); } catch (e) {}
      sync();
    });
  }
  reduced.addEventListener("change", sync);
  sync();

  // Star trail: mouse only, never under reduced motion or calm mode.
  if (script && script.dataset.trail === "true" && window.matchMedia("(pointer: fine)").matches) {
    var last = 0;
    document.addEventListener("mousemove", function (e) {
      var now = Date.now();
      if (isCalm() || now - last < 45) return;
      last = now;
      var s = document.createElement("span");
      s.className = "trail-star";
      s.style.left = e.clientX + "px";
      s.style.top = e.clientY + "px";
      document.body.appendChild(s);
      setTimeout(function () { s.remove(); }, 700);
    });
  }
})();
