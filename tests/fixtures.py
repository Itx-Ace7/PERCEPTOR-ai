"""Small in-memory base/head trees used to exercise the engine. Nothing here is shipped or run as an app."""

from __future__ import annotations

from pathlib import Path

BASE = {
    "requirements.txt": "flask==3.0.3\npyyaml==6.0.1\n",
    "backend/auth.py": (
        "def require_auth(request):\n"
        "    token = request.headers.get('Authorization', '')\n"
        "    if not token.startswith('Bearer '):\n"
        "        raise PermissionError('missing token')\n"
        "    return token\n"
    ),
    "backend/config.py": "import os\n\nDEBUG = False\nSTRIPE_KEY = os.getenv('STRIPE_KEY', '')\nBIND_HOST = '127.0.0.1'\n",
    "backend/repo.py": (
        "def fetch_rows(conn, owner_id):\n"
        "    return conn.execute('SELECT id FROM rows WHERE owner_id = ?', (owner_id,)).fetchall()\n"
        "\n\n"
        "def load_many(conn, owner_ids):\n"
        "    marks = ','.join('?' for _ in owner_ids)\n"
        "    query = f\"SELECT id FROM rows WHERE owner_id IN ({marks})\"\n"
        "    return conn.execute(query, tuple(owner_ids)).fetchall()\n"
    ),
    "backend/service.py": (
        "from repo import fetch_rows\n"
        "\n\n"
        "def process(conn, owner_id, amount):\n"
        "    if amount is None or amount <= 0:\n"
        "        raise ValueError('amount must be positive')\n"
        "    owner = owners_lookup(conn, owner_id)\n"
        "    if owner is None:\n"
        "        raise ValueError('unknown owner')\n"
        "    label = owner['name'].strip()\n"
        "    return {'status': 'ok', 'amount': amount, 'owner': label, 'rows': fetch_rows(conn, owner_id)}\n"
        "\n\n"
        "def owners_lookup(conn, owner_id):\n"
        "    return conn.execute('SELECT id, name FROM owners WHERE id = ?', (owner_id,)).fetchone()\n"
    ),
    "backend/routes.py": (
        "from auth import require_auth\n"
        "from service import process\n"
        "\n\n"
        "def create_item(request, conn):\n"
        "    require_auth(request)\n"
        "    data = request.json\n"
        "    return process(conn, data.get('owner_id'), data.get('amount')), 201\n"
    ),
    "tests/test_service.py": (
        "import pytest\n"
        "\n"
        "from service import process\n"
        "\n\n"
        "class FakeConn:\n"
        "    def execute(self, *args, **kwargs):\n"
        "        return self\n"
        "\n"
        "    def fetchone(self):\n"
        "        return {'name': 'Ada'}\n"
        "\n"
        "    def fetchall(self):\n"
        "        return []\n"
        "\n\n"
        "def test_process_success():\n"
        "    assert process(FakeConn(), 'o1', 25)['status'] == 'ok'\n"
        "\n\n"
        "def test_process_rejects_negative():\n"
        "    with pytest.raises(ValueError):\n"
        "        process(FakeConn(), 'o1', -5)\n"
    ),
}

HEAD = {
    **BASE,
    "requirements.txt": "flask==3.0.3\npyyaml==5.3.1\n",
    "backend/config.py": "DEBUG = True\nSTRIPE_KEY = 'sk_live_FIXTURE0NLY'\nBIND_HOST = '0.0.0.0'\n",
    "backend/repo.py": (
        "def fetch_rows(conn, owner_id):\n"
        "    query = f\"SELECT * FROM rows WHERE owner_id = '{owner_id}'\"\n"
        "    return conn.execute(query).fetchall()\n"
        "\n\n"
        "def load_many(conn, owner_ids):\n"
        "    rows = []\n"
        "    for oid in owner_ids:\n"
        "        rows.extend(conn.execute('SELECT id FROM rows WHERE owner_id = ?', (oid,)).fetchall())\n"
        "    return rows\n"
    ),
    "backend/service.py": (
        "from repo import fetch_rows\n"
        "\n\n"
        "def process(conn, owner_id, amount):\n"
        "    owner = owners_lookup(conn, owner_id)\n"
        "    label = owner['name'].strip()\n"
        "    return {'status': 'ok', 'amount': amount, 'owner': label, 'rows': fetch_rows(conn, owner_id)}\n"
        "\n\n"
        "def owners_lookup(conn, owner_id):\n"
        "    return conn.execute('SELECT id, name FROM owners WHERE id = ?', (owner_id,)).fetchone()\n"
    ),
    "backend/routes.py": (
        "from service import process\n"
        "\n\n"
        "def create_item(request, conn):\n"
        "    data = request.json\n"
        "    return process(conn, data.get('owner_id'), data.get('amount')), 200\n"
    ),
    "tests/test_service.py": BASE["tests/test_service.py"].split("def test_process_rejects_negative")[0].rstrip() + "\n",
}

# What the head tree above is expected to trip. Used only by tests.
EXPECTED = [
    ("SEC-SQLI", "backend/repo.py"),
    ("SEC-SECRET", "backend/config.py"),
    ("SEC-CONFIG", "backend/config.py"),
    ("SEC-AUTH-REMOVED", "backend/routes.py"),
    ("BUG-NULL", "backend/service.py"),
    ("BUG-VALIDATION", "backend/service.py"),
    ("API-BEHAVIOR", "backend/routes.py"),
    ("PERF-QUERY-LOOP", "backend/repo.py"),
    ("DEP-DOWNGRADE", "requirements.txt"),
    ("TEST-GAP", "tests/test_service.py"),
]


def write_tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root
