"""Advisory, intraprocedural Clang-AST barrier/lock evidence.

This is deliberately not an alias analysis or a deadlock/safety proof. Findings
describe possible paths; actual concurrency and object identity need runtime evidence.
"""
import hashlib
import json


def analyze_barriers(ast, filename, source):
    data = source.encode('utf-8')
    findings, gaps, waits, acquisitions = [], [], [], []

    def location(node):
        begin = node.get('range', {}).get('begin', {})
        end = node.get('range', {}).get('end', {})
        if 'offset' not in begin or 'offset' not in end:
            raise ValueError('Macro or unavailable source location')
        lo, hi = begin['offset'], end['offset'] + end.get('tokLen', 1)
        if not 0 <= lo < hi <= len(data):
            raise ValueError('Invalid AST source range')
        return {'file':filename, 'line':data[:lo].count(b'\n') + 1,
                'text':data[lo:hi].decode('utf-8')}

    def walk(node):
        yield node
        for child in node.get('inner', []):
            yield from walk(child)

    def callee(node):
        children = node.get('inner', [])
        if not children: return None
        refs = [n.get('referencedDecl', {}) for n in walk(children[0])]
        return next((r.get('name') for r in refs if r.get('kind') == 'FunctionDecl'), None)

    def resource(node):
        # Direct address-of named object/member only; never pretend to resolve aliases.
        if node.get('kind') != 'UnaryOperator' or node.get('opcode') != '&':
            raise ValueError('Indirect synchronization object')
        arg = node['inner'][0]
        if arg.get('kind') not in ('MemberExpr', 'DeclRefExpr'):
            raise ValueError('Unsupported synchronization object expression')
        return ''.join(location(arg)['text'].split())

    def visit(node, states, function):
        kind, children = node.get('kind'), node.get('inner', [])
        if kind == 'CompoundStmt':
            for child in children:
                states = visit(child, states, function)
            return states
        if kind == 'IfStmt' and len(children) in (2, 3):
            # Branches stay separate. Conditions are not solved or correlated.
            if any(n.get('kind') == 'CallExpr' for n in walk(children[0])):
                gaps.append({'function':function,'reason':'Call in branch condition not modeled'})
            branches = visit(children[1], [dict(s) for s in states], function)
            branches += visit(children[2], [dict(s) for s in states], function) if len(children) == 3 else states
            unique = {json.dumps(s, sort_keys=True):s for s in branches}
            if len(unique) > 64:
                raise ValueError('Path limit exceeded; use full source and runtime evidence')
            return list(unique.values())
        if kind == 'ReturnStmt':
            return []
        if kind == 'CallExpr':
            name = callee(node)
            if name in ('pthread_mutex_lock', 'pthread_mutex_unlock', 'pthread_barrier_wait'):
                try:
                    site = {'function':function, **location(node)}
                    obj = resource(children[1])
                except (ValueError, IndexError) as exc:
                    gaps.append({'function':function, 'reason':str(exc)})
                    return states
                if name == 'pthread_mutex_lock':
                    acquisitions.append({'object':obj, **site})
                    return [{**state, obj:site} for state in states]
                if name == 'pthread_mutex_unlock':
                    return [{k:v for k,v in state.items() if k != obj} for state in states]
                waits.append({'barrier':obj, **site})
                for state in states:
                    for mutex, acquired in state.items():
                        findings.append({'kind':'possible_barrier_wait_while_holding_mutex',
                            'barrier':obj, 'mutex':mutex, 'wait':site, 'acquisition':acquired})
            elif name not in ('fprintf', 'printf', 'puts', 'memset', 'pthread_mutex_init',
                              'pthread_mutex_destroy', 'pthread_barrier_init', 'pthread_barrier_destroy'):
                gaps.append({'function':function,'reason':'Unmodeled call: ' + str(name)})
            return states
        if kind in ('ForStmt', 'WhileStmt', 'DoStmt', 'SwitchStmt', 'GotoStmt', 'LabelStmt'):
            gaps.append({'function':function,'reason':'Unsupported control flow: ' + kind})
            return states
        if any(n.get('kind') == 'CallExpr' for n in walk(node)):
            gaps.append({'function':function,'reason':'Nested call not modeled: ' + str(kind)})
        return states

    for node in ast.get('inner', []):
        loc = node.get('loc', {})
        bodies = [n for n in node.get('inner', []) if n.get('kind') == 'CompoundStmt']
        if (node.get('kind') == 'FunctionDecl' and bodies and 'includedFrom' not in loc
                and loc.get('file', filename) == filename):
            visit(bodies[0], [{}], node['name'])
    unique = {}
    for finding in findings:
        other_functions = {w['function'] for w in waits
                           if w['barrier'] == finding['barrier'] and w['function'] != finding['wait']['function']}
        finding['possible_other_participant_acquisitions'] = [a for a in acquisitions
            if a['function'] in other_functions and a['object'] == finding['mutex']]
        key = json.dumps(finding, sort_keys=True)
        finding['fingerprint'] = hashlib.sha256(key.encode()).hexdigest()
        unique[key] = finding
    return {'schema_version':1, 'source_sha256':hashlib.sha256(data).hexdigest(),
            'findings':list(unique.values()), 'coverage_gaps':gaps,
            'interpretation':'Advisory possible paths, not proof of deadlock or safety. Matching expressions across functions require the same runtime object and concurrent barrier participants.',
            'limitations':['Direct pthread calls only; no interprocedural or pointer-alias analysis.',
                'Assumes successful mutex lock/unlock; branch feasibility and barrier counts are not solved.',
                'Unsupported control flow and nested/indirect calls are reported as coverage gaps.',
                'No findings does not mean safe. Runtime verification remains required.']}
