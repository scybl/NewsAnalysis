from __future__ import annotations


ADMIN_ROLES = {"admin", "admin_readonly"}
READONLY_ADMIN_ROLE = "admin_readonly"
DATA_CONSOLE_ROLES = {*ADMIN_ROLES, "user"}

DATA_CONSOLE_PAGES = {"/admin-market.html", "/admin-news.html", "/admin-crawler.html"}
ADMIN_ONLY_PAGES = {
    "/admin-accounts.html",
    "/admin-ops.html",
    "/admin-data-audit.html",
    "/admin-audit.html",
    "/admin-archives.html",
    "/admin-credentials.html",
    "/admin-distribution.html",
    "/admin-agent.html",
}
