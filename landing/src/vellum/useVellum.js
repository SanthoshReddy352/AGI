import { useEffect } from "react";

/**
 * Vellum runtime, ported from the design system's motion.js / suite.js / fx.js
 * into a single React effect. Faithful behaviour: repeatable scroll reveals,
 * floating nav + morphing pill + scrollspy + mega-menu + mobile menu, command
 * palette, accordion, dropdowns, toasts, magnetic buttons, spring tilt,
 * spotlight, persisted theme, scroll-progress bar, and the highlighter cursor.
 *
 * Re-runs whenever `key` changes (route change) so freshly rendered DOM is
 * wired up. All window/document listeners use an AbortController and all
 * IntersectionObservers are disconnected on cleanup, so nothing leaks or
 * double-fires across navigation or React StrictMode's double-invoke.
 */
export function useVellum(key) {
  useEffect(() => {
    const ac = new AbortController();
    const { signal } = ac;
    const opts = { signal };
    const passive = { passive: true, signal };
    const observers = [];

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
    const $ = (s, r = document) => r.querySelector(s);
    const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

    document.documentElement.classList.add("is-loaded");

    /* ---- Theme (persisted), via delegation so it survives re-renders ---- */
    const root = document.documentElement;
    const savedTheme = localStorage.getItem("vellum-theme");
    if (savedTheme) root.setAttribute("data-theme", savedTheme);
    document.addEventListener(
      "click",
      (e) => {
        if (!e.target.closest("[data-theme-toggle]")) return;
        const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
        root.setAttribute("data-theme", next);
        localStorage.setItem("vellum-theme", next);
      },
      opts
    );

    /* ====================================================== */
    /* Repeatable scroll reveals                               */
    /* ====================================================== */
    const allReveal = $$("[data-reveal]");
    if (reduce || !("IntersectionObserver" in window)) {
      allReveal.forEach((el) => el.classList.add("is-in"));
    } else {
      const grouped = new Set();
      $$("[data-reveal-group]").forEach((group) => {
        const kids = $$("[data-reveal]", group);
        kids.forEach((k) => grouped.add(k));
        const step = parseInt(group.dataset.stagger || "80", 10);
        const io = new IntersectionObserver(
          (entries) => {
            entries.forEach((e) => {
              kids.forEach((k, i) => {
                k.style.setProperty("--reveal-delay", e.isIntersecting ? `${i * step}ms` : "0ms");
                k.classList.toggle("is-in", e.isIntersecting);
              });
            });
          },
          { threshold: 0.12, rootMargin: "0px 0px -8% 0px" }
        );
        io.observe(group);
        observers.push(io);
      });
      const io2 = new IntersectionObserver(
        (entries) => entries.forEach((e) => e.target.classList.toggle("is-in", e.isIntersecting)),
        { threshold: 0.14, rootMargin: "0px 0px -8% 0px" }
      );
      allReveal.filter((el) => !grouped.has(el)).forEach((el) => io2.observe(el));
      observers.push(io2);
    }

    /* ====================================================== */
    /* Scroll progress bar (singleton)                         */
    /* ====================================================== */
    let progress = $(".scroll-progress");
    if (!progress) {
      progress = document.createElement("div");
      progress.className = "scroll-progress";
      progress.setAttribute("aria-hidden", "true");
      document.body.appendChild(progress);
    }
    const onProgress = () => {
      const d = document.documentElement;
      const max = d.scrollHeight - d.clientHeight;
      progress.style.setProperty("--sp", max > 0 ? (d.scrollTop / max).toFixed(4) : "0");
    };
    onProgress();
    window.addEventListener("scroll", onProgress, passive);

    /* ---------- Nav: float on scroll ---------- */
    const navx = $(".navx");
    if (navx) {
      const onScroll = () => navx.classList.toggle("is-float", window.scrollY > 20);
      onScroll();
      window.addEventListener("scroll", onScroll, passive);
    }

    /* ---------- Nav: morphing hover pill ---------- */
    const navNav = $(".navx__nav");
    if (navNav) {
      const pill = $(".navx__pill", navNav);
      const links = $$(".navx__link", navNav);
      const moveTo = (el) => {
        if (!pill || !el) return;
        navNav.classList.add("show-pill");
        pill.style.setProperty("--pill-x", `${el.offsetLeft}px`);
        pill.style.setProperty("--pill-w", `${el.offsetWidth}px`);
      };
      const rest = () => {
        const cur = links.find((l) => l.getAttribute("aria-current") === "true");
        if (cur) moveTo(cur);
        else navNav.classList.remove("show-pill");
      };
      links.forEach((l) => {
        l.addEventListener("pointerenter", () => moveTo(l), opts);
        l.addEventListener("focus", () => moveTo(l), opts);
      });
      navNav.addEventListener("pointerleave", rest, opts);
      window.addEventListener("resize", rest, opts);

      /* ---------- Nav: scrollspy (top nav links only) ---------- */
      const spyLinks = $$("[data-spy]", navNav);
      if (spyLinks.length && "IntersectionObserver" in window) {
        const setCurrent = (id) => {
          spyLinks.forEach((l) => l.setAttribute("aria-current", String(l.dataset.spy === id)));
          const cur = spyLinks.find((l) => l.dataset.spy === id);
          if (cur && !navNav.matches(":hover")) moveTo(cur);
        };
        const spy = new IntersectionObserver(
          (entries) => entries.forEach((e) => e.isIntersecting && setCurrent(e.target.id)),
          { rootMargin: "-45% 0px -50% 0px" }
        );
        spyLinks.forEach((l) => {
          const t = document.getElementById(l.dataset.spy);
          if (t) spy.observe(t);
        });
        observers.push(spy);
      }
      requestAnimationFrame(rest);
    }

    /* ---------- Nav: mega menu ---------- */
    $$(".navx__drop").forEach((drop) => {
      const trigger = $(".navx__link", drop);
      let t;
      const open = () => {
        clearTimeout(t);
        drop.classList.add("open");
        trigger?.setAttribute("aria-expanded", "true");
      };
      const close = () => {
        drop.classList.remove("open");
        trigger?.setAttribute("aria-expanded", "false");
      };
      drop.addEventListener("pointerenter", open, opts);
      drop.addEventListener("pointerleave", () => { t = setTimeout(close, 120); }, opts);
      trigger?.addEventListener("click", (e) => {
        e.preventDefault();
        drop.classList.contains("open") ? close() : open();
      }, opts);
    });

    /* ---------- Nav: mobile menu + hamburger ---------- */
    const burger = $(".burger");
    const mobile = $(".mobilemenu");
    if (burger && mobile) {
      const toggle = (force) => {
        const willOpen = force ?? !mobile.classList.contains("open");
        mobile.classList.toggle("open", willOpen);
        burger.classList.toggle("open", willOpen);
        document.body.style.overflow = willOpen ? "hidden" : "";
        burger.setAttribute("aria-expanded", String(willOpen));
      };
      burger.addEventListener("click", () => toggle(), opts);
      $$("a", mobile).forEach((a) => a.addEventListener("click", () => toggle(false), opts));
    }

    /* ---------- Command palette ---------- */
    const palette = $(".palette");
    const scrim = $("[data-scrim]");
    const goTo = (href) => {
      if (!href) return;
      const el = document.getElementById(href.replace(/^#/, ""));
      if (el) el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    };
    if (palette) {
      const items = $$(".palette__item", palette);
      const input = $("input", palette);
      let idx = 0;
      const openP = () => {
        scrim?.classList.add("open");
        palette.classList.add("open");
        idx = 0;
        items.forEach((it, i) => it.setAttribute("aria-selected", String(i === idx)));
        setTimeout(() => input?.focus(), 60);
      };
      const closeP = () => {
        scrim?.classList.remove("open");
        palette.classList.remove("open");
        if (input) input.value = "";
        items.forEach((it) => (it.style.display = ""));
      };
      const filter = () => {
        const q = (input?.value || "").toLowerCase();
        items.forEach((it) => {
          it.style.display = it.textContent.toLowerCase().includes(q) ? "" : "none";
        });
      };
      $$("[data-cmdk-open]").forEach((b) => b.addEventListener("click", openP, opts));
      scrim?.addEventListener("click", closeP, opts);
      input?.addEventListener("input", filter, opts);
      document.addEventListener("keydown", (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
          e.preventDefault();
          palette.classList.contains("open") ? closeP() : openP();
        }
        if (!palette.classList.contains("open")) return;
        const vis = items.filter((it) => it.style.display !== "none");
        if (e.key === "Escape") closeP();
        if (e.key === "ArrowDown") { e.preventDefault(); idx = Math.min(idx + 1, vis.length - 1); items.forEach((it) => it.setAttribute("aria-selected", String(it === vis[idx]))); }
        if (e.key === "ArrowUp") { e.preventDefault(); idx = Math.max(idx - 1, 0); items.forEach((it) => it.setAttribute("aria-selected", String(it === vis[idx]))); }
        if (e.key === "Enter") { const sel = vis[idx]; if (sel) { closeP(); goTo(sel.dataset.go); } }
      }, opts);
      items.forEach((it) => it.addEventListener("click", () => { closeP(); goTo(it.dataset.go); }, opts));
    }

    /* ---------- Accordion ---------- */
    $$(".acc-head").forEach((head) => {
      head.addEventListener("click", () => {
        const item = head.closest(".acc-item");
        const acc = head.closest(".accordion");
        const wasOpen = item.classList.contains("open");
        if (acc?.dataset.single !== "false") $$(".acc-item", acc).forEach((i) => i.classList.remove("open"));
        item.classList.toggle("open", !wasOpen);
        head.setAttribute("aria-expanded", String(!wasOpen));
      }, opts);
    });

    /* ---------- Dropdown menu ---------- */
    $$(".menu-wrap").forEach((wrap) => {
      const btn = $("[data-menu-trigger]", wrap);
      btn?.addEventListener("click", (e) => { e.stopPropagation(); wrap.classList.toggle("open"); }, opts);
    });
    document.addEventListener("click", () => $$(".menu-wrap.open").forEach((w) => w.classList.remove("open")), opts);

    /* ---------- Toasts ---------- */
    const stack = $(".toast-stack");
    const toastTemplates = {
      success: { cls: "", ico: '<path d="M5 13l4 4L19 7"/>', title: "You're all set", body: "Copy a command and run it to get going." },
      info: { cls: "info", ico: '<path d="M12 8h.01M11 12h1v4h1"/><circle cx="12" cy="12" r="9"/>', title: "Heads up", body: "Open the docs for the full walkthrough." },
      warn: { cls: "warn", ico: '<path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>', title: "One thing first", body: "Add an API key before your first chat." },
    };
    window.vellumToast = (kind = "success") => {
      if (!stack) return;
      const t = toastTemplates[kind] || toastTemplates.success;
      const el = document.createElement("div");
      el.className = `toast ${t.cls}`;
      el.innerHTML = `
        <span class="ico"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${t.ico}</svg></span>
        <div><b>${t.title}</b><p>${t.body}</p></div>
        <button class="x" aria-label="Dismiss"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg></button>`;
      stack.appendChild(el);
      const remove = () => { el.classList.add("leaving"); setTimeout(() => el.remove(), reduce ? 0 : 260); };
      el.querySelector(".x").addEventListener("click", remove);
      setTimeout(remove, 4200);
    };
    document.addEventListener("click", (e) => {
      const b = e.target.closest("[data-toast]");
      if (b) window.vellumToast(b.dataset.toast);
    }, opts);

    /* The pointer physics below only make sense with a real pointer. */
    if (finePointer && !reduce) {
      $$("[data-magnetic]").forEach((btn) => {
        const strength = parseFloat(btn.dataset.magnetic) || 0.32;
        btn.addEventListener("pointermove", (e) => {
          const r = btn.getBoundingClientRect();
          btn.style.transform = `translate(${(e.clientX - r.left - r.width / 2) * strength}px, ${(e.clientY - r.top - r.height / 2) * strength}px)`;
        }, opts);
        btn.addEventListener("pointerleave", () => { btn.style.transform = ""; }, opts);
      });
      $$("[data-tilt]").forEach((card) => {
        const max = parseFloat(card.dataset.tilt) || 7;
        card.addEventListener("pointermove", (e) => {
          const r = card.getBoundingClientRect();
          card.style.setProperty("--ry", `${((e.clientX - r.left) / r.width - 0.5) * max * 2}deg`);
          card.style.setProperty("--rx", `${(0.5 - (e.clientY - r.top) / r.height) * max * 2}deg`);
        }, opts);
        card.addEventListener("pointerleave", () => {
          card.style.setProperty("--ry", "0deg");
          card.style.setProperty("--rx", "0deg");
        }, opts);
      });
      $$(".card--spotlight").forEach((card) => {
        card.addEventListener("pointermove", (e) => {
          const r = card.getBoundingClientRect();
          card.style.setProperty("--mx", `${e.clientX - r.left}px`);
          card.style.setProperty("--my", `${e.clientY - r.top}px`);
        }, opts);
      });

      /* Highlighter cursor (singleton) */
      let dot = document.querySelector(".cursor-dot");
      if (!dot) {
        dot = document.createElement("div");
        dot.className = "cursor-dot";
        dot.setAttribute("aria-hidden", "true");
        document.body.appendChild(dot);
      }
      window.addEventListener("pointermove", (e) => {
        dot.style.setProperty("--cx", `${e.clientX}px`);
        dot.style.setProperty("--cy", `${e.clientY}px`);
      }, passive);
      document.addEventListener("pointerleave", () => { dot.style.opacity = "0"; }, opts);
      document.addEventListener("pointerenter", () => { dot.style.opacity = "1"; }, opts);
    }

    return () => {
      ac.abort();
      observers.forEach((o) => o.disconnect());
      document.body.style.overflow = "";
    };
  }, [key]);
}
