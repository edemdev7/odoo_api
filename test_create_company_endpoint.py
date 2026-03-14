#!/usr/bin/env python3
"""Smoke test for the /odoo/companies endpoint logic.

This test does not hit a real Odoo server. Instead, it patches the Odoo client
with a MagicMock to validate that the endpoint builds the expected payload and
returns the correct ApiResponse structure.
"""
import asyncio
from unittest.mock import MagicMock, patch

from api.odoo import create_company
from models.schemas import CompanyCreateRequest


async def run_test():
    request = CompanyCreateRequest(
        name="Test API Company",
        email="contact@example.com",
        phone="+2250700000000",
        street="API Street",
        city="Abidjan",
        country_id=1,
        category_ids=[3, 5],
        payment_term_id=4,
        salesperson_id=12,
        note="Test note",
    )

    fake_client = MagicMock()
    fake_client.execute_kw.side_effect = [
        9999,  # ID retourné par res.partner.create
        [
            {
                "name": "Test API Company",
                "email": "contact@example.com",
                "phone": "+2250700000000",
                "vat": False,
                "website": False,
                "company_registry": False,
                "customer_rank": 1,
                "supplier_rank": 0,
                "category_id": [[3, "Cat A"], [5, "Cat B"]],
            }
        ],
    ]

    test_user = {"username": "admin", "scopes": ["read", "write"], "odoo_db": "jnp_directe"}

    with patch("api.odoo.get_odoo_client", return_value=fake_client):
        response = await create_company(request, current_user=test_user)

    assert response.success is True
    assert response.data["id"] == 9999
    assert response.data["partner"]["name"] == "Test API Company"
    assert fake_client.execute_kw.call_count == 2

    print("✅ create_company endpoint smoke test passed")


if __name__ == "__main__":
    asyncio.run(run_test())
