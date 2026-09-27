// Small client-side extras. The site works fully without this file.
//
//  - "Stop the sparkles" button: toggles html.calm (CSS animations off) and
//    freezes animated GIFs on their first frame. Remembered per browser.
//  - Drives .blink and .blink-colors from a timer, and sets up .glow, so
//    those effects avoid per-frame work (see style.css "effects").
//  - Optional star trail behind the mouse (site.toml: cursor_trail = true).

(function () {
  var root = document.documentElement;
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

  function isCalm() {
    return root.classList.contains("calm") || reduced.matches;
  }

  // Swap each GIF for a still of its first frame, keeping the original src
  // in data-src so it can be restored.
  function freezeGifs(freeze) {
    document.querySelectorAll('img[src$=".gif"], img[data-src$=".gif"]').forEach(function (img) {
      if (freeze && !img.dataset.src) {
        var still = function () {
          try {
            var c = document.createElement("canvas");
            c.width = img.naturalWidth; c.height = img.naturalHeight;
            c.getContext("2d").drawImage(img, 0, 0);
            img.dataset.src = img.src;
            img.src = c.toDataURL();
          } catch (e) { /* cross-origin GIF: leave it animating */ }
        };
        img.complete ? still() : img.addEventListener("load", still, { once: true });
      } else if (!freeze && img.dataset.src) {
        img.src = img.dataset.src;
        delete img.dataset.src;
      }
    });
  }

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
      button.textContent = calm ? "Bring back the sparkles" : "Stop the sparkles";
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
  var script = document.currentScript || document.querySelector("script[data-trail]");
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
