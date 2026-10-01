import json, os, sys, tempfile, pathlib

pg_url = os.getenv("FF_VERIFY_DATABASE_URL", "").strip()
if pg_url:
    # 对照真实 PostgreSQL 运行时验证
    os.environ["DATABASE_URL"] = pg_url
    os.environ.pop("DATABASE_PATH", None)
else:
    db_path = pathlib.Path(tempfile.gettempdir()) / f"ff_v21_verify_{os.getpid()}.sqlite3"
    for suffix in ("", "-wal", "-shm"):
        p = pathlib.Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()
    os.environ["DATABASE_PATH"] = str(db_path)
os.environ["FLASK_ENV"] = "development"
os.environ.pop("RENDER", None)
if not pg_url:
    os.environ.pop("DATABASE_URL", None)
os.environ["ADMIN_USERNAME"] = "superboss"
os.environ["ADMIN_PASSWORD"] = "VerifyPass12345"
os.environ["ADMIN_DISPLAY_NAME"] = "超级管理员"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import app as A

results = []
def check(name, cond, extra=""):
    results.append((name, bool(cond), extra))
def body_of(r):
    try: return r.get_json() or {}
    except Exception: return {}
def state_of(r):
    return body_of(r).get("state") or {}
def post(client, url, payload, token):
    return client.post(url, data=json.dumps(payload), content_type="application/json",
                       headers={"X-CSRF-Token": token})
def fresh_token(client):
    return body_of(client.get("/api/bootstrap")).get("csrfToken", "")
def work_named(state, title):
    return next((x for x in state.get("works", []) if x.get("title") == title), None)

# --- setup ---
author = A.app.test_client()
g_token = fresh_token(author)
post(author, "/api/auth/register", {"username": "writer01", "displayName": "作者一号", "password": "Passw0rd123"}, g_token)
u_token = fresh_token(author)

adm = A.app.test_client()
a_token = fresh_token(adm)
post(adm, "/api/auth/login", {"username": "superboss", "password": "VerifyPass12345"}, a_token)
a_token = fresh_token(adm)

anon = A.app.test_client()

base = {
    "action": "submit", "title": "", "category": "散文", "tags": ["验证"],
    "body": ["初秋的风穿过旧操场，落叶在跑道边打着旋。"] * 40,
    "excerpt": "初秋的风穿过旧操场。", "isPublic": True, "allowComments": True,
    "allowFavorites": True, "visibility": "PUBLIC",
    "originalConfirmed": True, "rightsConfirmed": True,
}

# --- 1. 正常投稿自动通过 ---
r = post(author, "/api/works", {**base, "title": "正常投稿"}, u_token)
st = state_of(r)
w = work_named(st, "正常投稿")
check("1.1 正常投稿提交成功", r.status_code == 200, r.status_code)
check("1.2 正常投稿经 Agent 自动发布", (w or {}).get("status") == "published", (w or {}).get("status"))
st_admin = state_of(adm.get("/api/bootstrap"))
check("1.3 Agent 运行记录已写入", len(st_admin.get("agentRuns", [])) >= 1, len(st_admin.get("agentRuns", [])))
check("1.4 Agent 结果标记无需人工复核", all(x.get("needsHumanReview") in (0, False) for x in st_admin.get("agentResults", [])), st_admin.get("agentResults"))
check("1.5 低风险不生成复核任务", st_admin.get("agentTasks") == [], st_admin.get("agentTasks"))

# --- 2. 高风险投稿进入人工复核 ---
rn = post(author, "/api/works", {**base, "title": "高风险投稿",
          "body": ["本文提供代写服务，欢迎联系。"] * 40}, u_token)
st = state_of(rn)
w2 = work_named(st, "高风险投稿")
check("2.1 高风险投稿提交成功", rn.status_code == 200, rn.status_code)
check("2.2 高风险投稿进入等待人工复核", (w2 or {}).get("status") == "pending_review", (w2 or {}).get("status"))
check("2.3 未过审不进入公开列表", work_named(state_of(anon.get("/api/bootstrap")), "高风险投稿") is None)
st_admin = state_of(adm.get("/api/bootstrap"))
open_tasks = [t for t in st_admin.get("agentTasks", []) if t.get("status") == "open"]
check("2.4 生成待处理 Agent 复核任务", len(open_tasks) >= 1, st_admin.get("agentTasks"))
rev = [x for x in st_admin.get("agentResults", []) if x.get("recommendation") == "REVIEW"]
check("2.5 Agent 推荐人工复核", len(rev) >= 1, st_admin.get("agentResults"))

# --- 3. 人工审核关闭任务 ---
r = post(adm, "/api/admin/works/%d/review" % A.parse_numeric_id(w2["id"]), {"action": "publish", "note": "人工确认"}, a_token)
st_admin = state_of(r)
check("3.1 人工审核通过成功", r.status_code == 200, r.status_code)
check("3.2 复核任务被关闭", all(t.get("status") == "resolved" for t in st_admin.get("agentTasks", [])) and len(st_admin.get("agentTasks", [])) >= 1, st_admin.get("agentTasks"))
check("3.3 作品状态变为已发布", (work_named(st_admin, "高风险投稿") or {}).get("status") == "published")
check("3.4 审核后公开可见", work_named(state_of(anon.get("/api/bootstrap")), "高风险投稿") is not None)

# --- 4. 月度优秀 ---
target = work_named(st_admin, "正常投稿")
r = post(adm, "/api/admin/monthly-awards", {"workId": target["id"], "month": "2026-10", "rank": 1, "reason": "验证"}, a_token)
check("4.1 月度评选保存成功", r.status_code == 200, r.status_code)
awards = [a for a in state_of(r).get("monthlyAwards", []) if a.get("workId") == target["id"]]
check("4.2 获奖记录持久化", len(awards) == 1, len(awards))
check("4.3 获奖记录含评选人", bool(awards) and bool(awards[0].get("selectedBy")), awards[0].get("selectedBy") if awards else None)
r = post(adm, "/api/admin/monthly-awards", {"workId": target["id"], "month": "2026-13", "rank": 1, "reason": "x"}, a_token)
check("4.4 非法月份被拒绝", r.status_code == 400, r.status_code)
priv = post(author, "/api/works", {**base, "title": "私密稿", "visibility": "PRIVATE"}, u_token)
pw = work_named(state_of(priv), "私密稿")
r = post(adm, "/api/admin/monthly-awards", {"workId": pw["id"], "month": "2026-10", "rank": 2, "reason": "x"}, a_token)
check("4.5 私密作品不能参评", r.status_code == 400, r.status_code)

# --- 5. 权限 ---
check("5.1 游客访问管理接口 401", post(anon, "/api/admin/announcements", {"title": "x", "content": "y"}, fresh_token(anon)).status_code == 401)
check("5.2 普通用户访问管理接口 403", post(author, "/api/admin/announcements", {"title": "x", "content": "y"}, fresh_token(author)).status_code == 403)
ids = {}
for i in (1, 2, 3):
    c = A.app.test_client()
    r = post(c, "/api/auth/register", {"username": "senior0%d" % i, "displayName": "高管理%d" % i, "password": "Passw0rd123"}, fresh_token(c))
    ids[i] = state_of(r).get("currentUser", {}).get("id")
check("5.3 任命第 1 名高级管理员", post(adm, "/api/admin/admins/appoint", {"userId": ids[1], "reason": "一"}, a_token).status_code == 200)
check("5.4 任命第 2 名高级管理员", post(adm, "/api/admin/admins/appoint", {"userId": ids[2], "reason": "二"}, a_token).status_code == 200)
check("5.5 第 3 名被服务端拒绝", post(adm, "/api/admin/admins/appoint", {"userId": ids[3], "reason": "三"}, a_token).status_code >= 400)
sen = A.app.test_client()
st = fresh_token(sen)
r = post(sen, "/api/auth/login", {"username": "senior01", "password": "Passw0rd123"}, st)
s_token = body_of(r).get("csrfToken", "")
check("5.6 高级管理员登录成功", r.status_code == 200, r.status_code)
check("5.7 高级管理员不能任命管理员", post(sen, "/api/admin/admins/appoint", {"userId": ids[3], "reason": "越权"}, s_token).status_code == 403)
check("5.8 高级管理员可发布公告", post(sen, "/api/admin/announcements", {"title": "高管公告", "content": "内容"}, s_token).status_code == 200)
check("5.9 错误 CSRF 被拒绝", adm.post("/api/admin/announcements", data=json.dumps({"title": "x", "content": "y"}), content_type="application/json", headers={"X-CSRF-Token": "bad"}).status_code == 403)

# --- 6. 私密隔离与排行 ---
anon_works = [x.get("title") for x in state_of(anon.get("/api/bootstrap")).get("works", [])]
check("6.1 未登录看不到私密稿", "私密稿" not in anon_works, anon_works)
check("6.2 未登录看得到公开稿", "正常投稿" in anon_works, anon_works)
other = A.app.test_client()
r = post(other, "/api/auth/register", {"username": "reader99", "displayName": "路人", "password": "Passw0rd123"}, fresh_token(other))
check("6.3 其他用户看不到私密稿", "私密稿" not in [x.get("title") for x in state_of(r).get("works", [])])
check("6.4 作者本人看得到私密稿", "私密稿" in [x.get("title") for x in state_of(author.get("/api/bootstrap")).get("works", [])])
check("6.5 排行榜不含私密稿", "私密稿" not in json.dumps(state_of(anon.get("/api/bootstrap")).get("rankings") or {}, ensure_ascii=False))
pending = post(author, "/api/works", {**base, "title": "待审稿", "body": ["本文提供代写服务。"] * 40}, u_token)
check("6.6 排行榜不含待审稿", "待审稿" not in json.dumps(state_of(anon.get("/api/bootstrap")).get("rankings") or {}, ensure_ascii=False))

# --- 7. 系统状态 / 持久化 ---
h = state_of(adm.get("/api/bootstrap")).get("systemHealth")
check("7.1 管理员可见系统状态", isinstance(h, list) and len(h) >= 8, len(h or []))
check("7.2 非管理员系统状态为空", state_of(anon.get("/api/bootstrap")).get("systemHealth") == [])
before = len(state_of(anon.get("/api/bootstrap")).get("works", []))
A.init_db()
check("7.3 重新初始化后数据仍在", len(state_of(anon.get("/api/bootstrap")).get("works", [])) == before and before > 0, before)

print()
passed = sum(1 for _, ok, _ in results if ok)
for name, ok, extra in results:
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else "   -> " + str(extra)))
print()
print("%d/%d passed" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
