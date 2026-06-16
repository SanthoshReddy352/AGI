# Architecture Diagrams

Rendered UML diagrams for [../ARCHITECTURE.md](../ARCHITECTURE.md). Each diagram is a
PNG (rendered from Mermaid) plus its editable `.mmd` source.

| # | Diagram | Type | Image | Source |
|---|---------|------|-------|--------|
| 1 | System context | Flowchart | [01-system-context.png](01-system-context.png) | [.mmd](01-system-context.mmd) |
| 2 | Component architecture | Flowchart | [02-component-architecture.png](02-component-architecture.png) | [.mmd](02-component-architecture.mmd) |
| 3 | Request lifecycle — one turn | Sequence | [03-request-lifecycle.png](03-request-lifecycle.png) | [.mmd](03-request-lifecycle.mmd) |
| 4 | The agent loop | Flowchart | [04-agent-loop.png](04-agent-loop.png) | [.mmd](04-agent-loop.mmd) |
| 5 | Provider layer | Class | [05-provider-layer.png](05-provider-layer.png) | [.mmd](05-provider-layer.mmd) |
| 6 | Tool system | Flowchart | [06-tool-system.png](06-tool-system.png) | [.mmd](06-tool-system.mmd) |
| 7 | Memory model | Entity-Relationship | [07-memory-model.png](07-memory-model.png) | [.mmd](07-memory-model.mmd) |
| 8 | Skills at runtime | Flowchart | [08-skills-runtime.png](08-skills-runtime.png) | [.mmd](08-skills-runtime.mmd) |
| 9 | Process & deployment | Flowchart | [09-process-deployment.png](09-process-deployment.png) | [.mmd](09-process-deployment.mmd) |

## Regenerating

The PNGs are rendered from the `.mmd` sources with
[mermaid-cli](https://github.com/mermaid-js/mermaid-cli):

```bash
# one-time
npm install -g @mermaid-js/mermaid-cli      # or npx @mermaid-js/mermaid-cli

# render every diagram (white background, 2x scale)
for f in docs/diagrams/*.mmd; do
  mmdc -i "$f" -o "${f%.mmd}.png" -b white -s 2
done
```

The `.mmd` sources are also embedded (collapsible) beneath each figure in
`ARCHITECTURE.md`, so they stay in sync as the single source of truth.
