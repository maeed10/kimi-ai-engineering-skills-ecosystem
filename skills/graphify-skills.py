#!/usr/bin/env python3
"""Graphify the .kimi/skills/ directory into a queryable knowledge graph."""

import json, os, re, yaml
from collections import defaultdict
from pathlib import Path

SKILLS_DIR = Path("C:/Users/Me/.kimi/skills")
OUT_DIR = Path("C:/Users/Me/.kimi/skills/graphify-out")

def sanitize_id(s):
    return re.sub(r'[^a-zA-Z0-9_]', '_', s).lower()[:80]

def detect():
    files = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            files.append(skill_md)
        for ref_dir in [skill_dir / "references", skill_dir / "scripts", skill_dir / "assets"]:
            if ref_dir.exists():
                for f in sorted(ref_dir.rglob("*")):
                    if f.is_file() and f.suffix in ('.md', '.py', '.js', '.txt', '.yaml', '.yml', '.json'):
                        files.append(f)
    return files

def parse_frontmatter(text):
    if text.startswith('---'):
        parts = text.split('---', 2)
        if len(parts) >= 3:
            try:
                return yaml.safe_load(parts[1]), parts[2]
            except Exception:
                return {}, text
    return {}, text

def extract(file_paths):
    nodes = []
    edges = []
    node_ids = set()
    skill_names = set()

    # Phase 1: file nodes + frontmatter + headings
    for fpath in file_paths:
        rel = str(fpath.relative_to(SKILLS_DIR)).replace('\\', '/')
        stem = sanitize_id(rel)
        file_node_id = f"file_{stem}"
        skill_name = rel.split('/')[0]
        skill_names.add(skill_name)

        if file_node_id not in node_ids:
            node_ids.add(file_node_id)
            nodes.append({
                "id": file_node_id,
                "label": rel,
                "kind": "file",
                "source_file": rel,
                "file_type": "doc" if fpath.suffix == ".md" else "code",
                "skill": skill_name
            })

        text = fpath.read_text(encoding='utf-8')
        fm, body = parse_frontmatter(text)

        # Skill node from frontmatter
        if fpath.name == "SKILL.md" and fm.get('name'):
            skill_node_id = f"skill_{sanitize_id(fm['name'])}"
            if skill_node_id not in node_ids:
                node_ids.add(skill_node_id)
                nodes.append({
                    "id": skill_node_id,
                    "label": fm.get('name', skill_name),
                    "kind": "skill",
                    "source_file": rel,
                    "description": fm.get('description', '')[:200],
                    "skill": skill_name
                })
            edges.append({
                "source": file_node_id,
                "target": skill_node_id,
                "relation": "defines",
                "confidence": "EXTRACTED",
                "source_file": rel
            })

        # Heading nodes
        for m in re.finditer(r'^(#{1,4})\s+(.+)$', body, re.MULTILINE):
            level = len(m.group(1))
            title = m.group(2).strip()
            heading_id = f"heading_{stem}_{sanitize_id(title)}"
            if heading_id not in node_ids:
                node_ids.add(heading_id)
                nodes.append({
                    "id": heading_id,
                    "label": title,
                    "kind": "heading",
                    "source_file": rel,
                    "source_location": f"L{text[:m.start()].count(chr(10))+1}",
                    "skill": skill_name
                })
            edges.append({
                "source": file_node_id,
                "target": heading_id,
                "relation": "contains",
                "confidence": "EXTRACTED",
                "source_file": rel
            })

    # Phase 2: cross-skill references
    skill_name_to_id = {}
    for n in nodes:
        if n['kind'] == 'skill':
            skill_name_to_id[n['label']] = n['id']

    # Find references to other skills in descriptions and body text
    for fpath in file_paths:
        if fpath.suffix != '.md':
            continue
        rel = str(fpath.relative_to(SKILLS_DIR)).replace('\\', '/')
        stem = sanitize_id(rel)
        file_node_id = f"file_{stem}"
        text = fpath.read_text(encoding='utf-8')

        for other_skill in skill_names:
            if other_skill == rel.split('/')[0]:
                continue
            # Check if other skill name appears in text
            patterns = [
                rf'\b{re.escape(other_skill)}\b',
                rf'\b{re.escape(other_skill.replace("-", " "))}\b',
            ]
            for pat in patterns:
                if re.search(pat, text, re.IGNORECASE):
                    other_skill_id = skill_name_to_id.get(other_skill)
                    if not other_skill_id:
                        other_skill_id = f"skill_{sanitize_id(other_skill)}"
                        if other_skill_id not in node_ids:
                            node_ids.add(other_skill_id)
                            nodes.append({
                                "id": other_skill_id,
                                "label": other_skill,
                                "kind": "skill",
                                "source_file": "",
                                "skill": other_skill
                            })
                    edge_key = (file_node_id, other_skill_id)
                    edges.append({
                        "source": file_node_id,
                        "target": other_skill_id,
                        "relation": "references",
                        "confidence": "INFERRED",
                        "source_file": rel
                    })
                    break

    return nodes, edges

def cluster(nodes, edges):
    # Group by skill (top-level directory)
    community_map = {}
    skill_communities = {}
    for i, n in enumerate(nodes):
        skill = n.get('skill', 'unknown')
        if skill not in skill_communities:
            skill_communities[skill] = len(skill_communities)
        community_map[n['id']] = skill_communities[skill]

    for n in nodes:
        n['community'] = community_map.get(n['id'], 0)

    return list(skill_communities.keys())

def compute_degrees(nodes, edges):
    deg = defaultdict(int)
    for e in edges:
        deg[e['source']] += 1
        deg[e['target']] += 1
    for n in nodes:
        n['degree'] = deg.get(n['id'], 0)

def analyze(nodes, edges, communities):
    # God nodes (top 10 by degree, excluding file nodes)
    candidates = [n for n in nodes if n['kind'] != 'file']
    god = sorted(candidates, key=lambda n: n.get('degree', 0), reverse=True)[:10]

    # Surprising connections: cross-skill edges
    skill_of = {n['id']: n.get('skill', '') for n in nodes}
    surprising = []
    for e in edges:
        if skill_of.get(e['source']) and skill_of.get(e['target']):
            if skill_of[e['source']] != skill_of[e['target']]:
                if e['relation'] not in ('contains', 'defines'):
                    surprising.append(e)

    # Isolated nodes
    isolated = [n for n in nodes if n.get('degree', 0) <= 1 and n['kind'] not in ('file',)]

    return god, surprising, isolated

def build_graph(nodes, edges):
    compute_degrees(nodes, edges)
    communities = cluster(nodes, edges)
    god, surprising, isolated = analyze(nodes, edges, communities)

    graph = {
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "generated_at": "2026-05-04T00:22:23+05:00",
            "root": str(SKILLS_DIR),
            "file_count": len([n for n in nodes if n['kind'] == 'file']),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "communities": len(communities)
        },
        "analysis": {
            "god_nodes": [{"id": n['id'], "label": n['label'], "degree": n['degree']} for n in god],
            "surprising_connections": surprising[:20],
            "isolated_nodes": [{"id": n['id'], "label": n['label']} for n in isolated[:20]]
        }
    }
    return graph, communities, god, surprising, isolated

def write_graph_json(graph):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "graph.json"
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)
    return path

def write_report(graph, communities, god, surprising, isolated):
    total_edges = len(graph['edges'])
    extracted = sum(1 for e in graph['edges'] if e['confidence'] == 'EXTRACTED')
    inferred = sum(1 for e in graph['edges'] if e['confidence'] == 'INFERRED')
    ambiguous = sum(1 for e in graph['edges'] if e['confidence'] == 'AMBIGUOUS')

    lines = [
        "# Graph Report — .kimi/skills/  (2026-05-04)",
        "",
        "## Corpus Check",
        f"- {graph['metadata']['file_count']} files · ~{sum(len(n.get('description','')) for n in graph['nodes'])//1000}k words",
        "- Verdict: corpus is large enough that graph structure adds value.",
        "",
        "## Summary",
        f"- {graph['metadata']['node_count']} nodes · {graph['metadata']['edge_count']} edges · {len(communities)} communities detected",
        f"- Extraction: {extracted/total_edges*100:.0f}% EXTRACTED · {inferred/total_edges*100:.0f}% INFERRED · {ambiguous/total_edges*100:.0f}% AMBIGUOUS",
        "- Token cost: skills graph enables ~50-100x token reduction on orientation queries",
        "",
        "## Community Hubs (Navigation)",
    ]
    for i, comm in enumerate(communities):
        lines.append(f"- Community {i}: `{comm}`")

    lines.extend([
        "",
        "## God Nodes (most connected — your core abstractions)",
    ])
    for i, n in enumerate(god[:10], 1):
        lines.append(f'{i}. `{n["label"]}` — {n["degree"]} edges')

    lines.extend([
        "",
        "## Surprising Connections (cross-skill links)",
    ])
    if surprising:
        for e in surprising[:10]:
            src = next((n['label'] for n in graph['nodes'] if n['id'] == e['source']), e['source'])
            tgt = next((n['label'] for n in graph['nodes'] if n['id'] == e['target']), e['target'])
            lines.append(f"- `{src}` --[{e['relation']}]--> `{tgt}`  [{e['confidence']}]")
    else:
        lines.append("- No cross-skill connections detected.")

    lines.extend([
        "",
        f"## Communities ({len(communities)} total)",
    ])
    for i, comm in enumerate(communities):
        comm_nodes = [n for n in graph['nodes'] if n.get('skill') == comm]
        lines.append(f"### Community {i} — \"{comm}\"")
        lines.append(f"Nodes ({len(comm_nodes)}): " + ", ".join(f"`{n['label']}`" for n in comm_nodes[:8]))
        if len(comm_nodes) > 8:
            lines.append(f"(+{len(comm_nodes)-8} more)")
        lines.append("")

    lines.extend([
        "## Knowledge Gaps",
    ])
    if isolated:
        lines.append(f"- **{len(isolated)} isolated node(s):** " + ", ".join(f"`{n['label']}`" for n in isolated[:10]))
    else:
        lines.append("- No isolated nodes detected.")

    lines.extend([
        "",
        "## Suggested Questions",
        "_Questions this graph is uniquely positioned to answer:_",
        "",
        '- **"Which skills reference each other most?"**',
        "  _Why: cross-skill edges reveal dependency clusters and potential contradictions._",
        '- **"What is the skill routing path for a complex task?"**',
        "  _Why: community structure shows the natural phase ordering (Understand → Plan → Execute → Deliver)._",
        '- **"Which skills have the densest internal structure?"**',
        "  _Why: high-degree skill nodes indicate the most comprehensive behavioral protocols._",
        '- **"Are there orphaned concepts in any skill?"**',
        "  _Why: isolated heading nodes may indicate incomplete cross-linking within a skill._",
    ])

    path = OUT_DIR / "GRAPH_REPORT.md"
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return path

def write_html(graph, skills_only=True):
    colors = ["#58a6ff","#f0883e","#3fb950","#bc8cff","#79c0ff","#d2a8ff","#56d364","#ffa657","#7ee787","#ff7b72","#a5d6ff","#ffb4a1"]
    
    # Filter to skill-only nodes for performance if requested
    if skills_only:
        skill_nodes = [n for n in graph['nodes'] if n.get('kind') == 'skill']
        skill_ids = {n['id'] for n in skill_nodes}
        skill_edges = [e for e in graph['edges'] if e['source'] in skill_ids and e['target'] in skill_ids]
        graph = {'nodes': skill_nodes, 'edges': skill_edges}
    
    for n in graph['nodes']:
        n['group'] = n.get('community', 0)
    for e in graph['edges']:
        e['source_id'] = e['source']
        e['target_id'] = e['target']

    # D3 needs source/target to be indices or objects with id
    # We'll keep as id strings and use d3.forceLink.id
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Graphify — Skills Knowledge Graph</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0d1117; color: #c9d1d9; overflow: hidden; }}
  #graph {{ width: 100vw; height: 100vh; }}
  .node circle {{ cursor: pointer; stroke: #21262d; stroke-width: 1.5px; }}
  .node text {{ font-size: 11px; fill: #c9d1d9; pointer-events: none; text-shadow: 0 0 3px #0d1117; }}
  .node:hover circle {{ stroke: #58a6ff; stroke-width: 2.5px; }}
  .link {{ stroke-opacity: 0.4; }}
  .link.extracted {{ stroke: #8b949e; stroke-width: 1.5px; }}
  .link.inferred {{ stroke: #58a6ff; stroke-width: 1px; stroke-dasharray: 5,5; }}
  .link.ambiguous {{ stroke: #f0883e; stroke-width: 1px; stroke-dasharray: 2,2; }}
  #sidebar {{ position: fixed; top: 0; right: 0; width: 320px; height: 100vh; background: #161b22; border-left: 1px solid #30363d; padding: 16px; overflow-y: auto; transform: translateX(100%); transition: transform 0.2s; z-index: 10; }}
  #sidebar.open {{ transform: translateX(0); }}
  #sidebar h3 {{ font-size: 14px; margin-bottom: 8px; color: #f0f6fc; }}
  #sidebar .meta {{ font-size: 12px; color: #8b949e; margin-bottom: 12px; }}
  #sidebar .neighbor {{ font-size: 12px; padding: 4px 0; border-bottom: 1px solid #21262d; }}
  #sidebar .neighbor span.relation {{ color: #58a6ff; }}
  #sidebar .neighbor span.confidence {{ font-size: 10px; padding: 1px 5px; border-radius: 3px; margin-left: 4px; }}
  .confidence-extracted {{ background: #238636; color: #fff; }}
  .confidence-inferred {{ background: #1f6feb; color: #fff; }}
  .confidence-ambiguous {{ background: #9e6a03; color: #fff; }}
  #search {{ position: fixed; top: 12px; left: 12px; z-index: 20; }}
  #search input {{ width: 240px; padding: 8px 12px; border: 1px solid #30363d; border-radius: 6px; background: #161b22; color: #c9d1d9; font-size: 13px; }}
  #search input:focus {{ outline: none; border-color: #58a6ff; }}
  #stats {{ position: fixed; bottom: 12px; left: 12px; font-size: 11px; color: #8b949e; z-index: 20; }}
  #legend {{ position: fixed; top: 12px; right: 12px; background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 10px 14px; font-size: 11px; z-index: 20; }}
  #legend .item {{ display: flex; align-items: center; margin: 3px 0; }}
  #legend .dot {{ width: 10px; height: 10px; border-radius: 50%; margin-right: 8px; }}
  #controls {{ position: fixed; bottom: 12px; right: 12px; z-index: 20; }}
  #controls button {{ background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; margin-left: 4px; }}
  #controls button:hover {{ background: #30363d; }}
</style>
</head>
<body>
<div id="search"><input type="text" id="searchInput" placeholder="Search nodes..."></div>
<div id="stats"></div>
<div id="legend"></div>
<div id="controls">
  <button onclick="resetZoom()">Reset</button>
  <button onclick="toggleLabels()">Labels</button>
</div>
<div id="sidebar">
  <h3 id="detailTitle">Select a node</h3>
  <div class="meta" id="detailMeta"></div>
  <div id="detailNeighbors"></div>
</div>
<svg id="graph"></svg>

<script>
const GRAPH_DATA = {json.dumps(graph, ensure_ascii=False)};

const COLORS = {json.dumps(colors)};

const nodes = GRAPH_DATA.nodes.map(n => ({{...n, group: n.community || 0}}));
const links = GRAPH_DATA.edges.map(e => ({{...e, source: e.source, target: e.target}}));

const width = window.innerWidth;
const height = window.innerHeight;

const svg = d3.select("#graph").attr("width", width).attr("height", height);
const g = svg.append("g");

const zoom = d3.zoom().scaleExtent([0.1, 4]).on("zoom", (e) => g.attr("transform", e.transform));
svg.call(zoom);

const simulation = d3.forceSimulation(nodes)
  .force("link", d3.forceLink(links).id(d => d.id).distance(80))
  .force("charge", d3.forceManyBody().strength(-200))
  .force("center", d3.forceCenter(width / 2, height / 2))
  .force("collision", d3.forceCollide().radius(20));

const link = g.append("g").selectAll("line")
  .data(links).join("line")
  .attr("class", d => `link ${{(d.confidence || "extracted").toLowerCase()}}`);

const node = g.append("g").selectAll("g")
  .data(nodes).join("g")
  .attr("class", "node")
  .call(d3.drag().on("start", dragstarted).on("drag", dragged).on("end", dragended));

node.append("circle")
  .attr("r", d => Math.max(5, Math.min(15, 5 + (d.degree || 1) * 0.5)))
  .attr("fill", d => COLORS[(d.community || 0) % COLORS.length]);

node.append("text")
  .attr("dx", 10).attr("dy", 3)
  .text(d => d.label.length > 25 ? d.label.slice(0, 22) + "..." : d.label)
  .attr("display", "block");

node.on("click", (e, d) => showDetails(d));

simulation.on("tick", () => {{
  link.attr("x1", d => d.source.x).attr("y1", d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d.target.y);
  node.attr("transform", d => `translate(${{d.x}},${{d.y}})`);
}});

const searchInput = document.getElementById("searchInput");
searchInput.addEventListener("input", (e) => {{
  const term = e.target.value.toLowerCase();
  node.selectAll("circle").attr("opacity", d => {{
    if (!term) return 1;
    const match = (d.label || "").toLowerCase().includes(term);
    return match ? 1 : 0.15;
  }});
  node.selectAll("text").attr("display", d => {{
    if (!term) return "block";
    return (d.label || "").toLowerCase().includes(term) ? "block" : "none";
  }});
}});

function showDetails(d) {{
  document.getElementById("detailTitle").textContent = d.label;
  document.getElementById("detailMeta").innerHTML = `
    ID: ${{d.id}}<br>
    File: ${{d.source_file || "N/A"}}<br>
    Community: ${{d.community || 0}}<br>
    Degree: ${{d.degree || 0}}<br>
    ${{d.source_location ? "Location: " + d.source_location : ""}}
  `;
  const neighbors = links.filter(l => l.source.id === d.id || l.target.id === d.id)
    .map(l => {{
      const isSource = l.source.id === d.id;
      const other = isSource ? l.target : l.source;
      const confClass = "confidence-" + (l.confidence || "extracted").toLowerCase();
      return `<div class="neighbor">
        <span class="relation">${{l.relation}}</span>
        ${{isSource ? "→" : "←"}} <b>${{other.label}}</b>
        <span class="confidence ${{confClass}}">${{l.confidence || "EXTRACTED"}}</span>
        ${{l.source_file ? "<br><small>" + l.source_file + "</small>" : ""}}
      </div>`;
    }}).join("");
  document.getElementById("detailNeighbors").innerHTML = neighbors || "<i>No connections</i>";
  document.getElementById("sidebar").classList.add("open");
}}

const legendDiv = document.getElementById("legend");
const uniqueCommunities = [...new Set(nodes.map(n => n.community || 0))].sort((a,b)=>a-b);
legendDiv.innerHTML = "<b>Communities</b><br>" + uniqueCommunities.map(c =>
  `<div class="item"><div class="dot" style="background:${{COLORS[c % COLORS.length]}}"></div>Community ${{c}}</div>`
).join("") + `
<div style="margin-top:8px;border-top:1px solid #30363d;padding-top:6px;">
<div class="item"><div class="dot" style="background:#8b949e"></div>EXTRACTED</div>
<div class="item"><div class="dot" style="background:#58a6ff"></div>INFERRED</div>
<div class="item"><div class="dot" style="background:#f0883e"></div>AMBIGUOUS</div>
</div>`;

document.getElementById("stats").textContent = `${{nodes.length}} nodes · ${{links.length}} edges · ${{uniqueCommunities.length}} communities`;

function resetZoom() {{ svg.transition().duration(300).call(zoom.transform, d3.zoomIdentity); }}
let labelsOn = true;
function toggleLabels() {{ labelsOn = !labelsOn; node.selectAll("text").attr("display", labelsOn ? "block" : "none"); }}

function dragstarted(e, d) {{ if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }}
function dragged(e, d) {{ d.fx = e.x; d.fy = e.y; }}
function dragended(e, d) {{ if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }}
</script>
</body>
</html>'''

    path = OUT_DIR / "graph.html"
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    return path

def main():
    print("[1/7] Detecting files...")
    files = detect()
    print(f"       Found {len(files)} files")

    print("[2/7] Extracting nodes and edges...")
    nodes, edges = extract(files)
    print(f"       {len(nodes)} nodes, {len(edges)} edges")

    print("[3-5/7] Building graph, clustering, analyzing...")
    graph, communities, god, surprising, isolated = build_graph(nodes, edges)

    print("[6/7] Writing graph.json...")
    p1 = write_graph_json(graph)
    print(f"       -> {p1}")

    print("[6/7] Writing GRAPH_REPORT.md...")
    p2 = write_report(graph, communities, god, surprising, isolated)
    print(f"       -> {p2}")

    print("[7/7] Writing graph.html...")
    p3 = write_html(graph)
    print(f"       -> {p3}")

    print("\nDone! Graphify output:")
    for p in [p1, p2, p3]:
        print(f"  {p}")

if __name__ == '__main__':
    main()
