"""Independent budget/measurement primitives; not wired into frozen routing."""
from math import isfinite
from .onboarding import Budgets


class TokenBudget:
    def __init__(self, limits: Budgets):
        self.limits, self.calls, self.spent = limits, 0, 0
        self.pending = None
        self.unknown = False

    def reserve(self, input_tokens: int, output_cap: int):
        if self.pending is not None or self.unknown:
            raise ValueError('Unsettled or unknown usage prevents another call')
        if type(input_tokens) is not int or type(output_cap) is not int or input_tokens < 0 or output_cap < 1:
            raise ValueError('Exact nonnegative input count and positive output cap required')
        if (self.calls >= self.limits.max_model_calls or input_tokens > self.limits.max_input_tokens_per_call
                or output_cap > self.limits.max_output_tokens_per_call
                or self.spent + input_tokens + output_cap > self.limits.max_total_tokens):
            raise ValueError('Model call exceeds budget')
        self.pending = (input_tokens, output_cap)
        self.calls += 1

    def settle(self, input_tokens: int | None, output_tokens: int | None):
        if self.pending is None: raise ValueError('No reserved call')
        if any(v is not None and (type(v) is not int or v < 0) for v in (input_tokens, output_tokens)):
            raise ValueError('Invalid provider usage')
        reserved, self.pending = self.pending, None
        if input_tokens is None or output_tokens is None:
            self.unknown = True
            return
        self.spent += input_tokens + output_tokens
        if input_tokens > reserved[0] or output_tokens > reserved[1]:
            self.unknown = True
            raise ValueError('Provider usage exceeded reservation; stop further calls')


def summarize(records):
    """One record per repository job; unknown measurements propagate as null."""
    def total(name):
        values = [r.get(name) for r in records]
        if any(v is None for v in values): return None
        if any(type(v) not in (int, float) or not isfinite(v) or v < 0 for v in values): raise ValueError('Invalid metric')
        return sum(values)
    verified = sum(r.get('outcome') == 'verified' for r in records)
    tokens = total('tokens')
    calls = total('model_calls')
    return {'jobs': len(records), 'verified': verified,
            'rejected': sum(r.get('outcome') == 'rejected' for r in records),
            'unknown': sum(r.get('outcome') not in {'verified', 'rejected'} for r in records),
            'tokens': tokens, 'model_calls': calls,
            'tokens_per_verified_repair': tokens / verified if tokens is not None and verified else None,
            'inference_ms': total('inference_ms'), 'verification_ms': total('verification_ms'),
            'end_to_end_ms': total('end_to_end_ms'), 'cost_usd': total('cost_usd')}
