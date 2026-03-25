"""HTML page template renderer for the web app."""

from __future__ import annotations

from html import escape


def render_home_page(
    *,
    date_options: str,
    wafer_options: str,
    structure_options: str,
    search_query: str,
    sort_by: str,
    sort_dir: str,
    n_runs: int,
    run_pager: str,
    table_html: str,
    run_html: str,
) -> str:
    """Render the full home page HTML with embedded CSS and JS."""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>muGPD Analysis Browser</title>
  <style>
    :root {{
      --bg: #f5f3ef;
      --card: #fffdfa;
      --ink: #1f2528;
      --muted: #5f676c;
      --accent: #1f4f6b;
      --accent-soft: #e9f0f5;
      --border: #d7d1c6;
      --error: #b42318;
      --shadow: 0 6px 18px rgba(31, 37, 40, 0.07);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Source Sans 3", "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 100% 0%, #eef2f4 0, transparent 36%),
        radial-gradient(circle at 0% 100%, #f2ece2 0, transparent 35%),
        var(--bg);
    }}
    .layout {{ max-width: 1400px; margin: 0 auto; padding: 24px; display: grid; gap: 16px; }}
    h1 {{
      margin: 0;
      letter-spacing: 0.02em;
      font-size: 1.5rem;
      font-family: "Source Serif 4", "Georgia", serif;
      font-weight: 600;
    }}
    h2 {{
      margin: 0 0 12px 0;
      font-size: 1.2rem;
      padding-bottom: 6px;
      border-bottom: 1px dashed var(--border);
    }}
    h3 {{ margin: 0 0 10px 0; font-size: 1.05rem; }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 16px;
      box-shadow: var(--shadow);
    }}
    .card:first-child {{ background: linear-gradient(135deg, #ffffff 0%, #f4f1ea 100%); }}
    .toolbar {{ display: flex; gap: 12px; flex-wrap: wrap; align-items: end; }}
    .field {{ display: grid; gap: 6px; min-width: 220px; }}
    .field label {{ font-weight: 600; font-size: 0.9rem; }}
    input, select {{
      border-radius: 10px;
      border: 1px solid var(--border);
      padding: 8px;
      background: #fff;
      font-family: inherit;
      color: var(--ink);
    }}
    select[multiple] {{ min-height: 120px; max-height: 180px; }}
    select[multiple]:focus {{ outline: 2px solid var(--accent-soft); border-color: var(--accent); }}
    .btn {{
      border: 0;
      border-radius: 10px;
      background: var(--accent);
      color: #fff;
      font-weight: 700;
      padding: 10px 14px;
      cursor: pointer;
      text-decoration: none;
      display: inline-block;
      transition: filter 0.12s ease;
    }}
    .btn:hover {{ filter: brightness(1.02); }}
    .btn.secondary {{ background: #3f4e4f; }}
    .runs-controls {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin: 2px 0 10px 0;
      font-size: 0.9rem;
    }}
    .runs-controls label {{ display: inline-flex; gap: 4px; align-items: center; }}
    .runs-table-wrap {{ max-height: 62vh; overflow: auto; border-radius: 10px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{
      border-bottom: 1px solid var(--border);
      padding: 8px;
      text-align: left;
      vertical-align: top;
    }}
    th {{ background: #f5f1e5; font-size: 0.92rem; }}
    .runs-table th {{ position: sticky; top: 0; z-index: 2; }}
    .runs-table tbody tr:nth-child(even) {{ background: #fcfbf8; }}
    .runs-table tbody tr:hover {{ background: #eef3f7; }}
    .sort-link {{ color: inherit; text-decoration: none; font-weight: 700; }}
    .sort-link:hover {{ text-decoration: underline; }}
    .muted {{ color: var(--muted); margin: 0; }}
    .error {{ color: var(--error); font-weight: 600; }}
    .fig-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 12px;
    }}
    .figure-card {{
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 10px;
      background: #ffffff;
      transition: box-shadow 0.16s ease;
    }}
    .figure-card:hover {{ box-shadow: 0 8px 18px rgba(31, 37, 40, 0.1); }}
    .figure-card img {{
      width: 100%;
      height: 170px;
      object-fit: contain;
      background: #f9f9f9;
      border-radius: 8px;
    }}
    .figure-summary {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 8px;
      font-size: 0.86rem;
      background: #fff;
    }}
    .figure-summary th, .figure-summary td {{
      border-bottom: 1px solid var(--border);
      padding: 4px 6px;
      vertical-align: top;
    }}
    .figure-summary th {{ width: 45%; color: var(--muted); font-weight: 600; background: #f8f5ef; }}
    .figure-meta {{ margin-top: 8px; font-size: 0.88rem; color: var(--muted); }}
    .pager {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin: 10px 0 14px 0;
    }}
    .pager-links {{ display: flex; gap: 10px; align-items: center; }}
    .pager a {{ color: var(--accent); text-decoration: none; font-weight: 700; }}
    .pager-page, .pager-arrow {{
      min-width: 28px;
      height: 28px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0 6px;
      background: #fff;
      color: var(--ink);
      text-decoration: none;
      font-weight: 600;
      transition: background 0.12s ease, color 0.12s ease;
    }}
    .pager-page:hover, .pager-arrow:hover {{ background: var(--accent-soft); }}
    .pager-page.current {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
    .pager-arrow.disabled {{ opacity: 0.5; pointer-events: none; background: #f5f5f5; }}
    .pager-ellipsis {{ color: var(--muted); padding: 0 4px; }}
    details {{
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 10px 12px;
      background: #fff;
    }}
    details + details {{ margin-top: 10px; }}
    summary {{ cursor: pointer; font-weight: 700; }}

    .modal {{
      position: fixed; inset: 0; background: rgba(10, 16, 18, 0.86); display: none;
      align-items: center; justify-content: center; z-index: 1000; padding: 18px;
    }}
    .modal.open {{ display: flex; }}
    .modal-content {{
      position: relative; width: min(96vw, 1500px); height: min(92vh, 950px); display: grid;
      grid-template-rows: 1fr auto; gap: 10px; background: #12181c; border: 1px solid #2e3a42;
      border-radius: 12px; padding: 12px;
    }}
    .modal-image-wrap {{
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 0;
    }}
    .modal-image-wrap img {{
      max-width: 100%;
      max-height: 100%;
      object-fit: contain;
      border-radius: 8px;
      background: #0a0f12;
    }}
    .modal-caption {{
      color: #d6dde2;
      font-size: 0.9rem;
      line-height: 1.3;
      word-break: break-word;
    }}
    .modal-summary {{ margin-top: 8px; width: 100%; }}
    .modal-summary table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.88rem;
      color: #d6dde2;
    }}
    .modal-summary th, .modal-summary td {{
      border-bottom: 1px solid #344149;
      padding: 5px 8px;
      text-align: left;
    }}
    .modal-summary th {{
      width: 42%;
      color: #9eb0bc;
      font-weight: 600;
      background: rgba(255, 255, 255, 0.02);
    }}
    .modal-btn {{
      position: absolute; border: 1px solid #4a5c66; background: rgba(18, 24, 28, 0.86);
      color: #ecf2f6; border-radius: 9px; width: 40px; height: 40px; display: inline-flex;
      align-items: center; justify-content: center; cursor: pointer; font-size: 1.1rem;
    }}
    .modal-btn:hover {{ background: rgba(31, 79, 107, 0.8); }}
    .modal-prev {{ left: 14px; top: 50%; transform: translateY(-50%); }}
    .modal-next {{ right: 14px; top: 50%; transform: translateY(-50%); }}
    .modal-close {{ right: 12px; top: 12px; }}

    @media (max-width: 780px) {{
      .layout {{ padding: 14px; gap: 12px; }}
      h1 {{ font-size: 1.25rem; }}
      .field {{ min-width: 100%; }}
      .toolbar {{ gap: 10px; }}
      .pager {{ justify-content: center; }}
      .pager-links {{ flex-wrap: wrap; justify-content: center; }}
      .modal-content {{ width: 98vw; height: 86vh; padding: 10px; }}
    }}
  </style>
</head>
<body>
  <main class="layout">
    <section class="card">
      <h1>muGPD Analysis Browser</h1>
    </section>

    <section class="card">
      <h2>Filters</h2>
      <form method="get" class="toolbar">
        <input type="hidden" name="filters" value="1" />
        <div class="field">
          <label for="date">Acquisition date</label>
          <select id="date" name="date" multiple data-toggle-multi>{date_options}</select>
        </div>
        <div class="field">
          <label for="wafer">Wafer</label>
          <select id="wafer" name="wafer" multiple data-toggle-multi>{wafer_options}</select>
        </div>
        <div class="field">
          <label for="structure">Structure</label>
          <select id="structure" name="structure" multiple data-toggle-multi>
            {structure_options}
          </select>
        </div>
        <div class="field">
          <label for="q">Search run</label>
          <input
            id="q"
            name="q"
            value="{escape(search_query)}"
            placeholder="run id, wafer, structure..."
          />
        </div>
        <input type="hidden" name="sort_by" value="{escape(sort_by)}" />
        <input type="hidden" name="sort_dir" value="{escape(sort_dir)}" />
        <button class="btn" type="submit">Apply filters</button>
        <a class="btn secondary" href="/?refresh=1">Remove filters</a>
      </form>
    </section>

    <section class="card">
      <h2>Runs ({n_runs})</h2>
      <div class="runs-controls">
        <span class="muted">Columns</span>
        <label><input type="checkbox" data-col-toggle="run" checked /> Run</label>
        <label><input type="checkbox" data-col-toggle="created" checked /> Created</label>
        <label><input type="checkbox" data-col-toggle="dates" checked /> Date(s)</label>
        <label><input type="checkbox" data-col-toggle="wafers" checked /> Wafer(s)</label>
        <label><input type="checkbox" data-col-toggle="structures" checked /> Structure(s)</label>
      </div>
      {run_pager}
      {table_html}
    </section>

    {run_html}
  </main>

  <div id="image-modal" class="modal" aria-hidden="true">
    <div class="modal-content" role="dialog" aria-modal="true" aria-label="Image preview">
      <button
        id="modal-close"
        class="modal-btn modal-close"
        type="button"
        aria-label="Close"
      >✕</button>
      <button
        id="modal-prev"
        class="modal-btn modal-prev"
        type="button"
        aria-label="Previous image"
      >←</button>
      <button
        id="modal-next"
        class="modal-btn modal-next"
        type="button"
        aria-label="Next image"
      >→</button>
      <div class="modal-image-wrap"><img id="modal-image" src="" alt="" /></div>
      <div id="modal-caption" class="modal-caption"></div>
      <div id="modal-summary" class="modal-summary"></div>
    </div>
  </div>

  <script>
    (function () {{
      const selects = document.querySelectorAll('select[multiple][data-toggle-multi]');
      selects.forEach((select) => {{
        let lastIndex = -1;
        select.addEventListener('mousedown', (event) => {{
          const option = event.target;
          if (!(option instanceof HTMLOptionElement)) {{
            return;
          }}
          event.preventDefault();
          const options = Array.from(select.options);
          const clickedIndex = options.indexOf(option);
          if (clickedIndex < 0) {{
            return;
          }}
          if (event.shiftKey && lastIndex >= 0) {{
            const start = Math.min(lastIndex, clickedIndex);
            const end = Math.max(lastIndex, clickedIndex);
            for (let idx = start; idx <= end; idx += 1) {{
              options[idx].selected = true;
            }}
          }} else if (event.ctrlKey || event.metaKey) {{
            option.selected = !option.selected;
          }} else {{
            options.forEach((entry) => {{
              entry.selected = (entry === option);
            }});
          }}
          lastIndex = clickedIndex;
          select.focus();
        }});
      }});

      const colToggles = Array.from(document.querySelectorAll('[data-col-toggle]'));
      const storageKey = 'mugpd-run-columns';
      const saved = localStorage.getItem(storageKey);
      const visibleCols = saved ? JSON.parse(saved) : {{
        run: true,
        created: true,
        dates: true,
        wafers: true,
        structures: true,
      }};

      function applyColVisibility() {{
        colToggles.forEach((toggle) => {{
          const key = toggle.getAttribute('data-col-toggle') || '';
          const visible = visibleCols[key] !== false;
          toggle.checked = visible;
          document.querySelectorAll(`.col-${{key}}`).forEach((el) => {{
            el.style.display = visible ? '' : 'none';
          }});
        }});
      }}

      colToggles.forEach((toggle) => {{
        toggle.addEventListener('change', () => {{
          const key = toggle.getAttribute('data-col-toggle') || '';
          visibleCols[key] = toggle.checked;
          localStorage.setItem(storageKey, JSON.stringify(visibleCols));
          applyColVisibility();
        }});
      }});
      applyColVisibility();

      const modal = document.getElementById('image-modal');
      const modalImage = document.getElementById('modal-image');
      const modalCaption = document.getElementById('modal-caption');
      const modalSummary = document.getElementById('modal-summary');
      const modalPrev = document.getElementById('modal-prev');
      const modalNext = document.getElementById('modal-next');
      const modalClose = document.getElementById('modal-close');
      const figureLinks = Array.from(document.querySelectorAll('a.figure-open[data-full]'));
      let currentIndex = -1;

      function escapeHtml(text) {{
        return String(text)
          .replaceAll('&', '&amp;')
          .replaceAll('<', '&lt;')
          .replaceAll('>', '&gt;')
          .replaceAll('"', '&quot;')
          .replaceAll("'", '&#39;');
      }}

      function renderModalSummary(summaryRaw) {{
        if (!modalSummary) {{
          return;
        }}
        if (!summaryRaw) {{
          modalSummary.innerHTML = '';
          return;
        }}

        const rows = summaryRaw
          .split('||')
          .map((chunk) => chunk.split('::'))
          .filter((pair) => pair.length >= 2);

        if (rows.length === 0) {{
          modalSummary.innerHTML = '';
          return;
        }}

        const rowsHtml = rows
          .map((pair) => (
            '<tr>'
            + `<th>${{escapeHtml(pair[0])}}</th>`
            + `<td>${{escapeHtml(pair.slice(1).join('::'))}}</td>`
            + '</tr>'
          ))
          .join('');

        modalSummary.innerHTML = `<table><tbody>${{rowsHtml}}</tbody></table>`;
      }}

      function setModalImage(index) {{
        if (!modalImage || !modalCaption || figureLinks.length === 0) {{
          return;
        }}
        const safeIndex = (index + figureLinks.length) % figureLinks.length;
        currentIndex = safeIndex;
        const link = figureLinks[safeIndex];
        const full = link.getAttribute('data-full') || link.getAttribute('href') || '';
        const caption = link.getAttribute('data-caption') || '';
        const summary = link.getAttribute('data-summary') || '';
        modalImage.setAttribute('src', full);
        modalImage.setAttribute('alt', caption || 'Image preview');
        modalCaption.textContent = caption;
        renderModalSummary(summary);

        const prevLink = figureLinks[(safeIndex - 1 + figureLinks.length) % figureLinks.length];
        const nextLink = figureLinks[(safeIndex + 1) % figureLinks.length];
        const prevSrc = prevLink.getAttribute('data-full') || prevLink.getAttribute('href') || '';
        const nextSrc = nextLink.getAttribute('data-full') || nextLink.getAttribute('href') || '';
        if (prevSrc) {{
          const prevImg = new Image();
          prevImg.src = prevSrc;
        }}
        if (nextSrc) {{
          const nextImg = new Image();
          nextImg.src = nextSrc;
        }}
      }}

      function openModal(index) {{
        if (!modal) {{
          return;
        }}
        setModalImage(index);
        modal.classList.add('open');
        modal.setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';
      }}

      function closeModal() {{
        if (!modal) {{
          return;
        }}
        modal.classList.remove('open');
        modal.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
      }}

      figureLinks.forEach((link, index) => {{
        link.addEventListener('click', (event) => {{
          event.preventDefault();
          openModal(index);
        }});
      }});

      if (modalPrev) {{
        modalPrev.addEventListener('click', () => setModalImage(currentIndex - 1));
      }}
      if (modalNext) {{
        modalNext.addEventListener('click', () => setModalImage(currentIndex + 1));
      }}
      if (modalClose) {{
        modalClose.addEventListener('click', closeModal);
      }}
      if (modal) {{
        modal.addEventListener('click', (event) => {{
          if (event.target === modal) {{
            closeModal();
          }}
        }});
      }}

      document.addEventListener('keydown', (event) => {{
        if (!modal || !modal.classList.contains('open')) {{
          return;
        }}
        if (event.key === 'Escape') {{
          closeModal();
        }} else if (event.key === 'ArrowLeft') {{
          setModalImage(currentIndex - 1);
        }} else if (event.key === 'ArrowRight') {{
          setModalImage(currentIndex + 1);
        }}
      }});
    }})();
  </script>
</body>
</html>"""
