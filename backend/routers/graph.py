"""
Knowledge graph API.
Nodes and edges are built on-the-fly from the entities table.
NetworkX is used in-process for graph algorithms.
"""

from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from database import get_db

router = APIRouter(prefix="/api/graph", tags=["graph"])


def _build_nx_graph(collection_id: Optional[str] = None):
    """Build a NetworkX DiGraph from entity co-occurrence in documents."""
    try:
        import networkx as nx
    except ImportError:
        return None

    db = get_db()
    sql = """
        SELECT e.doc_id, e.entity_type, e.value, d.collection_id
        FROM entities e
        JOIN documents d ON d.id = e.doc_id
        WHERE 1=1
    """
    params: list = []
    if collection_id:
        sql += " AND d.collection_id=?"
        params.append(collection_id)
    rows = db.execute(sql, params).fetchall()
    db.close()

    G = nx.DiGraph()

    # Group entities by document
    from collections import defaultdict
    doc_entities: dict = defaultdict(list)
    for r in rows:
        doc_entities[r["doc_id"]].append(
            {"type": r["entity_type"], "value": r["value"]}
        )

    # Add nodes
    seen_nodes: set = set()
    for entities in doc_entities.values():
        for e in entities:
            node_id = f"{e['type']}::{e['value']}"
            if node_id not in seen_nodes:
                G.add_node(node_id, label=e["value"], node_type=e["type"])
                seen_nodes.add(node_id)

    # Add edges for entities co-occurring in the same document
    for doc_id, entities in doc_entities.items():
        # Connect COMPONENT → MANUFACTURER
        components = [e for e in entities if e["type"] in ("COMPONENT", "PART_NUMBER")]
        mfrs = [e for e in entities if e["type"] == "MANUFACTURER"]
        protocols = [e for e in entities if e["type"] == "PROTOCOL"]
        cves = [e for e in entities if e["type"] == "CVE"]

        for comp in components:
            cid = f"{comp['type']}::{comp['value']}"
            for mfr in mfrs:
                mid = f"MANUFACTURER::{mfr['value']}"
                G.add_edge(cid, mid, edge_type="MANUFACTURED_BY", doc_id=doc_id)
            for proto in protocols:
                pid = f"PROTOCOL::{proto['value']}"
                G.add_edge(cid, pid, edge_type="COMMUNICATES_VIA", doc_id=doc_id)
            for cve in cves:
                vid = f"CVE::{cve['value']}"
                G.add_edge(cid, vid, edge_type="VULNERABLE_TO", doc_id=doc_id)

    return G


@router.get("/nodes")
def get_nodes(collection_id: Optional[str] = None, node_type: Optional[str] = None,
              limit: int = 200):
    """Return graph nodes with degree information."""
    db = get_db()
    sql = """
        SELECT e.entity_type AS node_type, e.value AS label,
               COUNT(DISTINCT e.doc_id) AS doc_count,
               COUNT(*) AS mention_count
        FROM entities e
        JOIN documents d ON d.id = e.doc_id
        WHERE 1=1
    """
    params: list = []
    if collection_id:
        sql += " AND d.collection_id=?"
        params.append(collection_id)
    if node_type:
        sql += " AND e.entity_type=?"
        params.append(node_type)
    sql += " GROUP BY e.entity_type, e.value ORDER BY mention_count DESC LIMIT ?"
    params.append(limit)
    rows = db.execute(sql, params).fetchall()
    db.close()

    return [
        {
            "id": f"{r['node_type']}::{r['label']}",
            "label": r["label"],
            "node_type": r["node_type"],
            "doc_count": r["doc_count"],
            "mention_count": r["mention_count"],
        }
        for r in rows
    ]


@router.get("/edges")
def get_edges(collection_id: Optional[str] = None, limit: int = 500):
    """Return co-occurrence edges between entity nodes."""
    db = get_db()

    sql = """
        SELECT a.entity_type AS src_type, a.value AS src_val,
               b.entity_type AS tgt_type, b.value AS tgt_val,
               COUNT(*) AS weight
        FROM entities a
        JOIN entities b ON b.doc_id = a.doc_id AND b.id != a.id
        JOIN documents d ON d.id = a.doc_id
        WHERE a.entity_type IN ('COMPONENT','PART_NUMBER')
          AND b.entity_type IN ('MANUFACTURER','PROTOCOL','CVE')
    """
    params: list = []
    if collection_id:
        sql += " AND d.collection_id=?"
        params.append(collection_id)
    sql += " GROUP BY src_type,src_val,tgt_type,tgt_val ORDER BY weight DESC LIMIT ?"
    params.append(limit)
    rows = db.execute(sql, params).fetchall()
    db.close()

    edge_type_map = {
        "MANUFACTURER": "MANUFACTURED_BY",
        "PROTOCOL":     "COMMUNICATES_VIA",
        "CVE":          "VULNERABLE_TO",
    }
    return [
        {
            "source": f"{r['src_type']}::{r['src_val']}",
            "target": f"{r['tgt_type']}::{r['tgt_val']}",
            "edge_type": edge_type_map.get(r["tgt_type"], "RELATED_TO"),
            "weight": r["weight"],
        }
        for r in rows
    ]


@router.get("/node/{node_id:path}/neighbours")
def get_neighbours(node_id: str, hops: int = 1, collection_id: Optional[str] = None):
    """Return N-hop neighbourhood around a node."""
    try:
        import networkx as nx
        G = _build_nx_graph(collection_id)
        if G is None or node_id not in G:
            return {"nodes": [], "edges": []}

        subgraph_nodes: set = {node_id}
        frontier = {node_id}
        for _ in range(hops):
            next_frontier: set = set()
            for n in frontier:
                next_frontier.update(G.predecessors(n))
                next_frontier.update(G.successors(n))
            subgraph_nodes.update(next_frontier)
            frontier = next_frontier

        sub = G.subgraph(subgraph_nodes)
        nodes = [
            {"id": n, "label": sub.nodes[n].get("label", n),
             "node_type": sub.nodes[n].get("node_type", "unknown")}
            for n in sub.nodes
        ]
        edges = [
            {"source": u, "target": v,
             "edge_type": sub.edges[u, v].get("edge_type", "RELATED_TO")}
            for u, v in sub.edges
        ]
        return {"nodes": nodes, "edges": edges}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/path")
def find_path(body: dict):
    """Find shortest path between two node IDs."""
    src = body.get("source", "")
    tgt = body.get("target", "")
    collection_id = body.get("collection_id")

    try:
        import networkx as nx
        G = _build_nx_graph(collection_id)
        if G is None:
            raise HTTPException(status_code=503, detail="networkx not installed")

        if src not in G or tgt not in G:
            return {"path": [], "length": -1, "found": False}

        try:
            path = nx.shortest_path(G.to_undirected(), src, tgt)
            return {"path": path, "length": len(path) - 1, "found": True}
        except nx.NetworkXNoPath:
            return {"path": [], "length": -1, "found": False}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/export")
def export_graph(fmt: str = "json", collection_id: Optional[str] = None):
    """Export graph as JSON or GraphML."""
    nodes = get_nodes(collection_id, limit=2000)
    edges = get_edges(collection_id, limit=5000)

    if fmt == "json":
        import json
        payload = json.dumps({"nodes": nodes, "edges": edges}, indent=2)
        return Response(content=payload, media_type="application/json",
                        headers={"Content-Disposition": "attachment; filename=aegis_graph.json"})

    if fmt == "graphml":
        try:
            import networkx as nx
            G = _build_nx_graph(collection_id)
            import io
            buf = io.BytesIO()
            nx.write_graphml(G, buf)
            return Response(content=buf.getvalue(), media_type="application/xml",
                            headers={"Content-Disposition": "attachment; filename=aegis_graph.graphml"})
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    raise HTTPException(status_code=400, detail="fmt must be json or graphml")
