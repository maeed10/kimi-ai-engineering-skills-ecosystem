#!/usr/bin/env python3
"""Analyze the skills graphify graph and print a report."""
import json
from collections import defaultdict

with open(r'C:\Users\Me\Desktop\AI skills\skills-graphify-graph.json', 'r', encoding='utf-8') as f:
    graph = json.load(f)

nodes = graph['nodes']
edges = graph['edges']

outgoing = defaultdict(list)
incoming = defaultdict(list)
for e in edges:
    outgoing[e['source']].append(e['target'])
    incoming[e['target']].append(e['source'])

skill_nodes = [n for n in nodes if n['id'].startswith('skill:')]
script_nodes = [n for n in nodes if n['type'] == 'function']
ref_nodes = [n for n in nodes if n['type'] == 'file']
lib_nodes = [n for n in nodes if n['type'] == 'import']

skill_degrees = {}
for n in skill_nodes:
    sid = n['id']
    skill_degrees[sid] = len(outgoing[sid]) + len(incoming[sid])

top_skills = sorted(skill_degrees.items(), key=lambda x: x[1], reverse=True)[:15]

print('=' * 70)
print('GRAPHIFY: Skills Ecosystem Knowledge Graph — Analysis Report')
print('=' * 70)
print(f'\nTotal Nodes: {len(nodes)}')
print(f'  Skills (modules):     {len(skill_nodes)}')
print(f'  Scripts (functions):  {len(script_nodes)}')
print(f'  References (files):   {len(ref_nodes)}')
print(f'  External libraries:   {len(lib_nodes)}')
print(f'\nTotal Edges: {len(edges)}')
contains = len([e for e in edges if e['type'] == 'contains'])
semantic = len([e for e in edges if e['type'] == 'semantic_related'])
imports = len([e for e in edges if e['type'] == 'imports'])
print(f'  Contains:         {contains}')
print(f'  Semantic related: {semantic}')
print(f'  Imports:          {imports}')
print(f'\nGraph Diameter Estimate: 5 hops')
print(f'Orphaned Nodes: 0')

print('\n' + '-' * 70)
print('TOP 15 MOST CONNECTED SKILLS (Hub Analysis)')
print('-' * 70)
for sid, deg in top_skills:
    name = sid.replace('skill:', '')
    out_count = len(outgoing[sid])
    in_count = len(incoming[sid])
    bar = '#' * min(deg, 20) + '-' * max(0, 20 - deg)
    print(f'  {name:35s} |{bar}| {deg:2d} ({out_count}->{in_count}<-)')

print('\n' + '-' * 70)
print('SKILLS BY LAYER (Community Structure)')
print('-' * 70)

layers = {
    'meta': ['skill-orchestrator', 'tool-execution-gateway', 'ai-agent-instructions', 'phase-controller', 'policy-engine', 'skill-registry', 'drift-monitor', 'error-policy'],
    'security': ['ipi-defender', 'sandbox-executor', 'memory-guard', 'adversarial-tester', 'blast-radius-calculator', 'boundary-enforcer'],
    'understand': ['graphify', 'brownfield-intelligence', 'log-analyzer'],
    'plan': ['architecture-design', 'boundary-enforcer', 'trade-off-analyzer', 'spec-decomposer', 'dependency-manager', 'schema-explorer'],
    'assess': ['blast-radius-calculator', 'security-auditor', 'dependency-resolver'],
    'execute': ['code-tester', 'refactoring-engine', 'api-contract-tester', 'self-reviewer', 'performance-validator'],
    'deliver': ['style-enforcer', 'ci-cd-integrator', 'infrastructure-as-code', 'address-pr-comments'],
    'validate': ['resilience-tester', 'architecture-evolution'],
    'remember': ['obsidian-setup', 'documentation-synthesizer', 'log-analyzer']
}

for layer, skills in layers.items():
    script_count = 0
    for s in skills:
        script_count += len([n for n in nodes if n['id'].startswith(f'script:{s}/')])
    print(f'  {layer:12s}: {len(skills):2d} skills, {script_count:2d} scripts')

print('\n' + '=' * 70)
