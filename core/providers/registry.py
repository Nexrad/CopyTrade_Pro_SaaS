"""
core/providers/registry.py
------------------------------
Only Ab Marshall for this launch (product spec section 5) - adding a
second provider later means one new module + one line here, nothing
in the signal engine changes.
"""

from core.providers.marshallfx import AbMarshallProvider

ACTIVE_PROVIDERS = {
    "AbMarshall": AbMarshallProvider(),
}
