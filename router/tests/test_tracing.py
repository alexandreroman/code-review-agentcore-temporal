import pytest
from agentcore_review_router.tracing import traceparent

ROOT = "1-5759e988-bd862e3fe1be46a994272793"
PARENT = "53995c3f42cd8ad8"
TRACE_ID = "5759e988bd862e3fe1be46a994272793"


def test_sampled_trace_header_becomes_a_sampled_traceparent():
    assert traceparent(f"Root={ROOT};Parent={PARENT};Sampled=1") == f"00-{TRACE_ID}-{PARENT}-01"


@pytest.mark.parametrize("sampled", ["Sampled=0", "Sampled=?", "Sampled=", None])
def test_trace_header_not_sampled_becomes_an_unsampled_traceparent(sampled):
    header = f"Root={ROOT};Parent={PARENT}" + (f";{sampled}" if sampled else "")
    assert traceparent(header) == f"00-{TRACE_ID}-{PARENT}-00"


def test_extra_fields_and_their_order_do_not_matter():
    header = f"Sampled=1;Lineage=a87bd80c:1|68fd508a:5;Parent={PARENT};Root={ROOT}"
    assert traceparent(header) == f"00-{TRACE_ID}-{PARENT}-01"


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        f"Parent={PARENT};Sampled=1",
        f"Root={ROOT};Sampled=1",
        f"Root=2-5759e988-bd862e3fe1be46a994272793;Parent={PARENT};Sampled=1",
        f"Root=1-5759e988-bd862e3fe1be46a99427279;Parent={PARENT};Sampled=1",
        f"Root=1-5759E988-BD862E3FE1BE46A994272793;Parent={PARENT};Sampled=1",
        f"Root={ROOT};Parent=53995c3f42cd8ad;Sampled=1",
        f"Root={ROOT};Parent=53995c3f42cd8adz;Sampled=1",
        "garbage",
    ],
)
def test_missing_or_malformed_trace_header_gives_no_traceparent(header):
    assert traceparent(header) is None
