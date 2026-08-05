# MDDP System UI Design

MDDP service consoles use an instrument-rack visual language: dense but readable operator surfaces, explicit system state, and controls grouped by the task an operator is trying to complete.

## Base files

- [`services/influxdb/static/ui-tokens.css`](../services/influxdb/static/ui-tokens.css) defines themes, semantic colors, typography, radii, and motion tokens.
- [`services/influxdb/static/ui-patterns.css`](../services/influxdb/static/ui-patterns.css) defines the shell, header, sidebar rail, workspace, cards, forms, buttons, terminal, toast, and responsive primitives.
- [`services/influxdb/static/style.css`](../services/influxdb/static/style.css) composes those primitives for the InfluxDB domain.

The InfluxDB service is the reference implementation. A new service should copy the two base files into its own static bundle and keep domain-specific rules in its own `style.css`.

## Composition contract

```text
.dashboard-container
└── .main-header
    └── .main-layout
        ├── .sidebar-nav
        │   └── .nav-tab-btn[data-panel]
        └── .workspace-card
            └── .workspace-panel#panel-*
                └── .pattern-card
```

Panel labels should describe operator intent, such as `Connection setup` or `Retention policy`, instead of implementation details such as `InfluxDB API configuration`.

## Theme contract

The document root owns the active theme through `data-theme`:

```html
<html data-theme="arctic-light">
```

Supported themes:

| Theme | Use |
| --- | --- |
| `arctic-light` | Default light operator workspace. |
| `dark-ocean` | High-contrast dark control room. |
| `emerald-matrix` | Green telemetry-oriented variant. |
| `amber-cockpit` | Warm warning/cockpit variant. |
| `dracula` | Dark purple developer variant. |

Use semantic tokens such as `--bg-panel`, `--text-primary`, `--accent-blue`, `--amber`, and `--red`. Do not hard-code theme colors in service-specific components.

## Interaction rules

- Use visible keyboard focus through `:focus-visible`.
- Respect `prefers-reduced-motion`.
- Give service state a text label as well as a color or pulse indicator.
- Keep destructive actions visually separate from save and test actions.
- Use mono typography for timestamps, endpoints, IDs, tokens, and log output.
- Show an actionable explanation for empty states and errors.
- Persist theme and panel selection using a service-specific local-storage key.

## Adding a new service console

1. Copy `ui-tokens.css` and `ui-patterns.css` into the new service's static directory.
2. Add both files before the service stylesheet in the template.
3. Build a header with service identity, theme selector, status, and clock.
4. Put operator tasks into sidebar panels.
5. Use `.pattern-card`, `.form-group`, `.btn`, `.terminal-wrapper`, and `.badge` before creating new primitives.
6. Add responsive rules only for domain-specific layouts.
7. Add a short entry to the service's README or the root project README.
