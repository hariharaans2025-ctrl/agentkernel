import pytest
from agentkernel.repository.product_campaign import batch_size


def test_remote_batch_respects_operation_deadline_for_long_commands():
    for timeout in (1,2,10,30,120):
        size = batch_size(timeout)
        assert 1 <= size <= 40
        assert size*(timeout+1)+15 <= 170
    with pytest.raises(ValueError): batch_size(0)
