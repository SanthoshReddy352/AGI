// Single source of truth for the docs sidebar + prev/next navigation.
export const docsNav = [
  {
    title: "Introduction",
    items: [
      { href: "/docs", label: "Overview" },
      { href: "/docs/getting-started", label: "Getting started" },
      { href: "/docs/installation", label: "Installation" },
    ],
  },
  {
    title: "Concepts",
    items: [
      { href: "/docs/architecture", label: "Architecture" },
      { href: "/docs/how-it-works", label: "How routing works" },
      { href: "/docs/capabilities", label: "Capabilities" },
    ],
  },
  {
    title: "Control",
    items: [
      { href: "/docs/commands", label: "Commands & shell" },
      { href: "/docs/telegram", label: "Telegram & remote" },
    ],
  },
  {
    title: "Build",
    items: [
      { href: "/docs/adding-tools", label: "Add a new tool" },
      { href: "/docs/configuration", label: "Configuration" },
    ],
  },
];

// Flattened order for prev/next links.
export const docsOrder = docsNav.flatMap((s) => s.items);
