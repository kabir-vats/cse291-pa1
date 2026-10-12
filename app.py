import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from flask import Flask, g, make_response, redirect, render_template, request

app = Flask(__name__)
app.config['DATABASE'] = Path(__file__).with_name('boogle.db')


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        g.db.executescript('''
            CREATE TABLE IF NOT EXISTS clients (
                client_id TEXT PRIMARY KEY,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS requests (
                request_id INTEGER PRIMARY KEY,
                client_id TEXT NOT NULL,
                ts TEXT NOT NULL,
                ip TEXT
            );
            CREATE TABLE IF NOT EXISTS searches (
                search_id INTEGER PRIMARY KEY,
                client_id TEXT NOT NULL,
                query TEXT NOT NULL,
                ts TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS searches_by_client
                ON searches (client_id, ts DESC, search_id DESC);
            CREATE INDEX IF NOT EXISTS requests_by_client
                ON requests (client_id, request_id DESC);
        ''')
    return g.db


@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()


@app.before_request
def track_client():
    g.client_id = request.cookies.get('boogle_id')
    g.new_client = g.client_id is None and request.path == '/'
    if g.new_client:
        g.client_id = str(uuid4())
    g.ts = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    if g.client_id is not None:
        db = get_db()
        with db:
            db.execute('''
                INSERT INTO clients VALUES (?, ?, ?)
                ON CONFLICT(client_id) DO UPDATE SET last_seen = excluded.last_seen
            ''', (g.client_id, g.ts, g.ts))
            db.execute('INSERT INTO requests (client_id, ts, ip) VALUES (?, ?, ?)',
                       (g.client_id, g.ts, request.remote_addr))


def client_searches(client_id):
    rows = get_db().execute('''
        SELECT query, ts FROM searches WHERE client_id = ?
        ORDER BY ts DESC, search_id DESC
    ''', (client_id,)).fetchall()
    return [dict(row) for row in rows]


@app.get('/')
def index():
    response = make_response(render_template('boogle.html'))
    if g.new_client:
        response.set_cookie('boogle_id', g.client_id, max_age=31536000,
                            path='/', samesite='Lax')
    return response


@app.get('/search')
def search():
    query = request.args.get('q', '')
    if query.strip() and g.client_id is not None:
        db = get_db()
        with db:
            db.execute('INSERT INTO searches (client_id, query, ts) VALUES (?, ?, ?)',
                       (g.client_id, query, g.ts))
    return redirect('/', code=303)


@app.get('/api/history')
def history():
    return {'client_id': g.client_id, 'searches': client_searches(g.client_id)}


@app.get('/dump')
def dump():
    db = get_db()
    clients = []
    for row in db.execute('SELECT * FROM clients ORDER BY first_seen, client_id').fetchall():
        client = dict(row)
        ips = [visit['ip'] for visit in db.execute('''
            SELECT ip FROM requests WHERE client_id = ? ORDER BY request_id DESC
        ''', (client['client_id'],)).fetchall()]
        client['latest_ip'] = ips[0] if ips else None
        client['ips'] = list(dict.fromkeys(ips))
        client['searches'] = client_searches(client['client_id'])
        clients.append(client)
    return {'clients': clients}


@app.get('/jsontest')
def json_test():
    return {
        "data": "I am in CSE291!"
    }

if __name__ == "__main__":
    app.run(host="0.0.0.0", port="8000")
