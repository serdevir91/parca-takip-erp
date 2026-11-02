def test_version_and_login(client, admin_headers):
    r = client.get("/api/version")
    assert r.status_code == 200 and r.json()["version"]
    me = client.get("/api/auth/me", headers=admin_headers).json()
    assert me["username"] == "admin" and me["role"] == "admin"
    assert client.get("/api/auth/me").status_code == 401
    bad = client.post("/api/auth/login", data={"username": "admin", "password": "yanlış"})
    assert bad.status_code == 401
