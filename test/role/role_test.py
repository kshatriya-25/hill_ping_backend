# OM VIGHNHARTAYE NAMO NAMAH :
from test.centralClient import client

def test_role_crud_flow(client):
    # Step 1: Create role
    create_response = client.post("/role/create", data={"role_name": "Test Admin"})
    assert create_response.status_code == 200
    created_role = create_response.json()
    role_id = created_role["id"]
    assert created_role["role_name"] == "Test Admin"

    # Step 2: Get role by ID
    get_response = client.get(f"/role/get/{role_id}")
    assert get_response.status_code == 200
    role_data = get_response.json()
    assert role_data["role_name"] == "Test Admin"
    assert role_data["id"] == role_id


    # Step 3: Update role
    update_response = client.put(f"/role/{role_id}", data={"role_name": "Updated Admin"})
    assert update_response.status_code == 200
    updated_data = update_response.json()
    assert updated_data["role_name"] == "Updated Admin"

    # Step 4: Get all roles
    all_roles = client.get("/role/all")
    assert all_roles.status_code == 200
    all_data = all_roles.json()
    assert any(r["id"] == role_id for r in all_data)

    # Step 5: Delete role
    delete_response = client.delete(f"/role/{role_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["detail"] == "Role deleted successfully"

    # Step 6: Confirm deletion
    
    confirm_response = client.get(f"/role/get/{role_id}")
    assert confirm_response.status_code == 404
    assert confirm_response.json()["detail"] == "Role not found"