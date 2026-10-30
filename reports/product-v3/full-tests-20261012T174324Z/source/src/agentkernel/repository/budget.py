"""Process-safe paid-inference ledger. Unknown calls retain their full reservation."""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import uuid


def amount(value):
    if isinstance(value, bool):
        raise ValueError('A finite nonnegative USD amount is required')
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError('A finite nonnegative USD amount is required')
    return result


class BudgetLedger:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix('.lock').open('a+b') as stream:
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)

    def _read(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

    def _write(self, data):
        temporary = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
        temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
        temporary.replace(self.path)

    def initialize(self, *, total_usd, opening_reservation_usd=0, authorization):
        cap, opening = amount(total_usd), amount(opening_reservation_usd)
        if opening > cap or not authorization:
            raise ValueError('Explicit authorization and feasible budget required')
        with self.locked():
            if self.path.exists():
                return self._read()
            data = {'schema_version': 1, 'total_usd': float(cap),
                    'opening_reservation_usd': float(opening), 'authorization': authorization,
                    'created_at': datetime.now(timezone.utc).isoformat(), 'calls': []}
            self._write(data)
            return data

    @staticmethod
    def committed(data):
        return amount(data['opening_reservation_usd']) + sum(
            (amount(c['actual_usd']) if c.get('actual_usd') is not None else amount(c['reserved_usd']))
            for c in data['calls'])

    def snapshot(self):
        with self.locked():
            data = self._read()
        data['committed_usd'] = float(self.committed(data))
        data['remaining_usd'] = float(max(Decimal(0), amount(data['total_usd']) - self.committed(data)))
        data['known_new_spend_usd'] = float(sum(amount(c['actual_usd']) for c in data['calls'] if c.get('actual_usd') is not None))
        data['unknown_calls'] = sum(c.get('actual_usd') is None for c in data['calls'])
        return data

    def reserve(self, identifier, *, bound_usd, model, evidence):
        bound = amount(bound_usd)
        with self.locked():
            data = self._read()
            if any(c['id'] == identifier for c in data['calls']):
                raise ValueError('A recorded paid call must never be replayed')
            if self.committed(data) + bound > amount(data['total_usd']):
                raise ValueError('Aggregate paid-inference budget exhausted')
            data['calls'].append({'id': identifier, 'model': model, 'evidence': evidence,
                                  'reserved_usd': float(bound), 'actual_usd': None,
                                  'status': 'reserved', 'created_at': datetime.now(timezone.utc).isoformat()})
            self._write(data)

    def settle(self, identifier, *, actual_usd, input_tokens, output_tokens):
        actual = amount(actual_usd)
        if any(type(v) is not int or v < 0 for v in (input_tokens, output_tokens)):
            raise ValueError('Known token counts required')
        with self.locked():
            data = self._read(); row = next(c for c in data['calls'] if c['id'] == identifier)
            if row.get('actual_usd') is not None:
                raise ValueError('Paid call already settled')
            if actual > amount(row['reserved_usd']):
                row['status'] = 'provider_exceeded_reservation'; self._write(data)
                raise ValueError('Provider charge exceeded its reservation')
            row.update(actual_usd=float(actual), input_tokens=input_tokens, output_tokens=output_tokens, status='received')
            self._write(data)

    def unknown(self, identifier, reason):
        with self.locked():
            data = self._read(); row = next(c for c in data['calls'] if c['id'] == identifier)
            if row.get('actual_usd') is None:
                row.update(status='unknown', reason=reason)
                self._write(data)
