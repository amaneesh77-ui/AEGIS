"""
Report export service.
Generates a self-contained HTML research report from a collection.
"""

from __future__ import annotations
import time
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from database import get_db

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _ts(ts: int) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


@router.get("/collection/{collection_id}", response_class=HTMLResponse)
def export_collection_report(collection_id: str):
    """Generate a self-contained HTML report for a collection."""
    db = get_db()

    coll = db.execute(
        "SELECT * FROM collections WHERE id=?", (collection_id,)
    ).fetchone()
    if not coll:
        raise HTTPException(status_code=404, detail="Collection not found")

    docs = db.execute(
        "SELECT * FROM documents WHERE collection_id=? ORDER BY created_at",
        (collection_id,),
    ).fetchall()

    entities = db.execute(
        """SELECT e.entity_type, e.value, COUNT(*) as freq
           FROM entities e JOIN documents d ON d.id=e.doc_id
           WHERE d.collection_id=?
           GROUP BY e.entity_type, e.value ORDER BY freq DESC LIMIT 200""",
        (collection_id,),
    ).fetchall()

    annotations = db.execute(
        """SELECT a.*, d.filename FROM annotations a
           JOIN documents d ON d.id=a.doc_id
           WHERE d.collection_id=? ORDER BY a.created_at""",
        (collection_id,),
    ).fetchall()

    db.close()

    # Group entities by type
    ent_by_type: dict = {}
    for e in entities:
        ent_by_type.setdefault(e["entity_type"], []).append(e)

    # Build entity tables HTML
    ent_html = ""
    for etype, items in ent_by_type.items():
        rows_html = "".join(
            f"<tr><td>{_esc(e['value'])}</td><td>{e['freq']}</td></tr>"
            for e in items[:30]
        )
        ent_html += f"""
        <h3>{_esc(etype)}</h3>
        <table>
          <thead><tr><th>Value</th><th>Mentions</th></tr></thead>
          <tbody>{rows_html}</tbody>
        </table>"""

    # Documents table
    docs_html = "".join(f"""
        <tr>
          <td>{_esc(d['filename'])}</td>
          <td>{_esc(d['doc_type'])}</td>
          <td>{d['page_count'] or 0}</td>
          <td>{(d['word_count'] or 0):,}</td>
          <td>{_esc(d['ingest_status'])}</td>
          <td>{_esc(d['manufacturer'] or '-')}</td>
        </tr>""" for d in docs)

    # Annotations HTML
    ann_html = "".join(f"""
        <div class="ann-item ann-{_esc(a['kind'])}">
          <div class="ann-meta">
            <span class="ann-kind">{_esc(a['kind'])}</span>
            <span class="ann-doc">{_esc(a['filename'])}</span>
            <span class="ann-time">{_ts(a['created_at'])}</span>
          </div>
          <div class="ann-note">{_esc(a['note'] or '')}</div>
        </div>""" for a in annotations) or "<p>No annotations yet.</p>"

    generated_at = _ts(int(time.time()))
    title = f"AEGIS Research Report - {coll['name']}"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{_esc(title)}</title>
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:#0d1117;color:#e6edf3;margin:0;padding:40px;font-size:14px;line-height:1.6}}
  h1{{font-size:28px;font-weight:700;margin-bottom:4px;color:#e6edf3}}
  h2{{font-size:18px;font-weight:600;margin:36px 0 12px;padding-bottom:8px;
      border-bottom:1px solid #30363d;color:#e6edf3}}
  h3{{font-size:14px;font-weight:600;color:#8b949e;text-transform:uppercase;
      letter-spacing:0.5px;margin:20px 0 8px}}
  .meta{{color:#8b949e;font-size:13px;margin-bottom:32px}}
  .meta span{{margin-right:24px}}
  table{{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:20px}}
  th{{background:#161b22;color:#8b949e;font-weight:600;font-size:11px;
      text-transform:uppercase;letter-spacing:0.5px;padding:8px 12px;
      text-align:left;border-bottom:1px solid #30363d}}
  td{{padding:8px 12px;border-bottom:1px solid #21262d}}
  .ann-item{{background:#161b22;border:1px solid #30363d;border-radius:8px;
             padding:12px 16px;margin-bottom:10px}}
  .ann-meta{{display:flex;gap:12px;margin-bottom:6px;font-size:12px;color:#8b949e}}
  .ann-kind{{font-weight:600;text-transform:uppercase;font-size:10px;
             padding:2px 8px;border-radius:12px;background:#1f2d3d;color:#58a6ff}}
  .ann-doc{{color:#58a6ff}}
  .footer{{margin-top:40px;padding-top:20px;border-top:1px solid #30363d;
           color:#8b949e;font-size:12px}}
  @media print{{body{{background:white;color:black}}th,td{{color:black}}}}
</style>
</head>
<body>
<h1>{_esc(coll['name'])}</h1>
<div class="meta">
  <span>Generated: {generated_at}</span>
  <span>Documents: {len(docs)}</span>
  <span>Entities: {len(entities)}</span>
  <span>Annotations: {len(annotations)}</span>
  {f'<span>{_esc(coll["description"])}</span>' if coll['description'] else ''}
</div>

<h2>Documents indexed</h2>
<table>
  <thead>
    <tr><th>Filename</th><th>Type</th><th>Pages</th><th>Words</th><th>Status</th><th>Manufacturer</th></tr>
  </thead>
  <tbody>{docs_html}</tbody>
</table>

<h2>Extracted entities</h2>
{ent_html or '<p style="color:#8b949e">No entities extracted yet.</p>'}

<h2>Research annotations</h2>
{ann_html}

<div class="footer">
  AEGIS - Automated Expert Guidance &amp; Intelligence System &nbsp;|&nbsp;
  OFFICIAL SENSITIVE - handle accordingly &nbsp;|&nbsp;
  Generated {generated_at}
</div>
</body>
</html>"""

    return HTMLResponse(content=html, headers={
        "Content-Disposition": f'attachment; filename="AEGIS_Report_{collection_id[:8]}.html"'
    })


def _esc(s) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
