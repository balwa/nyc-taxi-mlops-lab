"""The ops wiki's API (instructor-hosted, S6, given): list the published pages, fetch one with a
conditional GET.

Credentials come from Secrets Manager (`lab/wiki`: {"url": ..., "token": ...}) and are read every time a
client is made, so a rotated token (gameday E7) needs only the secret updated, no redeploy.

The wiki limits each student to 10 requests/s with bursts of 30 and answers 429 with Retry-After beyond
that; this client waits as told. Send each page's last ETag and an unchanged page costs a 304 and no body.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


class WikiError(RuntimeError):
    pass


@dataclass(frozen=True)
class PageRef:
    id: str
    title: str
    updated_at: str
    etag: str


@dataclass(frozen=True)
class Page:
    id: str
    title: str
    updated_at: str
    etag: str
    body: str


class Wiki:
    def __init__(self, url: str, token: str, max_retries: int = 6, timeout: float = 30.0):
        self.url, self.token, self.max_retries, self.timeout = url.rstrip("/"), token, max_retries, timeout

    @classmethod
    def from_secret(cls, name: str = "lab/wiki") -> Wiki:
        import boto3

        sm = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        s = json.loads(sm.get_secret_value(SecretId=name)["SecretString"])
        return cls(s["url"], s["token"])

    def _get(self, path: str, headers: dict | None = None) -> tuple[int, dict, dict]:
        req = urllib.request.Request(self.url + path, headers={"Authorization": f"Bearer {self.token}", **(headers or {})})
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return r.status, json.load(r), dict(r.headers)
            except urllib.error.HTTPError as e:
                if e.code == 304:
                    return 304, {}, dict(e.headers)
                if e.code == 429 and attempt < self.max_retries:
                    time.sleep(float(e.headers.get("Retry-After") or 1))
                    continue
                if e.code == 401:
                    raise WikiError("the wiki refused the token (401): was it rotated? Update lab/wiki in Secrets Manager") from e
                raise WikiError(f"GET {path}: HTTP {e.code}") from e
        raise WikiError(f"GET {path}: still rate-limited after {self.max_retries} retries")

    def pages(self) -> list[PageRef]:
        """The published pages, without bodies."""
        _, body, _ = self._get("/pages")
        return [PageRef(p["id"], p["title"], p["updated_at"], p["etag"]) for p in body]

    def page(self, page_id: str, etag: str | None = None) -> Page | None:
        """The page, or None if it hasn't changed since `etag` (a 304)."""
        status, body, _ = self._get(f"/pages/{page_id}", {"If-None-Match": etag} if etag else None)
        if status == 304:
            return None
        return Page(body["id"], body["title"], body["updated_at"], body["etag"], body["body"])
