---
name: blog-watcher
description: "Track blogs / RSS feeds and surface new posts since the last check."
source: "hermes-agent skills/research/blogwatcher (MIT — see docs/third_party_credits.md)"
adapted_for: "FRIDAY local voice assistant"
requires:
  - web_extract
  - web_crawl
  - scheduler
---

# blog watcher

## When to use

The user wants to monitor a blog / Substack / RSS feed and be told when there's something new — either ad-hoc ("any new posts on the Anthropic blog?") or as a recurring routine ("brief me each morning on what's new on Hacker News front page").

Pair this skill with the scheduler (P3.9) for the recurring case.

## How to use

1. **Identify the source**. Accept any of:
   - A direct RSS / Atom URL.
   - A site URL — try `<site>/feed`, `<site>/rss`, `<site>/atom.xml` in that order.
2. **Fetch** with `web_extract`. Most feeds are small enough to skip `summarize_if_over`.
3. **Diff against last-seen**. Cache the most-recent `<entry>`/`<item>` GUID per source in `facts(namespace='blogwatcher', key='<source>:last_guid')`. New posts are everything above the cached GUID, in order.
4. **For each new post**:
   - Pull title + URL from the feed entry.
   - If the user asked for summaries, follow the link with `web_extract` and summarise with `llm_chat` in ≤2 sentences.
   - Otherwise just announce title + link.
5. **Update the cached GUID** to the newest seen so the next run only reports newer items.

For a recurring brief, register a routine in `config/routines.yaml`:
```yaml
routines:
  - name: morning_blog_brief
    cron: "0 8 * * *"
    command: "check my blog watch list and summarise new posts"
    quiet_hours: { start: 22, end: 7 }
```

## Examples

- "Friday, watch the Anthropic blog and tell me when there's something new."
- "Friday, any new posts on Hacker News front page since last night?"
- "Friday, set up a morning briefing on lobste.rs and arstechnica.com."

## Common failures and recovery

- **No feed at the conventional paths** → tell the user "I couldn't find an RSS feed at <site>; give me the feed URL directly".
- **Feed parser raises** → fall back to fetching the index page and using `web_crawl` depth=1 to discover article titles.
- **Cache says nothing new but the user expected something** → wipe the cached GUID with `forget_memory blogwatcher:<source>:last_guid` and re-run.
