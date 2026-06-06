# FRIDAY — Landing page & docs

The marketing site and documentation for [FRIDAY](https://github.com/SanthoshReddy352/Friday_Linux),
the local-first voice AI assistant. Built with **Next.js (App Router)** + **Tailwind CSS**, designed
to deploy to **Vercel** with zero configuration.

```
web/
├── app/
│   ├── page.js              # landing page
│   ├── layout.js            # root layout (fonts, metadata)
│   ├── globals.css          # design tokens + animations
│   ├── icon.svg             # favicon
│   └── docs/
│       ├── layout.js        # docs shell (sidebar + mobile drawer)
│       ├── page.js          # docs overview
│       ├── getting-started/
│       ├── installation/
│       ├── architecture/
│       ├── how-it-works/    # the deterministic-router story
│       ├── capabilities/
│       ├── adding-tools/
│       └── configuration/
└── components/              # Nav, Footer, VoiceOrb, RouterPipeline, CodeBlock, doc-ui…
```

## Run locally

```bash
cd web
npm install
npm run dev          # http://localhost:3000
```

Build a production bundle:

```bash
npm run build
npm start
```

## Deploy to Vercel

This site lives in the `web/` subdirectory of the FRIDAY repo, so the **Root Directory**
setting is the one thing you must get right.

### Option A — Dashboard (recommended)

1. Push this repo to GitHub (it already is).
2. Go to [vercel.com/new](https://vercel.com/new) and **Import** the `Friday_Linux` repo.
3. In the import screen, set **Root Directory** → `web`.
   Vercel auto-detects Next.js; leave Build Command (`next build`) and Output as defaults.
4. Click **Deploy**. You get a `*.vercel.app` URL in ~1 minute.
5. (Optional) Add a custom domain under **Settings → Domains**.

Every push to `main` redeploys automatically; pull requests get preview URLs.

### Option B — Vercel CLI

```bash
npm i -g vercel
cd web
vercel            # first run: link project, set root to the current dir
vercel --prod     # promote to production
```

### Notes

- **Don't** set Root Directory to the repo root — the Python project there is not a web app.
- No environment variables are required for the site to build or run.
- The `metadataBase` URL in `app/layout.js` is a placeholder
  (`https://friday-assistant.vercel.app`). Update it to your real domain so Open Graph / Twitter
  card URLs resolve correctly.

## Editing content

- **Landing copy/sections** — `app/page.js` (each section is a small component at the bottom).
- **Docs pages** — one folder per page under `app/docs/`. Add a page by creating
  `app/docs/<slug>/page.js` and adding it to the sidebar in `components/docs-nav.js`
  (the prev/next links update automatically from that file).
- **Design tokens / colors / animations** — `tailwind.config.js` and `app/globals.css`.
- **Artwork** — `components/VoiceOrb.js` (hero) and `components/RouterPipeline.js`
  (routing diagram) are inline SVG/CSS; no external image assets to manage.
