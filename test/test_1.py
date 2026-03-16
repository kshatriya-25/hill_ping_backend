from fastapi.testclient import TestClient
import pytest
import main
from app.modals.masters import Role

from fastapi import status

client = TestClient(main.app)

# @pytest.fixture
# def camera():
#     role = Role(
#         id = 1,
#         role_name = "admin"
#     )

def test_return_health_check():
    response = client.get("/health")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"message": " HAR HAR MAHADEV"}