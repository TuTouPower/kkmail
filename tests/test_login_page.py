import web_outlook_app as appmod


def test_login_page_renders():
    client = appmod.app.test_client()
    response = client.get("/login")
    assert response.status_code == 200
    assert b"login" in response.data.lower() or b"password" in response.data.lower()
