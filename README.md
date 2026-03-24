# master_thesis

## HTML browser alternative to Streamlit

This repository now includes a lightweight web UI based on Flask:

- Entry point: `mugpd-web`
- Compatibility module: `src/mugpd/webapp.py`
- Refactored package: `src/mugpd/web/`

### Web package structure

- `src/mugpd/web/app.py`: Flask routes and OOP renderer (`BrowserWebApp`)
- `src/mugpd/web/logic.py`: pure helpers for formatting, sorting, table extraction, path safety
- `src/mugpd/web/__init__.py`: package entry exports

It is designed to be faster than Streamlit for browsing many figures by using:

- Lazy image loading in the browser
- Thumbnail caching on disk (`~/.cache/mugpd/thumbnails`)
- Plain HTML tables for run and task data

### Install web dependencies

```bash
pip install .[web]
```

### Run the web app

```bash
mugpd-web --results "$HOME/results" --host 127.0.0.1 --port 7860
```

Then open `http://127.0.0.1:7860` in your browser.