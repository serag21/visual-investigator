# Visual Investigator — private beta runtime

This branch contains the application runtime only. It is an invitation-gated
experimental service, not a verified diagnostic or compatibility authority.

Render Free runs the pinned Docker image with managed HTTPS; Neon Free PostgreSQL
stores invitation revocations, quotas and optional feedback. Set GEMINI_API_KEY,
VI_SESSION_SECRET, VI_INVITE_HASHES and VI_DATABASE_URL in hosting secret settings.
Never commit their values. Do not use an ephemeral SQLite path on Render.

Deploy this branch explicitly, with automatic deploys disabled. Confirm the
workspace has no payment method and both services remain on Free before creation.
The activation process limits real provider checks separately; the configuration
request ceiling is an abuse control, not a billing guarantee.

Photos/context stay in process memory until expiry or restart; explicit browser
saves are readable, not encrypted. Users must consent to Gemini unpaid-tier data
use and attest they are eligible adults in supported regions outside EEA/UK/CH.
No invitations to real testers should be sent before external and phone checks.

Normal local development: install `.[app]`, then run
`python -m investigator.server --max-calls 0` (http://127.0.0.1:8765).
The zero-call default in this command intentionally prevents paid/live experiments.

Operator controls: `python -m investigator.admin --help`, with private configuration
supplied through environment variables. The owner interface can revoke members
or disable all access. Revocation cannot erase previously downloaded/device data.

Source publication and successful local tests do not establish a live deployment,
physical camera support, accurate model answers or commercial differentiation.
