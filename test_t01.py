import os
import pathlib
import tempfile
import unittest

TEMP_DIR = tempfile.TemporaryDirectory(prefix="fangfei-t01-tests-")
os.environ["DATABASE_PATH"] = str(pathlib.Path(TEMP_DIR.name) / "test.sqlite3")
os.environ["ADMIN_USERNAME"] = "test_admin"
os.environ["ADMIN_PASSWORD"] = "TestAdminPass123!"
os.environ["ADMIN_DISPLAY_NAME"] = "测试管理员"
os.environ.pop("RENDER", None)
os.environ["FLASK_ENV"] = "testing"

import app as app_module


def numeric_id(value):
    return int(str(value).replace("w", "").replace("cv", ""))


class ProjectHubT01Tests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.csrf = self.client.get("/api/bootstrap").json["csrfToken"]

    def post(self, path, payload):
        return self.client.post(path, json=payload, headers={"X-CSRF-Token": self.csrf})

    def register(self, username, display_name):
        response = self.post("/api/auth/register", {
            "username": username,
            "displayName": display_name,
            "password": "ReaderPass123!",
        })
        self.assertEqual(response.status_code, 200, response.json)
        self.csrf = response.json["csrfToken"]
        return response.json["state"]["currentUser"]

    def login(self, username, password):
        response = self.post("/api/auth/login", {"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.json)
        self.csrf = response.json["csrfToken"]
        return response.json["state"]["currentUser"]

    def test_site_and_guest_bootstrap(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("芳菲文学社", response.get_data(as_text=True))
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(self.client.get("/api/bootstrap").json["state"]["currentUser"]["role"], "guest")

    def test_csrf_required(self):
        response = self.client.post("/api/auth/register", json={
            "username": "noc_srf_user",
            "displayName": "无令牌",
            "password": "ReaderPass123!",
        })
        self.assertEqual(response.status_code, 403)

    def test_reader_cannot_admin(self):
        self.register("reader_admin_check", "普通读者")
        response = self.post("/api/admin/announcements", {"title": "越权公告", "content": "不应成功"})
        self.assertEqual(response.status_code, 403)

    def test_work_social_and_comments(self):
        self.register("author_one", "作者一")
        response = self.post("/api/works", {
            "title": "雨后",
            "category": "散文",
            "tags": ["雨", "校园"],
            "body": ["雨停之后，操场留下浅浅的光。"],
        })
        self.assertEqual(response.status_code, 200, response.json)
        work = response.json["state"]["works"][0]
        self.assertEqual(work["author"], "作者一")

        response = self.post(f"/api/works/{numeric_id(work['id'])}/like", {})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json["state"]["works"][0]["likes"], 1)

        response = self.post(f"/api/works/{numeric_id(work['id'])}/favorite", {})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json["state"]["works"][0]["favorites"], 1)

        response = self.post(f"/api/works/{numeric_id(work['id'])}/comments", {"text": "写得很好。"})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(len(response.json["state"]["works"][0]["comments"]), 1)

    def test_admin_announcement_and_logout_login(self):
        self.login("test_admin", "TestAdminPass123!")
        response = self.post("/api/admin/announcements", {"title": "测试公告", "content": "公告内容"})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json["state"]["announcements"][0]["title"], "测试公告")

        response = self.post("/api/auth/logout", {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["state"]["currentUser"]["role"], "guest")
        self.csrf = response.json["csrfToken"]

        self.login("test_admin", "TestAdminPass123!")
        self.assertEqual(self.client.get("/api/bootstrap").json["state"]["currentUser"]["role"], "admin")

    def test_private_message(self):
        user_a = self.register("message_a", "甲")
        self.logout_if_needed()
        response = self.client.get("/api/bootstrap")
        self.csrf = response.json["csrfToken"]
        self.register("message_b", "乙")
        response = self.post("/api/conversations", {"authorId": user_a["id"]})
        self.assertEqual(response.status_code, 200, response.json)
        conversation = response.json["state"]["conversations"][0]
        response = self.post(f"/api/conversations/{numeric_id(conversation['id'])}/messages", {"text": "你好", "replyTo": ""})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json["state"]["conversations"][0]["messages"][0]["text"], "你好")

    def logout_if_needed(self):
        if self.client.get("/api/bootstrap").json["state"]["currentUser"]["role"] != "guest":
            response = self.post("/api/auth/logout", {})
            self.csrf = response.json["csrfToken"]


if __name__ == "__main__":
    unittest.main(verbosity=2)
