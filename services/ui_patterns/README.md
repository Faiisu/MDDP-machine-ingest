# MDDP System UI Patterns

This folder defines the visual contract for service consoles in the MDDP system. The current direction is an instrument-rack interface: dark layered surfaces, phosphor accents, mono operational labels, and a rail that groups work by operator intent.

## Files

- `services/influxdb/static/ui-tokens.css` — portable theme tokens and type settings.
- `services/influxdb/static/ui-patterns.css` — shell, rail, panel, card, form, button, terminal, and responsive primitives.
- `services/influxdb/static/style.css` — InfluxDB-specific composition and content styling.

The InfluxDB service is the first reference implementation. Copy the two `ui-*.css` files into a future service's static directory, include them before the service stylesheet, and keep service-specific rules in `style.css`.

## Composition contract

Use this structure for new service consoles:

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

Panels should be named for the operator task, not the implementation layer. Keep the header status, theme selector, clock, keyboard focus, and reduced-motion behavior consistent across services.

## Theme contract

The shared selector reads `data-theme` from the document root. Supported values are `dark-ocean`, `arctic-light`, `emerald-matrix`, `amber-cockpit`, and `dracula`. New services should persist the selected theme under their own local-storage key and use the shared semantic tokens instead of hard-coded colors.
