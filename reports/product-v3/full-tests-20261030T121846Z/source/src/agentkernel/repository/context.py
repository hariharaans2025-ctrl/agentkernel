"""Conservative whole-file retrieval and non-truncating evidence grouping."""
import hashlib
import json
import re


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def index_functions(ast, filename, source):
    """Filter a Clang translation-unit AST to definitions in the main source file."""
    data = source.encode('utf-8')
    found = []
    def walk(node):
        if not isinstance(node, dict): return
        children = node.get('inner', [])
        loc = node.get('loc', {})
        if (node.get('kind') == 'FunctionDecl' and any(c.get('kind') == 'CompoundStmt' for c in children)
                and 'includedFrom' not in loc and loc.get('file', filename) == filename):
            start, end = node.get('range', {}).get('begin', {}), node.get('range', {}).get('end', {})
            if 'offset' not in start or 'offset' not in end:
                raise ValueError('Unsupported macro function range; keep full context')
            begin, finish = start['offset'], end['offset'] + end.get('tokLen', 1)
            if not 0 <= begin < finish <= len(data): raise ValueError('Invalid source offsets')
            refs, members = set(), set()
            def refs_walk(n):
                decl = n.get('referencedDecl', {})
                if decl.get('kind') == 'FunctionDecl': refs.add(decl['name'])
                if n.get('kind') == 'MemberExpr': members.add(n.get('name', ''))
                for c in n.get('inner', []): refs_walk(c)
            refs_walk(node)
            found.append({'name': node['name'], 'file': filename,
                          'start_line': data[:begin].count(b'\n') + 1,
                          'end_line': data[:finish].count(b'\n') + 1,
                          'references': sorted(refs), 'members': sorted(members),
                          'definition_sha256': hashlib.sha256(data[begin:finish]).hexdigest()})
        for child in children: walk(child)
    walk(ast)
    return found


def select_sources(sources, index, seed_functions, editable):
    names = {entry['name'] for entry in index}
    if not seed_functions or not set(seed_functions) <= names:
        raise ValueError('Unresolved diagnostic seed; request full context instead')
    # Include callers, callees and function-pointer references to a fixed point.
    selected = set(seed_functions)
    while True:
        next_names = set(selected)
        for entry in index:
            if entry['name'] in selected or selected.intersection(entry['references']):
                next_names.add(entry['name'])
                next_names.update(set(entry['references']) & names)
        if next_names == selected: break
        selected = next_names
    files = set(editable) | {e['file'] for e in index if e['name'] in selected}
    # Retain all listed project headers: avoid assuming declarations/macros are irrelevant.
    files |= {name for name in sources if name.endswith(('.h', '.hpp'))}
    if not files <= sources.keys(): raise ValueError('Selected source missing')
    # Missing quoted includes could hide lock/type definitions; do not silently omit them.
    for name in files:
        for header in re.findall(r'^\s*#\s*include\s*"([^"]+)"', sources[name], re.MULTILINE):
            if not any(f == header or f.endswith('/' + header) for f in files):
                raise ValueError('Unresolved project include; expand context')
    return {name: sources[name] for name in sorted(files)}, sorted(selected)


def group_runs(runs):
    """Group only identical observable outcomes; preserve every run's metadata."""
    groups = {}
    for run in runs:
        key = canonical({k: run.get(k) for k in ('classification', 'exit_code', 'timed_out', 'stdout', 'stderr')})
        if key not in groups: groups[key] = {'outcome': json.loads(key), 'runs': []}
        groups[key]['runs'].append({k: v for k, v in run.items() if k not in groups[key]['outcome']})
    return list(groups.values())


def expand_runs(groups):
    return [{**member, **group['outcome']} for group in groups for member in group['runs']]


def group_diagnostics(diagnostics):
    groups = {}
    for i, diagnostic in enumerate(diagnostics):
        key = canonical(diagnostic)
        if key not in groups: groups[key] = {'diagnostic': diagnostic, 'run_indices': []}
        groups[key]['run_indices'].append(i)
    return list(groups.values())


def prepare_context(sources, index, seeds, editable, campaign, diagnostics, stacks, contract):
    selected, functions = select_sources(sources, index, seeds, editable)
    common = {'original_task': contract['description'], 'editable_files': editable,
              'build_command': contract['build_command'], 'run_command': contract['run_command'],
              'verification_requirements': contract['verification'],
              'counts': campaign['counts'], 'requested_runs': campaign['requested_runs']}
    full = {**common, 'sources': sources, 'runs': campaign['runs'], 'diagnostics': diagnostics, 'thread_stacks': stacks}
    compact = {**common, 'sources': selected, 'run_groups': group_runs(campaign['runs']),
               'diagnostic_groups': group_diagnostics(diagnostics), 'thread_stacks': stacks,
               'context_format': 'Groups preserve each member; sources outside editable_files are read-only.'}
    if sorted(expand_runs(compact['run_groups']), key=lambda r: r['run_id']) != sorted(campaign['runs'], key=lambda r: r['run_id']):
        raise ValueError('Run evidence changed during grouping')
    expanded = [None] * len(diagnostics)
    for group in compact['diagnostic_groups']:
        for i in group['run_indices']: expanded[i] = group['diagnostic']
    if expanded != diagnostics: raise ValueError('Diagnostic evidence changed')
    for name in selected:
        if selected[name] != sources[name]: raise ValueError('Source changed')
    audit = {'selected_files': sorted(selected), 'omitted_files': sorted(set(sources) - set(selected)),
             'seed_functions': seeds, 'reachable_functions': functions,
             'runs_lossless': True, 'diagnostics_lossless': True, 'stacks_unchanged': compact['thread_stacks'] == full['thread_stacks'],
             'source_blocks_unchanged': True,
             'limitations': ['Whole-file conservative retrieval; no general C++ dependency proof.',
                            'Unresolved seeds/includes stop preparation rather than truncate.',
                            'No repair inference or repair-quality comparison performed.']}
    return full, compact, audit
