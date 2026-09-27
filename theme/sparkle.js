// Small client-side extras. The site works fully without this file.
//
//  - "Reduce movement" button: toggles html.calm (CSS animations off) and
//    freezes animated GIFs on their first frame. Remembered per browser.
//  - Fills in the pretend visitor counter.
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

  var button = document.getElementById("calm-toggle");
  function sync() {
    var calm = root.classList.contains("calm");
    if (button) {
      button.setAttribute("aria-pressed", calm ? "true" : "false");
      button.textContent = calm ? "Bring back the movement" : "Stop the movement";
    }
    freezeGifs(isCalm());
    runBlink(!isCalm());
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
      s.style.left = (e.clientX + 6) + "px";
      s.style.top = (e.clientY + 6) + "px";
      document.body.appendChild(s);
      setTimeout(function () { s.remove(); }, 700);
    });
  }
})();
