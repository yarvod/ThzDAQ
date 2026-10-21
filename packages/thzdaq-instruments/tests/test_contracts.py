import pytest
from contracts import CONTRACTS, contract_cases
from thzdaq_instruments.capabilities import ALL_CAPABILITIES

CASES = list(contract_cases())


@pytest.mark.parametrize(
    "capability, check, factory",
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_implementation_satisfies_contract(capability, check, factory):
    device = factory()
    assert isinstance(device, capability)
    check(device)


def test_every_capability_has_a_contract():
    assert set(CONTRACTS) == set(ALL_CAPABILITIES)
