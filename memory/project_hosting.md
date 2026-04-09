---
name: App Hosting on Render
description: The Streamlit app (app.py) is hosted on Render — this is the primary interface, not local execution
type: project
---

The GECO HSE Portal (app.py) is deployed and hosted on Render.

**Why:** This is the primary way users interact with the system — not by running locally or using watcher.py.

**How to apply:** When suggesting changes, testing, or debugging, assume the app runs in Render's cloud environment. Local run commands are secondary. Environment variables must be set in Render's dashboard, not just .env. Deployment is via git push to the connected repo.
