# -*- coding: utf-8 -*-
"""
Trazelio Sport PLATAFORMA - SaaS multi-club: web + app instalable (PWA), asistencia facial, estadísticas y avisos por WhatsApp
Requiere: pip install -r requirements.txt   |  Ejecutar: python trazelio_sport.py  (ver LEEME.txt para publicarlo)
Usuarios iniciales: admin / admin1234  |  entrenador / profe1234  (cambio obligatorio al ingresar)
"""
import base64, hashlib, hmac, io, json, math, os, re, secrets, sqlite3, sys, threading, time, unicodedata, urllib.error, urllib.parse, urllib.request, webbrowser
from datetime import date, datetime, timedelta
from functools import wraps
from flask import Flask, Response, abort, flash, g, has_request_context, jsonify, redirect, render_template, request, send_file, session
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__))
DATA = os.path.join(BASE, 'datos_deportivos'); os.makedirs(os.path.join(DATA, 'backups'), exist_ok=True)
DB = os.path.join(DATA, 'trazelio_sport.db')   # solo para migrar una instalación anterior
CLUBES = os.path.join(DATA, 'clubes'); os.makedirs(CLUBES, exist_ok=True)   # una base de datos por club
PLAT = os.path.join(DATA, 'plataforma.db')                                  # registro de clubes y suscripciones
TZ_LOCAL = os.environ.get('TRAZELIO_TZ', 'America/Bogota')
if hasattr(time, 'tzset'): os.environ['TZ'] = TZ_LOCAL; time.tzset()
SLUG_RE = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')
RESERVADOS = {'admin', 'api', 'www', 'static', 'plataforma', 'registro', 'login', 'logout', 'p', 'j', 'foto', 'soporte', 'demo', 'trazelio', 'app', 'club', 'webhook'}
TRIAL_DIAS = 15
CONTACTO_WA = ''.join(ch for ch in os.environ.get('TRAZELIO_CONTACTO_WA', '') if ch.isdigit())
SUPER_PASS = os.environ.get('TRAZELIO_SUPER_PASS', '')
WEBHOOK_SECRET = os.environ.get('TRAZELIO_WEBHOOK_SECRET', '')
API_URL = os.environ.get('TRAZELIO_API_URL', '').rstrip('/')   # API cloud (FastAPI)
WEB_URL = os.environ.get('TRAZELIO_WEB_URL', '').rstrip('/')   # web (Next.js)
BRIDGE_SECRET = os.environ.get('TRAZELIO_BRIDGE_SECRET', '')   # mismo valor que BRIDGE_SECRET de la API FastAPI
PLANES = {   # PRECIOS DE EJEMPLO: define los tuyos con TRAZELIO_PRECIO_MENSUAL / TRAZELIO_PRECIO_ANUAL
    'MENSUAL': dict(nombre='Mensual', precio=int(os.environ.get('TRAZELIO_PRECIO_MENSUAL', 89000)), dias=30, url=os.environ.get('TRAZELIO_PAGO_MENSUAL', '')),
    'ANUAL': dict(nombre='Anual', precio=int(os.environ.get('TRAZELIO_PRECIO_ANUAL', 890000)), dias=365, url=os.environ.get('TRAZELIO_PAGO_ANUAL', '')),
}
PORT = int(os.environ.get('TRAZELIO_PORT', 5000))
HOST = os.environ.get('TRAZELIO_HOST', '127.0.0.1')   # 0.0.0.0 para atender a otros equipos
HTTPS = os.environ.get('TRAZELIO_HTTPS') == '1'        # 1 si va detrás de Caddy/Nginx con HTTPS
UMBRAL_FACIAL = 0.5     # distancia máxima para aceptar un rostro (menor = más estricto)
MARGEN_FACIAL = 0.04    # el segundo deportista más parecido debe quedar al menos así de lejos
MAX_ROSTROS = 5         # muestras por deportista
INTENTOS = {}
DIA_GRACIA = 5          # la mensualidad del mes se considera vencida después de este día
CIERRE_CIEGO = True     # el entrenador no ve el efectivo esperado antes de contar
MENSUALIDAD_SUGERIDA = 80000
MEDIOS = ['Efectivo', 'Nequi', 'DaviPlata', 'Bancolombia', 'Davivienda', 'Tarjeta Crédito', 'Tarjeta Débito', 'Sistecrédito']
CATEGORIAS = ['Sub-8', 'Sub-10', 'Sub-12', 'Sub-14', 'Sub-16', 'Sub-18', 'Mayores Femenino', 'Mayores Masculino']
ROLES = ['Jugador de Campo', 'Portero / Arquero', 'Asistente Técnico']

SCHEMA = """
CREATE TABLE IF NOT EXISTS club(id INTEGER PRIMARY KEY, nombre TEXT, nit TEXT, telefono TEXT);
CREATE TABLE IF NOT EXISTS usuarios(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, rol TEXT NOT NULL, cambiar INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS deportistas(id INTEGER PRIMARY KEY AUTOINCREMENT, documento TEXT UNIQUE NOT NULL, nombre TEXT NOT NULL, categoria TEXT NOT NULL, rol_deportivo TEXT NOT NULL, acudiente_nombre TEXT, acudiente_celular TEXT, contacto_emergencia TEXT, activo INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS asistencias(id INTEGER PRIMARY KEY AUTOINCREMENT, deportista_id INTEGER NOT NULL REFERENCES deportistas(id), entrenador TEXT, metodo TEXT DEFAULT 'MANUAL', fecha TEXT DEFAULT (datetime('now','localtime')));
CREATE UNIQUE INDEX IF NOT EXISTS ux_asistencia_dia ON asistencias(deportista_id, date(fecha));
CREATE TABLE IF NOT EXISTS productos(id INTEGER PRIMARY KEY AUTOINCREMENT, codigo TEXT UNIQUE NOT NULL, producto TEXT NOT NULL, talla TEXT, costo REAL NOT NULL CHECK(costo>=0), precio REAL NOT NULL CHECK(precio>=0), stock INTEGER NOT NULL DEFAULT 0 CHECK(stock>=0), stock_minimo INTEGER DEFAULT 5, activo INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS cajas(id INTEGER PRIMARY KEY AUTOINCREMENT, cajero TEXT NOT NULL, apertura TEXT DEFAULT (datetime('now','localtime')), base REAL NOT NULL, cierre TEXT, contado REAL, esperado REAL, diferencia REAL, estado TEXT DEFAULT 'ABIERTA', notas TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS ux_caja_abierta ON cajas(cajero) WHERE estado='ABIERTA';
CREATE TABLE IF NOT EXISTS egresos(id INTEGER PRIMARY KEY AUTOINCREMENT, caja_id INTEGER NOT NULL REFERENCES cajas(id), concepto TEXT NOT NULL, monto REAL NOT NULL CHECK(monto>0), fecha TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS mensualidades(id INTEGER PRIMARY KEY AUTOINCREMENT, deportista_id INTEGER NOT NULL REFERENCES deportistas(id), mes TEXT NOT NULL, monto REAL NOT NULL CHECK(monto>0), medio_pago TEXT NOT NULL, caja_id INTEGER REFERENCES cajas(id), cajero TEXT, fecha TEXT DEFAULT (datetime('now','localtime')), UNIQUE(deportista_id, mes));
CREATE TABLE IF NOT EXISTS ventas(id INTEGER PRIMARY KEY AUTOINCREMENT, deportista_id INTEGER REFERENCES deportistas(id), total REAL NOT NULL, metodo_pago TEXT NOT NULL, caja_id INTEGER REFERENCES cajas(id), cajero TEXT, fecha TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS venta_items(id INTEGER PRIMARY KEY AUTOINCREMENT, venta_id INTEGER NOT NULL REFERENCES ventas(id), producto_id INTEGER, descripcion TEXT, cantidad INTEGER, precio REAL);
CREATE TABLE IF NOT EXISTS rostros(id INTEGER PRIMARY KEY AUTOINCREMENT, deportista_id INTEGER NOT NULL REFERENCES deportistas(id), descriptor TEXT NOT NULL, creado TEXT DEFAULT (datetime('now','localtime')));
CREATE INDEX IF NOT EXISTS ix_rostros_dep ON rostros(deportista_id);
CREATE TABLE IF NOT EXISTS tarifas(categoria TEXT PRIMARY KEY, monto REAL NOT NULL CHECK(monto>=0));
CREATE TABLE IF NOT EXISTS ajustes(clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS usuario_categorias(usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE, categoria TEXT NOT NULL, PRIMARY KEY(usuario_id, categoria));
CREATE TABLE IF NOT EXISTS eventos(id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT NOT NULL CHECK(tipo IN ('PARTIDO','ENTRENO')), fecha TEXT NOT NULL, categoria TEXT NOT NULL, rival TEXT, lugar TEXT, goles_favor INTEGER, goles_contra INTEGER, notas TEXT, creado_por TEXT, creado TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS estadisticas(id INTEGER PRIMARY KEY AUTOINCREMENT, evento_id INTEGER NOT NULL REFERENCES eventos(id) ON DELETE CASCADE, deportista_id INTEGER NOT NULL REFERENCES deportistas(id), jugo INTEGER DEFAULT 1, minutos INTEGER DEFAULT 0, goles INTEGER DEFAULT 0, asistencias INTEGER DEFAULT 0, amarillas INTEGER DEFAULT 0, rojas INTEGER DEFAULT 0, atajadas INTEGER DEFAULT 0, calificacion INTEGER DEFAULT 0, actitud INTEGER DEFAULT 0, comentario TEXT, UNIQUE(evento_id, deportista_id));
CREATE TABLE IF NOT EXISTS avisos(id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT NOT NULL, deportista_id INTEGER REFERENCES deportistas(id), celular TEXT NOT NULL, texto TEXT NOT NULL, estado TEXT NOT NULL DEFAULT 'PENDIENTE', intentos INTEGER NOT NULL DEFAULT 0, error TEXT, creado TEXT DEFAULT (datetime('now','localtime')), enviado TEXT);
CREATE INDEX IF NOT EXISTS ix_avisos_estado ON avisos(estado);
"""
MIGRACIONES = (('deportistas', 'consentimiento_biometrico', 'TEXT'), ('asistencias', 'distancia', 'REAL'), ('usuarios', 'activo', 'INTEGER DEFAULT 1'), ('deportistas', 'token_acudiente', 'TEXT'),
    ('deportistas', 'token_jugador', 'TEXT'), ('deportistas', 'foto', 'TEXT'), ('deportistas', 'foto_pendiente', 'TEXT'), ('deportistas', 'fecha_nacimiento', 'TEXT'), ('deportistas', 'posicion', 'TEXT'),
    ('deportistas', 'dorsal', 'INTEGER'), ('deportistas', 'pie', 'TEXT'), ('deportistas', 'estatura', 'INTEGER'), ('deportistas', 'peso', 'INTEGER'), ('deportistas', 'apodo', 'TEXT'), ('deportistas', 'lema', 'TEXT'),
    ('deportistas', 'acepta_whatsapp', 'INTEGER DEFAULT 0'), ('usuarios', 'nombre_completo', 'TEXT'), ('usuarios', 'celular', 'TEXT'), ('usuarios', 'email', 'TEXT'), ('usuarios', 'foto', 'TEXT'), ('usuarios', 'cargo', 'TEXT'), ('usuarios', 'origen', 'TEXT'), ('deportistas', 'cloud_id', 'INTEGER'))


_PREPARADAS = set()

def preparar_db(c):
    c.executescript(SCHEMA)
    for tabla, col, tipo in MIGRACIONES:
        if col not in [r[1] for r in c.execute(f'PRAGMA table_info({tabla})')]:
            c.execute(f'ALTER TABLE {tabla} ADD COLUMN {col} {tipo}')

def ruta_club(slug=None):
    if slug is None and has_request_context(): slug = g.get('club')
    if not slug:
        if has_request_context(): raise PermissionError('Sesión sin club')
        return DB
    if not SLUG_RE.match(slug): raise ValueError('Código de club inválido')
    return os.path.join(CLUBES, slug, 'club.db')

def db(slug=None):
    ruta = ruta_club(slug)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    c = sqlite3.connect(ruta, timeout=15, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA journal_mode=WAL')
    if ruta not in _PREPARADAS:
        preparar_db(c); _PREPARADAS.add(ruta)
    return c

def q(sql, args=(), one=False, slug=None):
    c = db(slug)
    try:
        cur = c.execute(sql, args)
        return cur.fetchone() if one else cur.fetchall()
    finally:
        c.close()

def ex(sql, args=(), slug=None):
    c = db(slug)
    try:
        return c.execute(sql, args).lastrowid
    finally:
        c.close()

def pdb():
    c = sqlite3.connect(PLAT, timeout=15, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute("CREATE TABLE IF NOT EXISTS clubes(slug TEXT PRIMARY KEY, nombre TEXT NOT NULL, email TEXT, celular TEXT, plan TEXT NOT NULL DEFAULT 'MENSUAL', estado TEXT NOT NULL DEFAULT 'TRIAL', vence TEXT NOT NULL, creado TEXT DEFAULT (datetime('now','localtime')), ultimo_pago TEXT)")
    return c

def pq(sql, args=(), one=False):
    c = pdb()
    try:
        cur = c.execute(sql, args)
        return cur.fetchone() if one else cur.fetchall()
    finally:
        c.close()

def pex(sql, args=()):
    c = pdb()
    try:
        return c.execute(sql, args).lastrowid
    finally:
        c.close()

def estado_club(slug):
    r = pq('SELECT * FROM clubes WHERE slug=?', (slug,), True)
    if not r: return None
    d = dict(r); hoy = date.today()
    d['dias'] = (date.fromisoformat(d['vence']) - hoy).days
    d['vigente'] = d['estado'] in ('TRIAL', 'ACTIVE') and d['dias'] >= 0
    return d

def crear_club(slug, nombre, email, celular, usuario, clave, nombre_completo, dias=TRIAL_DIAS):
    pex("INSERT INTO clubes(slug,nombre,email,celular,plan,estado,vence) VALUES(?,?,?,?,'MENSUAL','TRIAL',?)",
        (slug, nombre, email, celular, (date.today() + timedelta(days=dias)).isoformat()))
    try:
        c = db(slug)
        c.execute('INSERT INTO club VALUES(1,?,?,?)', (nombre, '', celular))
        c.execute("INSERT INTO usuarios(username,password,rol,cambiar,nombre_completo,celular,email,cargo) VALUES(?,?,'admin',0,?,?,?,'Director')",
                  (usuario, generate_password_hash(clave), nombre_completo, celular, email))
        c.close()
    except Exception:
        pex('DELETE FROM clubes WHERE slug=?', (slug,)); raise

def init_db():
    c = pdb(); hay = c.execute('SELECT 1 FROM clubes').fetchone(); c.close()
    if not hay and os.path.exists(DB):   # instalación anterior de un solo club
        try:
            os.makedirs(os.path.join(CLUBES, 'principal'), exist_ok=True)
            o, d = sqlite3.connect(DB), sqlite3.connect(ruta_club('principal')); o.backup(d); o.close(); d.close()
            nombre = q('SELECT nombre FROM club', one=True, slug='principal')['nombre']
            for u in q("SELECT id FROM usuarios WHERE rol='entrenador'", slug='principal'):
                for cat in CATEGORIAS: ex('INSERT OR IGNORE INTO usuario_categorias VALUES(?,?)', (u['id'], cat), slug='principal')
            pex("INSERT INTO clubes(slug,nombre,plan,estado,vence) VALUES('principal',?,'ANUAL','ACTIVE',?)", (nombre, (date.today() + timedelta(days=365)).isoformat()))
            print("Instalación anterior migrada al club 'principal'")
        except Exception as e:
            print('No se pudo migrar la instalación anterior:', e)

def backup():
    carpeta = os.path.join(os.path.dirname(ruta_club()), 'backups'); os.makedirs(carpeta, exist_ok=True)
    dst = os.path.join(carpeta, datetime.now().strftime('trazelio_%Y%m%d_%H%M%S.db'))
    src, out = db(), sqlite3.connect(dst)
    src.backup(out); out.close(); src.close()
    for f in sorted(os.listdir(carpeta))[:-30]:
        os.remove(os.path.join(carpeta, f))

def ajuste(clave, defecto, slug=None):
    r = q('SELECT valor FROM ajustes WHERE clave=?', (clave,), True, slug=slug)
    return r['valor'] if r else defecto

def dia_gracia():
    return int(ajuste('dia_gracia', DIA_GRACIA))

def cierre_ciego():
    return ajuste('cierre_ciego', '1' if CIERRE_CIEGO else '0') == '1'

def tarifas():
    return {r['categoria']: r['monto'] for r in q('SELECT * FROM tarifas')}

def norm(t):
    t = unicodedata.normalize('NFD', (t or '').casefold())
    return ''.join(ch for ch in t if unicodedata.category(ch) != 'Mn')

def cop(v):
    return '$' + f"{float(v or 0):,.0f}".replace(',', '.')

def num(s):
    v = float(str(s).strip() or 0)
    if v < 0: raise ValueError('Los valores no pueden ser negativos')
    return round(v, 2)

app = Flask(__name__, static_folder=os.path.join(BASE, 'static'), template_folder=os.path.join(BASE, 'templates'))

def _clave():
    f = os.path.join(DATA, 'secret.key')
    if not os.path.exists(f):
        with open(f, 'w') as h: h.write(secrets.token_hex(32))
    with open(f) as h: return h.read().strip()

app.secret_key = _clave()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=HTTPS,
                  PERMANENT_SESSION_LIFETIME=60 * 60 * 12, MAX_CONTENT_LENGTH=8 * 1024 * 1024)
if HTTPS:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.jinja_env.filters['cop'] = cop
app.jinja_env.globals['csrf'] = lambda: session.setdefault('csrf', secrets.token_hex(16))

def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if 'uid' not in session or not session.get('club'): return redirect('/login')
        return f(*a, **k)
    return w

def admin_required(f):
    @wraps(f)
    @login_required
    def w(*a, **k):
        if session.get('rol') != 'admin': abort(403)
        return f(*a, **k)
    return w

LIBRES = ('login', 'logout', 'manifest', 'sw', 'index', 'registro', 'suscripcion', 'webhook_pagos', 'sso')
KIOSCO_OK = ('asistencia_facial', 'api_identificar', 'api_paquete', 'api_sync', 'api_csrf', 'suscripcion', 'logout', 'login', 'manifest', 'sw', 'static')

@app.before_request
def seguridad():
    session.setdefault('csrf', secrets.token_hex(16))
    ep = request.endpoint or ''
    if request.method == 'POST' and ep != 'webhook_pagos' and (request.form.get('csrf') or request.headers.get('X-CSRF')) != session['csrf']: abort(400)
    if ep == 'static' or ep.startswith('plataforma'): return
    slug = (request.view_args or {}).get('slug')
    g.club = slug or session.get('club')
    if g.club and not SLUG_RE.match(g.club): abort(404)
    if g.club and ep not in LIBRES:
        info = estado_club(g.club)
        if not info:
            if slug: abort(404)
            session.clear(); return redirect('/login')
        g.info = info
        if session.get('uid') and not slug:   # si desactivan al usuario en la plataforma, su sesión cae en la siguiente petición
            fila = q('SELECT COALESCE(activo,1) a FROM usuarios WHERE id=?', (session['uid'],), True)
            if not fila or not fila['a']: session.clear(); return redirect('/login')
        if not info['vigente'] and not slug: return redirect('/suscripcion')
    if session.get('rol') == 'kiosco' and ep not in KIOSCO_OK: return redirect('/asistencia/facial')
    if session.get('cambiar') and ep not in ('cuenta', 'logout', 'login', 'manifest', 'sw', 'api_csrf', 'suscripcion'): return redirect('/cuenta')

@app.context_processor
def ctx():
    club = q('SELECT * FROM club', one=True) if g.get('club') else None
    return dict(web_url=WEB_URL, club=club or {'nombre': 'Trazelio Sport', 'nit': '', 'telefono': ''}, medios=MEDIOS, categorias=CATEGORIAS, roles=ROLES, css=CSS, planes=PLANES, contacto_wa=CONTACTO_WA)

def caja_abierta():
    return q("SELECT * FROM cajas WHERE cajero=? AND estado='ABIERTA'", (session.get('user'),), True)

def vencida(dep_id):
    pagado = q('SELECT 1 FROM mensualidades WHERE deportista_id=? AND mes=?', (dep_id, datetime.now().strftime('%Y-%m')), True)
    return (not pagado) and datetime.now().day > dia_gracia()

# ---------------- Acceso ----------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        slug = request.form.get('club', '').strip().lower(); nombre = request.form.get('username', '').strip()
        clave = (request.remote_addr, slug, nombre.lower())
        if len(INTENTOS) > 5000: INTENTOS.clear()
        fallos = [t for t in INTENTOS.get(clave, []) if time.time() - t < 300]
        if len(fallos) >= 5:
            flash('Demasiados intentos fallidos. Espera 5 minutos.', 'err'); return render_template('login.html', prefill=slug)
        u = None
        if SLUG_RE.match(slug) and pq('SELECT 1 FROM clubes WHERE slug=?', (slug,), True):
            c = db(slug); u = c.execute('SELECT * FROM usuarios WHERE username=? AND COALESCE(activo,1)=1', (nombre,)).fetchone(); c.close()
        if u and check_password_hash(u['password'], request.form.get('password', '')):
            INTENTOS.pop(clave, None); session.clear(); session.permanent = True
            session.update(uid=u['id'], user=u['username'], rol=u['rol'], cambiar=u['cambiar'], club=slug)
            return redirect('/')
        INTENTOS[clave] = fallos + [time.time()]
        flash('Credenciales incorrectas', 'err')
    return render_template('login.html', prefill=request.args.get('club', ''))

@app.route('/logout')
def logout():
    session.clear(); return redirect('/login')

@app.route('/cuenta', methods=['GET', 'POST'])
@login_required
def cuenta():
    if request.method == 'POST':
        u = q('SELECT * FROM usuarios WHERE id=?', (session['uid'],), True)
        nueva = request.form.get('nueva', '')
        if not check_password_hash(u['password'], request.form.get('actual', '')): flash('La contraseña actual no coincide', 'err')
        elif len(nueva) < 8: flash('La nueva contraseña debe tener mínimo 8 caracteres', 'err')
        else:
            ex('UPDATE usuarios SET password=?, cambiar=0 WHERE id=?', (generate_password_hash(nueva), u['id']))
            session['cambiar'] = 0; flash('Contraseña actualizada', 'ok'); return redirect('/')
    return render_template('cuenta.html')

@app.route('/')
def index():
    if 'uid' not in session or not session.get('club'):
        return render_template('landing.html')
    rol = session.get('rol')
    return redirect('/resumen' if rol == 'admin' else ('/asistencia/facial' if rol == 'kiosco' else '/asistencia'))

# ---------------- Deportistas ----------------
def cats_permitidas():
    if session.get('rol') in ('admin', 'kiosco'): return list(CATEGORIAS)
    mias = {r['categoria'] for r in q('SELECT categoria FROM usuario_categorias WHERE usuario_id=?', (session.get('uid'),))}
    return [c for c in CATEGORIAS if c in mias]

def dep_permitido(did):
    d = q('SELECT * FROM deportistas WHERE id=?', (did,), True) or abort(404)
    if d['categoria'] not in cats_permitidas(): abort(403)
    return d

def marcadores(lista):
    return ','.join('?' * len(lista))

def num_wa(cel):
    c = ''.join(ch for ch in (cel or '') if ch.isdigit())
    return '57' + c if len(c) == 10 else c

def encolar(tipo, did, texto, celular, slug=None):
    cel = num_wa(celular)
    if len(cel) < 11: return False
    ex('INSERT INTO avisos(tipo,deportista_id,celular,texto) VALUES(?,?,?,?)', (tipo, did, cel, texto[:900]), slug=slug)
    return True

def avisar_llegada(d, cuando=None):
    if ajuste('wa_llegada', '1') != '1' or not d['acepta_whatsapp'] or not d['acudiente_celular']: return
    hora = (cuando or datetime.now()).strftime('%H:%M')
    encolar('LLEGADA', d['id'], f"✅ {d['nombre']} llegó al entrenamiento a las {hora}.", d['acudiente_celular'])

@app.route('/deportistas')
@login_required
def deportistas():
    cats = cats_permitidas(); t = request.args.get('q', '').strip(); toks = norm(t).split()
    rows = q(f'SELECT d.*, (SELECT COUNT(*) FROM rostros r WHERE r.deportista_id=d.id) rostros FROM deportistas d WHERE categoria IN ({marcadores(cats)}) ORDER BY activo DESC, categoria, nombre', cats)
    rows = [r for r in rows if all(x in norm(r['nombre'] + ' ' + (r['documento'] or '')) for x in toks)]
    e = dep_permitido(request.args['edit']) if request.args.get('edit') else None
    return render_template('deportistas.html', rows=rows, e=dict(e) if e else {}, t=t, categorias=cats)

@app.post('/deportistas/guardar')
@login_required
def deportista_guardar():
    f = request.form; ident = f.get('id') or ''; cats = cats_permitidas()
    nombre = ' '.join(f.get('nombre', '').split()); cat = f.get('categoria'); rol = f.get('rol_deportivo') or ROLES[0]
    if len(nombre) < 3 or cat not in cats or rol not in ROLES:
        flash('Escribe el nombre y elige una de tus categorías', 'err'); return redirect('/deportistas')
    if ident: dep_permitido(ident)
    if any(norm(r['nombre']) == norm(nombre) and str(r['id']) != ident for r in q('SELECT id, nombre FROM deportistas WHERE categoria=?', (cat,))):
        flash('Ya hay alguien con ese nombre en la categoría. Agrega el segundo apellido o una inicial para diferenciarlos.', 'err'); return redirect('/deportistas')
    doc = f.get('documento', '').strip()
    resto = [f.get('acudiente_nombre', '').strip(), f.get('acudiente_celular', '').strip(), f.get('contacto_emergencia', '').strip()]
    try:
        if ident:
            ex("UPDATE deportistas SET documento=COALESCE(NULLIF(?,''), documento), nombre=?, categoria=?, rol_deportivo=?, acudiente_nombre=?, acudiente_celular=?, contacto_emergencia=? WHERE id=?", [doc, nombre, cat, rol] + resto + [ident])
            did = int(ident)
        else:
            did = ex('INSERT INTO deportistas(documento,nombre,categoria,rol_deportivo,acudiente_nombre,acudiente_celular,contacto_emergencia) VALUES(?,?,?,?,?,?,?)', [doc or 'tmp' + secrets.token_hex(4), nombre, cat, rol] + resto)
            if not doc: ex('UPDATE deportistas SET documento=? WHERE id=?', (f'SD-{did:05d}', did))
            if ajuste('cloud', '0') == '1': empujar_deportista(g.club, q('SELECT * FROM deportistas WHERE id=?', (did,), True))
        flash(f'{nombre} guardado', 'ok')
    except sqlite3.IntegrityError:
        flash('Ese documento ya está registrado en otro deportista', 'err'); return redirect('/deportistas')
    return redirect(f'/deportistas/{did}/rostro' if f.get('siguiente') == 'rostro' else (f'/deportistas/{did}/ficha' if f.get('siguiente') == 'ficha' else '/deportistas'))

@app.route('/api/deportistas/buscar')
@login_required
def api_buscar():
    toks = norm(request.args.get('q', '')).split(); cats = cats_permitidas()
    if not toks: return jsonify([])
    rows = q(f"""SELECT d.id, d.nombre, d.categoria, (SELECT 1 FROM asistencias a WHERE a.deportista_id=d.id AND date(a.fecha)=date('now','localtime')) presente
                FROM deportistas d WHERE d.activo=1 AND d.categoria IN ({marcadores(cats)}) ORDER BY d.nombre""", cats)
    out = [dict(id=r['id'], nombre=r['nombre'], categoria=r['categoria'], presente=bool(r['presente'])) for r in rows if all(t in norm(r['nombre']) for t in toks)]
    return jsonify(out[:8])

@app.post('/deportistas/<int:i>/estado')
@admin_required
def deportista_estado(i):
    ex('UPDATE deportistas SET activo=1-activo WHERE id=?', (i,)); return redirect('/deportistas')

# ---------------- Asistencia ----------------
@app.route('/asistencia')
@login_required
def asistencia():
    cats = cats_permitidas(); cat = request.args.get('cat') if request.args.get('cat') in cats else (cats[0] if cats else None)
    mes = datetime.now().strftime('%Y-%m'); rows = []
    if cat:
        rows = q("""SELECT d.*, (SELECT 1 FROM asistencias a WHERE a.deportista_id=d.id AND date(a.fecha)=date('now','localtime')) presente,
                    (SELECT 1 FROM mensualidades m WHERE m.deportista_id=d.id AND m.mes=?) pagado
                    FROM deportistas d WHERE d.activo=1 AND d.categoria=? ORDER BY d.nombre""", (mes, cat))
    hoy = q(f"""SELECT d.id, d.nombre, d.categoria, a.fecha, a.metodo FROM asistencias a JOIN deportistas d ON d.id=a.deportista_id
               WHERE date(a.fecha)=date('now','localtime') AND d.categoria IN ({marcadores(cats)}) ORDER BY a.fecha DESC LIMIT 15""", cats)
    hoy = [dict(dict(r), pend=vencida(r['id'])) for r in hoy]
    return render_template('asistencia.html', cat=cat, rows=rows, hoy=hoy, gracia=datetime.now().day > dia_gracia(), categorias=cats)

@app.post('/asistencia/marcar')
@login_required
def asistencia_marcar():
    f = request.form
    if f.get('id'): d = q('SELECT * FROM deportistas WHERE id=? AND activo=1', (f['id'],), True)
    else: d = q('SELECT * FROM deportistas WHERE documento=? AND activo=1', (f.get('documento', '').strip(),), True)
    destino = '/asistencia?cat=' + urllib.parse.quote(f.get('cat') or (d['categoria'] if d else ''))
    if not d or d['categoria'] not in cats_permitidas():
        flash('Deportista no encontrado en tus categorías', 'err'); return redirect(destino)
    try:
        ex('INSERT INTO asistencias(deportista_id, entrenador, metodo) VALUES(?,?,?)', (d['id'], session['user'], 'MANUAL'))
        flash(f"Asistencia registrada: {d['nombre']} ({d['categoria']})", 'ok'); avisar_llegada(d)
        if vencida(d['id']): flash(f"Aviso administrativo: {d['nombre']} tiene la mensualidad pendiente", 'warn')
    except sqlite3.IntegrityError:
        flash(f"{d['nombre']} ya tiene asistencia registrada hoy", 'err')
    return redirect(destino)

# ---------------- Cobros y tienda ----------------
@app.route('/cobros')
@login_required
def cobros():
    deps = q('SELECT id, nombre, categoria FROM deportistas WHERE activo=1 ORDER BY nombre')
    prods = q('SELECT * FROM productos WHERE activo=1 AND stock>0 ORDER BY producto, talla')
    ult = q("""SELECT d.nombre, m.mes, m.monto, m.medio_pago, m.fecha FROM mensualidades m JOIN deportistas d ON d.id=m.deportista_id
               ORDER BY m.id DESC LIMIT 8""")
    return render_template('cobros.html', deps=deps, prods=prods, ult=ult, caja=caja_abierta(), tarifas=tarifas(),
                           mes=datetime.now().strftime('%Y-%m'), sugerida=MENSUALIDAD_SUGERIDA)

@app.post('/cobros/mensualidad')
@login_required
def cobro_mensualidad():
    caja = caja_abierta(); f = request.form
    if not caja: flash('Abre caja antes de cobrar', 'err'); return redirect('/caja')
    try:
        monto = num(f.get('monto')); mes = f.get('mes', '')
        datetime.strptime(mes, '%Y-%m')
        if monto <= 0 or f.get('medio') not in MEDIOS or not f.get('deportista_id'): raise ValueError('Datos de cobro incompletos')
        ex('INSERT INTO mensualidades(deportista_id,mes,monto,medio_pago,caja_id,cajero) VALUES(?,?,?,?,?,?)',
           (f['deportista_id'], mes, monto, f['medio'], caja['id'], session['user']))
        flash('Mensualidad registrada', 'ok')
    except sqlite3.IntegrityError: flash('Esa mensualidad ya fue pagada', 'err')
    except ValueError as e: flash(str(e), 'err')
    return redirect('/cobros')

@app.post('/cobros/venta')
@login_required
def cobro_venta():
    caja = caja_abierta(); f = request.form
    if not caja: flash('Abre caja antes de vender', 'err'); return redirect('/caja')
    items = [(int(k[4:]), int(v)) for k, v in f.items() if k.startswith('qty_') and v.isdigit() and int(v) > 0]
    if not items or f.get('medio') not in MEDIOS: flash('Selecciona productos y medio de pago', 'err'); return redirect('/cobros')
    c = db(); vid = None
    try:
        c.execute('BEGIN IMMEDIATE'); total = 0; filas = []
        for pid, qty in items:
            p = c.execute('SELECT * FROM productos WHERE id=? AND activo=1', (pid,)).fetchone()
            if not p or p['stock'] < qty: raise ValueError('Stock insuficiente: ' + (p['producto'] if p else str(pid)))
            total += p['precio'] * qty; filas.append((p, qty))
        vid = c.execute('INSERT INTO ventas(deportista_id,total,metodo_pago,caja_id,cajero) VALUES(?,?,?,?,?)',
                        (f.get('deportista_id') or None, total, f['medio'], caja['id'], session['user'])).lastrowid
        for p, qty in filas:
            c.execute('INSERT INTO venta_items(venta_id,producto_id,descripcion,cantidad,precio) VALUES(?,?,?,?,?)',
                      (vid, p['id'], p['producto'] + (f" T.{p['talla']}" if p['talla'] else ''), qty, p['precio']))
            c.execute('UPDATE productos SET stock=stock-? WHERE id=?', (qty, p['id']))
        c.execute('COMMIT')
    except ValueError as e:
        c.execute('ROLLBACK'); flash(str(e), 'err'); return redirect('/cobros')
    finally:
        c.close()
    return redirect(f'/ticket/{vid}')

@app.route('/ticket/<int:vid>')
@login_required
def ticket(vid):
    v = q('SELECT * FROM ventas WHERE id=?', (vid,), True) or abort(404)
    return render_template('ticket.html', v=v, items=q('SELECT * FROM venta_items WHERE venta_id=?', (vid,)))

# ---------------- Inventario ----------------
@app.route('/inventario')
@login_required
def inventario():
    rows = q('SELECT * FROM productos ORDER BY activo DESC, producto, talla')
    e = q('SELECT * FROM productos WHERE id=?', (request.args.get('edit'),), True) if request.args.get('edit') else None
    return render_template('inventario.html', rows=rows, e=dict(e) if e else {})

@app.post('/inventario/guardar')
@admin_required
def inventario_guardar():
    f = request.form
    try:
        codigo, nombre = f.get('codigo', '').strip(), f.get('producto', '').strip()
        costo, precio, agregar = num(f.get('costo')), num(f.get('precio')), int(f.get('agregar') or 0)
        minimo = int(f.get('stock_minimo') or 5)
        if not codigo or not nombre: raise ValueError('Código y nombre son obligatorios')
        ya = q('SELECT id, stock FROM productos WHERE codigo=?', (codigo,), True)
        if ya:
            if ya['stock'] + agregar < 0: raise ValueError('El ajuste dejaría el stock en negativo')
            ex('UPDATE productos SET producto=?,talla=?,costo=?,precio=?,stock=stock+?,stock_minimo=? WHERE id=?', (nombre, f.get('talla', '').strip(), costo, precio, agregar, minimo, ya['id']))
        else:
            if agregar < 0: raise ValueError('El stock inicial no puede ser negativo')
            ex('INSERT INTO productos(codigo,producto,talla,costo,precio,stock,stock_minimo) VALUES(?,?,?,?,?,?,?)', (codigo, nombre, f.get('talla', '').strip(), costo, precio, agregar, minimo))
        flash('Producto guardado', 'ok')
    except ValueError as e: flash(str(e), 'err')
    return redirect('/inventario')

@app.post('/inventario/<int:i>/estado')
@admin_required
def inventario_estado(i):
    ex('UPDATE productos SET activo=1-activo WHERE id=?', (i,)); return redirect('/inventario')

# ---------------- Caja ciega y arqueo ----------------
def resumen_caja(cid):
    caja = q('SELECT * FROM cajas WHERE id=?', (cid,), True)
    por = {r['m']: r['t'] for r in q("""SELECT m, SUM(t) t FROM (SELECT medio_pago m, monto t FROM mensualidades WHERE caja_id=?
                                        UNION ALL SELECT metodo_pago, total FROM ventas WHERE caja_id=?) GROUP BY m""", (cid, cid))}
    mens = q('SELECT COALESCE(SUM(monto),0) s FROM mensualidades WHERE caja_id=?', (cid,), True)['s']
    tienda = q('SELECT COALESCE(SUM(total),0) s FROM ventas WHERE caja_id=?', (cid,), True)['s']
    egr = q('SELECT COALESCE(SUM(monto),0) s FROM egresos WHERE caja_id=?', (cid,), True)['s']
    return dict(caja=caja, por=por, mens=mens, tienda=tienda, egresos=egr, efectivo=por.get('Efectivo', 0),
                esperado=caja['base'] + por.get('Efectivo', 0) - egr, total=mens + tienda)

@app.route('/caja')
@login_required
def caja():
    abierta = caja_abierta(); res = None; egr = []
    if abierta:
        res = resumen_caja(abierta['id']); egr = q('SELECT * FROM egresos WHERE caja_id=? ORDER BY id DESC', (abierta['id'],))
    hist = q('SELECT * FROM cajas WHERE estado="CERRADA" ' + ('' if session['rol'] == 'admin' else 'AND cajero=? ') + 'ORDER BY id DESC LIMIT 20',
             () if session['rol'] == 'admin' else (session['user'],))
    ver = session['rol'] == 'admin' or not cierre_ciego()
    return render_template('caja.html', abierta=abierta, res=res, egr=egr, hist=hist, ver=ver)

@app.post('/caja/abrir')
@login_required
def caja_abrir():
    try:
        if caja_abierta(): raise ValueError('Ya tienes una caja abierta')
        ex('INSERT INTO cajas(cajero, base) VALUES(?,?)', (session['user'], num(request.form.get('base'))))
        flash('Caja abierta', 'ok')
    except (ValueError, sqlite3.IntegrityError) as e: flash(str(e), 'err')
    return redirect('/caja')

@app.post('/caja/egreso')
@login_required
def caja_egreso():
    c = caja_abierta()
    try:
        if not c: raise ValueError('No hay caja abierta')
        monto, concepto = num(request.form.get('monto')), request.form.get('concepto', '').strip()
        if monto <= 0 or not concepto: raise ValueError('Indica concepto y valor del egreso')
        ex('INSERT INTO egresos(caja_id,concepto,monto) VALUES(?,?,?)', (c['id'], concepto, monto)); flash('Egreso registrado', 'ok')
    except ValueError as e: flash(str(e), 'err')
    return redirect('/caja')

@app.post('/caja/cerrar')
@login_required
def caja_cerrar():
    c = caja_abierta()
    if not c: return redirect('/caja')
    try: contado = num(request.form.get('contado'))
    except ValueError as e: flash(str(e), 'err'); return redirect('/caja')
    esperado = resumen_caja(c['id'])['esperado']
    ex("UPDATE cajas SET cierre=datetime('now','localtime'), contado=?, esperado=?, diferencia=?, estado='CERRADA', notas=? WHERE id=?",
       (contado, esperado, round(contado - esperado, 2), request.form.get('notas', '').strip(), c['id']))
    backup()
    return redirect(f"/caja/{c['id']}")

@app.route('/caja/<int:cid>')
@login_required
def caja_cierre(cid):
    res = resumen_caja(cid)
    if not res['caja'] or (session['rol'] != 'admin' and res['caja']['cajero'] != session['user']): abort(404)
    c = res['caja']; dif = c['diferencia'] or 0
    estado = 'CUADRADA' if abs(dif) < 0.5 else ('SOBRANTE' if dif > 0 else 'FALTANTE')
    club = q('SELECT nombre FROM club', one=True)['nombre']
    L = [f'*CIERRE DE CAJA - {club}*', f"Cajero: {c['cajero']}", f"Apertura: {c['apertura']}", f"Cierre: {c['cierre'] or 'abierta'}", '',
         f"Base inicial: {cop(c['base'])}", f"Mensualidades: {cop(res['mens'])}", f"Tienda: {cop(res['tienda'])}", f"TOTAL VENDIDO: {cop(res['total'])}", '*Por medio de pago*']
    L += [f'- {m}: {cop(v)}' for m, v in res['por'].items()]
    L += ['', f"Egresos: {cop(res['egresos'])}", f"Efectivo esperado: {cop(res['esperado'])}", f"Efectivo contado: {cop(c['contado'])}", f'Diferencia: {cop(dif)} ({estado})']
    if c['notas']: L.append('Notas: ' + c['notas'])
    texto = '\n'.join(L)
    return render_template('caja_cierre.html', res=res, c=c, estado=estado, texto=texto, wa='https://wa.me/?text=' + urllib.parse.quote(texto),
                           egr=q('SELECT * FROM egresos WHERE caja_id=?', (cid,)))

# ---------------- Usuarios (admin) ----------------
@app.route('/usuarios', methods=['GET', 'POST'])
@admin_required
def usuarios():
    if request.method == 'POST':
        f = request.form; nombre = f.get('username', '').strip().lower()
        if not re.fullmatch(r'[a-z0-9]{3,20}', nombre) or len(f.get('password', '')) < 8 or f.get('rol') not in ('admin', 'entrenador', 'kiosco'):
            flash('Usuario (3 a 20 letras o números), rol y contraseña (8+) son obligatorios', 'err')
        else:
            try:
                uid = ex('INSERT INTO usuarios(username,password,rol,cambiar,nombre_completo,celular,cargo) VALUES(?,?,?,?,?,?,?)',
                         (nombre, generate_password_hash(f['password']), f['rol'], 0 if f['rol'] == 'kiosco' else 1, f.get('nombre_completo', '').strip(), f.get('celular', '').strip(), f.get('cargo', '').strip()))
                for cat in f.getlist('cats'):
                    if cat in CATEGORIAS: ex('INSERT OR IGNORE INTO usuario_categorias VALUES(?,?)', (uid, cat))
                flash('Usuario creado', 'ok')
            except sqlite3.IntegrityError: flash('Ese usuario ya existe', 'err')
        return redirect('/usuarios')
    asign = {}
    for r in q('SELECT * FROM usuario_categorias ORDER BY categoria'): asign.setdefault(r['usuario_id'], []).append(r['categoria'])
    return render_template('usuarios.html', rows=q("SELECT id, username, rol, COALESCE(activo,1) activo, nombre_completo, celular, foto, cargo FROM usuarios ORDER BY rol, username"), asign=asign)

@app.post('/usuarios/<int:i>/categorias')
@admin_required
def usuario_categorias(i):
    ex('DELETE FROM usuario_categorias WHERE usuario_id=?', (i,))
    for cat in request.form.getlist('cats'):
        if cat in CATEGORIAS: ex('INSERT OR IGNORE INTO usuario_categorias VALUES(?,?)', (i, cat))
    flash('Categorías actualizadas', 'ok'); return redirect('/usuarios')

@app.post('/usuarios/<int:i>/estado')
@admin_required
def usuario_estado(i):
    if i != session['uid']: ex('UPDATE usuarios SET activo=1-COALESCE(activo,1) WHERE id=?', (i,))
    return redirect('/usuarios')

@app.post('/usuarios/<int:i>/clave')
@admin_required
def usuario_clave(i):
    p = request.form.get('password', '')
    if len(p) < 8: flash('La contraseña debe tener mínimo 8 caracteres', 'err')
    else:
        ex("UPDATE usuarios SET password=?, cambiar=CASE rol WHEN 'kiosco' THEN 0 ELSE 1 END WHERE id=?", (generate_password_hash(p), i)); flash('Contraseña restablecida', 'ok')
    return redirect('/usuarios')

# ---------------- Asistencia facial ----------------
def _vec(v):
    if not isinstance(v, list) or len(v) != 128: raise ValueError('Descriptor facial inválido')
    out = [float(x) for x in v]
    if not all(math.isfinite(x) for x in out): raise ValueError('Descriptor facial inválido')
    return out

def _distancias(v, excluir=None):
    mejor = {}
    for r in q("SELECT r.deportista_id i, r.descriptor s FROM rostros r JOIN deportistas d ON d.id=r.deportista_id WHERE d.activo=1 AND d.consentimiento_biometrico IS NOT NULL"):
        if r['i'] == excluir: continue
        d = math.dist(v, json.loads(r['s']))
        if d < mejor.get(r['i'], 9): mejor[r['i']] = d
    return sorted(mejor.items(), key=lambda x: x[1])

@app.route('/asistencia/facial')
@login_required
def asistencia_facial():
    return render_template('facial.html')

@app.post('/api/facial/identificar')
@login_required
def api_identificar():
    try: v = _vec((request.get_json(silent=True) or {}).get('descriptor'))
    except ValueError as e: return jsonify(estado='error', msg=str(e)), 400
    ranking = _distancias(v)
    if not ranking or ranking[0][1] > UMBRAL_FACIAL: return jsonify(estado='desconocido')
    if len(ranking) > 1 and ranking[1][1] - ranking[0][1] < MARGEN_FACIAL: return jsonify(estado='ambiguo')
    did, dist = ranking[0]; d = q('SELECT * FROM deportistas WHERE id=?', (did,), True)
    try:
        ex('INSERT INTO asistencias(deportista_id, entrenador, metodo, distancia) VALUES(?,?,?,?)', (did, session['user'], 'FACIAL', round(dist, 4))); ya = False
        avisar_llegada(d)
    except sqlite3.IntegrityError: ya = True
    return jsonify(estado='ok', ya=ya, nombre=d['nombre'], categoria=d['categoria'], rol=d['rol_deportivo'], pendiente=(not ya) and vencida(did))

@app.route('/deportistas/<int:i>/rostro')
@login_required
def rostro(i):
    d = dep_permitido(i)
    return render_template('rostro.html', d=d, n=q('SELECT COUNT(*) n FROM rostros WHERE deportista_id=?', (i,), True)['n'], maximo=MAX_ROSTROS)

@app.post('/deportistas/<int:i>/consentimiento')
@login_required
def rostro_consentimiento(i):
    dep_permitido(i); quien = request.form.get('autoriza', '').strip()
    if request.form.get('acepta') == '1' and quien:
        ex('UPDATE deportistas SET consentimiento_biometrico=? WHERE id=?', (f'{datetime.now():%Y-%m-%d %H:%M} | autoriza: {quien} | registró: {session["user"]}', i))
        flash('Autorización registrada', 'ok')
    else: flash('Indica quién autoriza y marca la casilla', 'err')
    return redirect(f'/deportistas/{i}/rostro')

@app.post('/api/facial/enrolar')
@login_required
def api_enrolar():
    j = request.get_json(silent=True) or {}
    if session.get('rol') == 'kiosco': return jsonify(ok=False, msg='Sin permiso'), 403
    try: v = _vec(j.get('descriptor'))
    except ValueError as e: return jsonify(ok=False, msg=str(e)), 400
    d = q('SELECT * FROM deportistas WHERE id=?', (j.get('deportista_id'),), True)
    if not d or d['categoria'] not in cats_permitidas(): return jsonify(ok=False, msg='Deportista no disponible'), 403
    if not d['consentimiento_biometrico']: return jsonify(ok=False, msg='Falta la autorización del acudiente'), 403
    n = q('SELECT COUNT(*) n FROM rostros WHERE deportista_id=?', (d['id'],), True)['n']
    if n >= MAX_ROSTROS: return jsonify(ok=False, msg=f'Ya hay {MAX_ROSTROS} muestras. Elimina los datos para volver a registrar.'), 409
    otros = _distancias(v, excluir=d['id'])
    if otros and otros[0][1] < 0.4:
        otro = q('SELECT nombre FROM deportistas WHERE id=?', (otros[0][0],), True)['nombre']
        return jsonify(ok=False, msg=f'Este rostro se parece demasiado al de {otro}. Verifica a quién estás registrando.'), 409
    ex('INSERT INTO rostros(deportista_id, descriptor) VALUES(?,?)', (d['id'], json.dumps(v)))
    return jsonify(ok=True, total=n + 1)

@app.post('/deportistas/<int:i>/rostro/borrar')
@admin_required
def rostro_borrar(i):
    ex('DELETE FROM rostros WHERE deportista_id=?', (i,)); ex('UPDATE deportistas SET consentimiento_biometrico=NULL WHERE id=?', (i,))
    flash('Datos biométricos eliminados', 'ok'); return redirect(f'/deportistas/{i}/rostro')

# ---------------- App instalable (PWA) ----------------
SW_JS = """const C='trazelio-v3',P=C+'-p',PAGINAS=['/asistencia','/asistencia/facial'];
self.addEventListener('install',e=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x!==C&&x!==P).map(x=>caches.delete(x)))).then(()=>clients.claim())));
self.addEventListener('fetch',e=>{const u=new URL(e.request.url);
 if(e.request.method!=='GET'||u.origin!==location.origin)return;
 if(u.pathname.startsWith('/static/')){e.respondWith(caches.open(C).then(async c=>{const h=await c.match(e.request);if(h)return h;const r=await fetch(e.request);if(r.ok)c.put(e.request,r.clone());return r;}));return}
 if(e.request.mode==='navigate'){e.respondWith(fetch(e.request).then(r=>{if(r.ok&&!r.redirected&&PAGINAS.includes(u.pathname)){const k=r.clone();caches.open(P).then(c=>c.put(e.request,k))}return r}).catch(async()=>(await caches.match(e.request))||new Response('<h2 style="font-family:sans-serif;padding:24px">Sin conexión. Reintenta cuando vuelva el internet.</h2>',{headers:{'Content-Type':'text/html;charset=utf-8'}})))}
});"""

@app.route('/manifest.json')
def manifest():
    return jsonify(name='Trazelio Sport', short_name='Trazelio', start_url='/', scope='/', display='standalone', background_color='#12263F', theme_color='#0F5132',
                   icons=[{'src': '/static/icon-192.png', 'sizes': '192x192', 'type': 'image/png'}, {'src': '/static/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any maskable'}])

@app.route('/sw.js')
def sw():
    return Response(SW_JS, mimetype='application/javascript', headers={'Cache-Control': 'no-cache'})

# ---------------- Configuración, tarifas y WhatsApp (admin) ----------------
@app.route('/configuracion', methods=['GET', 'POST'])
@admin_required
def configuracion():
    if request.method == 'POST':
        f = request.form
        try:
            nombre = f.get('nombre', '').strip() or 'Club Deportivo'
            ex('UPDATE club SET nombre=?, nit=?, telefono=? WHERE id=1', (nombre, f.get('nit', '').strip(), f.get('telefono', '').strip()))
            pex('UPDATE clubes SET nombre=? WHERE slug=?', (nombre, g.club))
            guardar = lambda k, v: ex('INSERT OR REPLACE INTO ajustes(clave,valor) VALUES(?,?)', (k, str(v)))
            guardar('dia_gracia', min(max(int(f.get('dia_gracia') or 5), 0), 28)); guardar('cierre_ciego', '1' if f.get('cierre_ciego') else '0')
            guardar('wa_modo', 'api' if f.get('wa_modo') == 'api' else 'manual'); guardar('wa_phone_id', f.get('wa_phone_id', '').strip())
            guardar('wa_plantilla', f.get('wa_plantilla', '').strip()); guardar('wa_idioma', f.get('wa_idioma', '').strip() or 'es'); guardar('wa_version', f.get('wa_version', '').strip() or 'v26.0')
            if f.get('wa_token', '').strip(): guardar('wa_token', f['wa_token'].strip())
            guardar('wa_llegada', '1' if f.get('wa_llegada') else '0'); guardar('wa_recordatorios', '1' if f.get('wa_recordatorios') else '0')
            for i, cat in enumerate(CATEGORIAS):
                v = f.get(f'tarifa_{i}', '').strip()
                if v: ex('INSERT OR REPLACE INTO tarifas(categoria,monto) VALUES(?,?)', (cat, num(v)))
                else: ex('DELETE FROM tarifas WHERE categoria=?', (cat,))
            flash('Configuración guardada', 'ok')
        except ValueError:
            flash('Revisa los valores numéricos', 'err')
        return redirect('/configuracion')
    t = tarifas()
    wa = dict(modo=ajuste('wa_modo', 'manual'), phone_id=ajuste('wa_phone_id', ''), plantilla=ajuste('wa_plantilla', ''), idioma=ajuste('wa_idioma', 'es'), version=ajuste('wa_version', 'v26.0'),
              tiene_token=bool(ajuste('wa_token', '')), llegada=ajuste('wa_llegada', '1') == '1', recordatorios=ajuste('wa_recordatorios', '1') == '1')
    return render_template('config.html', filas=[(i, c, t.get(c)) for i, c in enumerate(CATEGORIAS)], dia=dia_gracia(), ciego=cierre_ciego(), wa=wa)

# ---------------- Fotos ----------------
def dir_fotos():
    d = os.path.join(os.path.dirname(ruta_club()), 'fotos'); os.makedirs(d, exist_ok=True); return d

def guardar_foto(archivo):
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 40_000_000
    try: img = ImageOps.exif_transpose(Image.open(archivo.stream)).convert('RGB')
    except Exception: raise ValueError('La imagen no es válida. Usa una foto JPG o PNG.')
    nombre = secrets.token_hex(12) + '.webp'
    ImageOps.fit(img, (480, 480), method=Image.LANCZOS).save(os.path.join(dir_fotos(), nombre), 'WEBP', quality=82)
    return nombre

def borrar_foto(nombre):
    if nombre and re.fullmatch(r'[0-9a-f]{24}\.webp', nombre):
        try: os.remove(os.path.join(dir_fotos(), nombre))
        except OSError: pass

def enviar_foto(nombre):
    if not nombre or not re.fullmatch(r'[0-9a-f]{24}\.webp', nombre): abort(404)
    ruta = os.path.join(dir_fotos(), nombre)
    if not os.path.exists(ruta): abort(404)
    r = send_file(ruta, mimetype='image/webp'); r.headers['Cache-Control'] = 'private, max-age=3600'; return r

@app.route('/foto/<archivo>')
@login_required
def foto(archivo):
    return enviar_foto(archivo)

# ---------------- Perfiles ----------------
POSICIONES = ['Portero', 'Defensa', 'Volante', 'Delantero']
PIES = ['Derecho', 'Izquierdo', 'Ambos']

@app.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    u = q('SELECT * FROM usuarios WHERE id=?', (session['uid'],), True)
    if request.method == 'POST':
        f = request.form
        try:
            ex('UPDATE usuarios SET nombre_completo=?, celular=?, email=?, cargo=? WHERE id=?', (f.get('nombre_completo', '').strip()[:80], f.get('celular', '').strip()[:20], f.get('email', '').strip()[:80], f.get('cargo', '').strip()[:40], u['id']))
            a = request.files.get('foto')
            if a and a.filename:
                nueva = guardar_foto(a); borrar_foto(u['foto']); ex('UPDATE usuarios SET foto=? WHERE id=?', (nueva, u['id']))
            flash('Perfil actualizado', 'ok')
        except ValueError as e: flash(str(e), 'err')
        return redirect('/perfil')
    return render_template('perfil.html', u=u, cats=cats_permitidas() if u['rol'] == 'entrenador' else [])

def _fecha(s):
    s = (s or '').strip()
    if not s: return None
    return datetime.strptime(s, '%Y-%m-%d').date().isoformat()

def _opt(v, lo, hi, nombre):
    v = (v or '').strip()
    if not v: return None
    try: n = int(v)
    except ValueError: raise ValueError(f'{nombre} inválido')
    if not lo <= n <= hi: raise ValueError(f'{nombre} debe estar entre {lo} y {hi}')
    return n

@app.route('/deportistas/<int:i>/ficha', methods=['GET', 'POST'])
@login_required
def ficha(i):
    d = dep_permitido(i)
    if request.method == 'POST':
        f = request.form
        try:
            dorsal = _opt(f.get('dorsal'), 1, 99, 'El dorsal')
            if dorsal and q('SELECT 1 FROM deportistas WHERE categoria=? AND dorsal=? AND id<>? AND activo=1', (d['categoria'], dorsal, i), True): raise ValueError('Ese dorsal ya lo tiene otro jugador de la categoría')
            pos = f.get('posicion') if f.get('posicion') in POSICIONES else None; pie = f.get('pie') if f.get('pie') in PIES else None
            try: nac = _fecha(f.get('fecha_nacimiento'))
            except ValueError: raise ValueError('Fecha de nacimiento inválida')
            ex('UPDATE deportistas SET fecha_nacimiento=?, posicion=?, dorsal=?, pie=?, estatura=?, peso=?, apodo=?, lema=?, acepta_whatsapp=? WHERE id=?',
               (nac, pos, dorsal, pie, _opt(f.get('estatura'), 60, 230, 'La estatura'), _opt(f.get('peso'), 10, 200, 'El peso'), f.get('apodo', '').strip()[:20], f.get('lema', '').strip()[:60], 1 if f.get('acepta_whatsapp') else 0, i))
            a = request.files.get('foto')
            if a and a.filename:
                nueva = guardar_foto(a); borrar_foto(d['foto']); ex('UPDATE deportistas SET foto=? WHERE id=?', (nueva, i))
            flash('Ficha guardada', 'ok')
        except ValueError as e: flash(str(e), 'err')
        return redirect(f'/deportistas/{i}/ficha')
    edad = None
    if d['fecha_nacimiento']:
        n = date.fromisoformat(d['fecha_nacimiento']); h = date.today(); edad = h.year - n.year - ((h.month, h.day) < (n.month, n.day))
    return render_template('ficha.html', d=d, posiciones=POSICIONES, pies=PIES, edad=edad)

@app.post('/deportistas/<int:i>/foto/<accion>')
@login_required
def foto_revision(i, accion):
    d = dep_permitido(i)
    if d['foto_pendiente'] and accion == 'aprobar':
        borrar_foto(d['foto']); ex('UPDATE deportistas SET foto=foto_pendiente, foto_pendiente=NULL WHERE id=?', (i,)); flash('Foto aprobada', 'ok')
    elif d['foto_pendiente'] and accion == 'rechazar':
        borrar_foto(d['foto_pendiente']); ex('UPDATE deportistas SET foto_pendiente=NULL WHERE id=?', (i,)); flash('Foto rechazada', 'ok')
    return redirect(f'/deportistas/{i}/ficha')

@app.route('/organigrama')
@admin_required
def organigrama():
    ramas = []
    for c in CATEGORIAS:
        ent = q("SELECT u.* FROM usuarios u JOIN usuario_categorias uc ON uc.usuario_id=u.id WHERE uc.categoria=? AND COALESCE(u.activo,1)=1 ORDER BY u.nombre_completo, u.username", (c,))
        n = q('SELECT COUNT(*) n FROM deportistas WHERE categoria=? AND activo=1', (c,), True)['n']
        ramas.append((c, ent, n))
    return render_template('organigrama.html', ramas=ramas, admins=q("SELECT * FROM usuarios WHERE rol='admin' AND COALESCE(activo,1)=1"), kioscos=q("SELECT * FROM usuarios WHERE rol='kiosco' AND COALESCE(activo,1)=1"))

# ---------------- Eventos y estadísticas ----------------
def _int(v, lo, hi):
    try: n = int(str(v or '').strip() or 0)
    except ValueError: raise ValueError('Hay valores numéricos inválidos')
    if not lo <= n <= hi: raise ValueError(f'Los valores deben estar entre {lo} y {hi}')
    return n

def evento_permitido(eid):
    e = q('SELECT * FROM eventos WHERE id=?', (eid,), True) or abort(404)
    if e['categoria'] not in cats_permitidas(): abort(403)
    return e

@app.route('/eventos')
@login_required
def eventos():
    cats = cats_permitidas()
    rows = q(f'SELECT e.*, (SELECT COUNT(*) FROM estadisticas s WHERE s.evento_id=e.id) n FROM eventos e WHERE categoria IN ({marcadores(cats)}) ORDER BY fecha DESC, id DESC LIMIT 60', cats)
    return render_template('eventos.html', rows=rows, categorias=cats, hoy=date.today().isoformat())

@app.post('/eventos/crear')
@login_required
def evento_crear():
    f = request.form
    try:
        fecha = datetime.strptime(f.get('fecha', ''), '%Y-%m-%d').date().isoformat()
        if f.get('tipo') not in ('PARTIDO', 'ENTRENO') or f.get('categoria') not in cats_permitidas(): raise ValueError('x')
    except ValueError:
        flash('Elige tipo, fecha y una de tus categorías', 'err'); return redirect('/eventos')
    eid = ex('INSERT INTO eventos(tipo,fecha,categoria,rival,lugar,creado_por) VALUES(?,?,?,?,?,?)', (f['tipo'], fecha, f['categoria'], f.get('rival', '').strip()[:60], f.get('lugar', '').strip()[:60], session['user']))
    return redirect(f'/eventos/{eid}')

@app.route('/eventos/<int:eid>')
@login_required
def evento(eid):
    e = evento_permitido(eid)
    deps = q("SELECT d.id, d.nombre, d.posicion, d.dorsal, d.foto, d.rol_deportivo, (SELECT 1 FROM asistencias a WHERE a.deportista_id=d.id AND date(a.fecha)=?) presente FROM deportistas d WHERE d.activo=1 AND d.categoria=? ORDER BY d.nombre", (e['fecha'], e['categoria']))
    st = {r['deportista_id']: dict(r) for r in q('SELECT * FROM estadisticas WHERE evento_id=?', (eid,))}
    return render_template('evento.html', e=e, deps=deps, st=st)

@app.post('/eventos/<int:eid>/guardar')
@login_required
def evento_guardar(eid):
    e = evento_permitido(eid); f = request.form; partido = e['tipo'] == 'PARTIDO'
    deps = q('SELECT * FROM deportistas WHERE activo=1 AND categoria=?', (e['categoria'],))
    previos = {r['deportista_id'] for r in q('SELECT deportista_id FROM estadisticas WHERE evento_id=?', (eid,))}
    try:
        gf = (_int(f.get('goles_favor'), 0, 99) if f.get('goles_favor', '').strip() else None) if 'goles_favor' in f else e['goles_favor']
        gc = (_int(f.get('goles_contra'), 0, 99) if f.get('goles_contra', '').strip() else None) if 'goles_contra' in f else e['goles_contra']
        filas = []
        for d in deps:
            k = str(d['id'])
            if not f.get('jugo_' + k): continue
            filas.append(dict(did=d['id'], min=_int(f.get('min_' + k), 0, 150) if partido else 0, gol=_int(f.get('gol_' + k), 0, 30) if partido else 0, ast=_int(f.get('ast_' + k), 0, 30) if partido else 0,
                              ama=_int(f.get('ama_' + k), 0, 2) if partido else 0, roj=_int(f.get('roj_' + k), 0, 1) if partido else 0, ata=_int(f.get('ata_' + k), 0, 60) if partido else 0,
                              cal=_int(f.get('cal_' + k), 0, 10), act=_int(f.get('act_' + k), 0, 5), com=' '.join(f.get('com_' + k, '').split())[:140]))
        total = sum(x['gol'] for x in filas)
        if gf is not None and total > gf: raise ValueError(f'Los goles de los jugadores ({total}) superan los goles del equipo ({gf})')
    except ValueError as err:
        flash(str(err), 'err'); return redirect(f'/eventos/{eid}')
    c = db()
    try:
        c.execute('BEGIN')
        c.execute('UPDATE eventos SET rival=?, lugar=?, goles_favor=?, goles_contra=?, notas=? WHERE id=?', (f.get('rival', e['rival'] or '').strip()[:60], f.get('lugar', e['lugar'] or '').strip()[:60], gf, gc, f.get('notas', e['notas'] or '').strip()[:200], eid))
        ids = [x['did'] for x in filas]
        c.execute(f'DELETE FROM estadisticas WHERE evento_id=? AND deportista_id NOT IN ({marcadores(ids)})', [eid] + ids)
        for x in filas:
            c.execute("""INSERT INTO estadisticas(evento_id,deportista_id,jugo,minutos,goles,asistencias,amarillas,rojas,atajadas,calificacion,actitud,comentario) VALUES(?,?,1,?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(evento_id,deportista_id) DO UPDATE SET minutos=excluded.minutos, goles=excluded.goles, asistencias=excluded.asistencias, amarillas=excluded.amarillas, rojas=excluded.rojas,
                         atajadas=excluded.atajadas, calificacion=excluded.calificacion, actitud=excluded.actitud, comentario=excluded.comentario""",
                      (eid, x['did'], x['min'], x['gol'], x['ast'], x['ama'], x['roj'], x['ata'], x['cal'], x['act'], x['com']))
        c.execute('COMMIT')
    except Exception:
        c.execute('ROLLBACK'); raise
    finally:
        c.close()
    avisados = 0
    if f.get('avisar'):
        etiqueta = (f"partido vs {e['rival']}" if e['rival'] else 'partido') if partido else 'entrenamiento'
        dd = date.fromisoformat(e['fecha']); etiqueta += f' del {dd.day:02d}/{dd.month:02d}'
        for d in deps:
            if d['id'] in previos or d['id'] not in {x['did'] for x in filas} or not d['acepta_whatsapp'] or not d['acudiente_celular']: continue
            url = request.host_url.rstrip('/') + f"/p/{g.club}/{token_de(d['id'])}"
            avisados += encolar('ESTADISTICAS', d['id'], f"⚽ Ya están las estadísticas de {d['nombre']} ({etiqueta}). Míralas aquí: {url}", d['acudiente_celular'])
    flash(f'Estadísticas guardadas ({len(filas)} jugadores' + (f', {avisados} avisos en cola)' if avisados else ')'), 'ok')
    return redirect(f'/eventos/{eid}')

@app.post('/eventos/<int:eid>/eliminar')
@admin_required
def evento_eliminar(eid):
    ex('DELETE FROM eventos WHERE id=?', (eid,)); flash('Evento eliminado', 'ok'); return redirect('/eventos')

NIVELES = [(0, 'Cantera', '🌱'), (100, 'Promesa', '⭐'), (300, 'Titular', '🔥'), (600, 'Estrella', '💫'), (1000, 'Leyenda', '👑')]

def tarjeta(did):
    d = q('SELECT * FROM deportistas WHERE id=?', (did,), True)
    ev = q("""SELECT e.tipo, e.fecha, e.rival, e.goles_favor gf, e.goles_contra gc, s.* FROM estadisticas s JOIN eventos e ON e.id=s.evento_id
              WHERE s.deportista_id=? ORDER BY e.fecha DESC, e.id DESC""", (did,))
    par = [r for r in ev if r['tipo'] == 'PARTIDO']; suma = lambda k: sum(r[k] or 0 for r in par)
    goles, asis, amar, rojas, minutos, atajadas = suma('goles'), suma('asistencias'), suma('amarillas'), suma('rojas'), suma('minutos'), suma('atajadas')
    cal = [r['calificacion'] for r in par if r['calificacion']]; act = [r['actitud'] for r in ev if r['actitud']]
    mias = {r['dia'] for r in q('SELECT DISTINCT date(fecha) dia FROM asistencias WHERE deportista_id=?', (did,))}
    ses = [r['dia'] for r in q("SELECT DISTINCT date(a.fecha) dia FROM asistencias a JOIN deportistas x ON x.id=a.deportista_id WHERE x.categoria=? AND date(a.fecha)>=date('now','localtime','-90 day') ORDER BY dia DESC", (d['categoria'],))]
    racha = 0
    for dia in ses:
        if dia in mias: racha += 1
        else: break
    pct = round(100 * sum(1 for x in ses if x in mias) / len(ses)) if ses else None
    xp = len(mias) * 10 + len(par) * 20 + goles * 15 + asis * 10 + (50 if racha >= 5 else 0)
    idx = max(i for i, n in enumerate(NIVELES) if xp >= n[0]); nivel = NIVELES[idx]; sig = NIVELES[idx + 1] if idx + 1 < len(NIVELES) else None
    logros = [('⚽', 'Primer gol', 'Marca tu primer gol', goles >= 1), ('🎯', 'Goleador', 'Llega a 5 goles', goles >= 5), ('🅰️', 'Asistidor', '3 pases de gol', asis >= 3),
              ('🏟️', 'Debutante', 'Juega tu primer partido', len(par) >= 1), ('🔥', 'Racha de 3', '3 entrenos seguidos', racha >= 3), ('🚀', 'Racha de 5', '5 entrenos seguidos', racha >= 5),
              ('📅', 'Constante', '90% de asistencia', pct is not None and pct >= 90 and len(ses) >= 8), ('🤝', 'Juego limpio', '5 partidos sin tarjetas', sum(1 for r in par if not r['amarillas'] and not r['rojas']) >= 5),
              ('🌟', 'Gran partido', 'Calificación de 9 o más', any((r['calificacion'] or 0) >= 9 for r in par)), ('💪', 'Actitud de crack', 'Actitud promedio de 4,5 o más', len(act) >= 3 and sum(act) / len(act) >= 4.5),
              ('🧤', 'Muro', '10 atajadas', atajadas >= 10)]
    reciente = []
    for r in ev[:6]:
        res = None if r['gf'] is None or r['gc'] is None else ('G' if r['gf'] > r['gc'] else ('P' if r['gf'] < r['gc'] else 'E'))
        reciente.append(dict(tipo=r['tipo'], fecha=r['fecha'], rival=r['rival'], gf=r['gf'], gc=r['gc'], res=res, goles=r['goles'], asist=r['asistencias'], cal=r['calificacion'], act=r['actitud'], com=r['comentario']))
    return dict(goles=goles, asist=asis, amarillas=amar, rojas=rojas, minutos=minutos, atajadas=atajadas, partidos=len(par), entrenos=len(mias), racha=racha, pct=pct,
                cal=round(sum(cal) / len(cal), 1) if cal else None, act=round(sum(act) / len(act), 1) if act else None, xp=xp, nivel=nivel, idx=idx, sig=sig,
                pct_nivel=100 if not sig else int(100 * (xp - nivel[0]) / (sig[0] - nivel[0])), logros=[dict(emoji=a, nombre=b, desc=c, ok=o) for a, b, c, o in logros],
                n_logros=sum(1 for x in logros if x[3]), reciente=reciente)

# ---------------- Enlaces privados: acudiente y jugador ----------------
def token_de(i, col='token_acudiente'):
    if col not in ('token_acudiente', 'token_jugador'): raise ValueError('columna')
    r = q(f'SELECT {col} t FROM deportistas WHERE id=?', (i,), True)
    if r and not r['t']:
        t = secrets.token_urlsafe(24); ex(f'UPDATE deportistas SET {col}=? WHERE id=?', (t, i)); return t
    return r['t'] if r else None

@app.route('/deportistas/<int:i>/enlace', methods=['GET', 'POST'])
@login_required
def enlace(i):
    d = dep_permitido(i)
    if request.method == 'POST':
        ex('UPDATE deportistas SET token_acudiente=NULL, token_jugador=NULL WHERE id=?', (i,)); flash('Los enlaces anteriores quedaron desactivados', 'ok')
    base = request.host_url.rstrip('/'); club = q('SELECT nombre FROM club', one=True)['nombre']
    url_a = f"{base}/p/{g.club}/{token_de(i)}"; url_j = f"{base}/j/{g.club}/{token_de(i, 'token_jugador')}"
    cel = num_wa(d['acudiente_celular'])
    wa = lambda txt: f'https://wa.me/{cel}?text=' + urllib.parse.quote(txt)
    return render_template('enlace.html', d=d, url_a=url_a, url_j=url_j,
                           wa_a=wa(f"Hola, este es el enlace para ver la carta, las estadísticas, la asistencia y los pagos de {d['nombre']} en {club}: {url_a}"),
                           wa_j=wa(f"Este es el enlace de {d['nombre']} para ver su carta de jugador en {club}: {url_j}"))

def abrir_portal(slug, token, col):
    d = q(f'SELECT * FROM deportistas WHERE {col}=? AND activo=1', (token,), True)
    if not d: abort(404)
    return d

def mensaje_club():
    return render_template('mensaje.html', titulo='Este espacio está en pausa', texto='El club está renovando su plan. Vuelve a intentarlo en unos días.'), 402

def render_carta(d, vista, token=None):
    t = tarjeta(d['id']); mes = datetime.now().strftime('%Y-%m'); pagos = []; asis = []
    base = f'/{"p" if vista == "acudiente" else "j"}/{g.club}/{token}' if token else ''
    if vista == 'acudiente':
        pagos = q('SELECT mes, monto, medio_pago FROM mensualidades WHERE deportista_id=? ORDER BY mes DESC LIMIT 6', (d['id'],))
        asis = q('SELECT fecha FROM asistencias WHERE deportista_id=? ORDER BY fecha DESC LIMIT 10', (d['id'],))
    foto_src = (f'/foto/{d["foto"]}' if vista == 'staff' else f'{base}/foto') if d['foto'] else None
    pend_src = f'{base}/foto?pendiente=1' if d['foto_pendiente'] and vista != 'staff' else None
    r = Response(render_template('portal.html', d=d, t=t, vista=vista, base=base, pagos=pagos, asis=asis, mes=mes, al_dia=bool(q('SELECT 1 FROM mensualidades WHERE deportista_id=? AND mes=?', (d['id'], mes), True)),
                                 foto_src=foto_src, pend_src=pend_src, posiciones=POSICIONES, pies=PIES))
    r.headers['Cache-Control'] = 'no-store'; return r

def servir_foto_de(d):
    return enviar_foto(d['foto_pendiente'] if request.args.get('pendiente') and d['foto_pendiente'] else d['foto'])

@app.route('/p/<slug>/<token>')
def portal(slug, token):
    d = abrir_portal(slug, token, 'token_acudiente')
    return render_carta(d, 'acudiente', token) if g.info['vigente'] else mensaje_club()

@app.route('/j/<slug>/<token>')
def jugador(slug, token):
    d = abrir_portal(slug, token, 'token_jugador')
    return render_carta(d, 'jugador', token) if g.info['vigente'] else mensaje_club()

@app.route('/p/<slug>/<token>/foto')
def portal_foto(slug, token):
    return servir_foto_de(abrir_portal(slug, token, 'token_acudiente'))

@app.route('/j/<slug>/<token>/foto')
def jugador_foto(slug, token):
    return servir_foto_de(abrir_portal(slug, token, 'token_jugador'))

@app.post('/j/<slug>/<token>/datos')
def jugador_datos(slug, token):
    d = abrir_portal(slug, token, 'token_jugador'); f = request.form
    if not g.info['vigente']: return mensaje_club()
    limpio = lambda s, n: ''.join(ch for ch in ' '.join((s or '').split()) if ch.isprintable())[:n]
    try:
        ex('UPDATE deportistas SET apodo=?, lema=?, posicion=?, pie=? WHERE id=?', (limpio(f.get('apodo'), 20), limpio(f.get('lema'), 60), f.get('posicion') if f.get('posicion') in POSICIONES else d['posicion'], f.get('pie') if f.get('pie') in PIES else d['pie'], d['id']))
        a = request.files.get('foto')
        if a and a.filename:
            nueva = guardar_foto(a); borrar_foto(d['foto_pendiente']); ex('UPDATE deportistas SET foto_pendiente=? WHERE id=?', (nueva, d['id']))
            flash('¡Foto enviada! Tu entrenador la revisa y aparece en tu carta.', 'ok')
        else: flash('¡Datos guardados!', 'ok')
    except ValueError as e: flash(str(e), 'err')
    return redirect(f'/j/{slug}/{token}')

@app.route('/deportistas/<int:i>/carta')
@login_required
def carta_staff(i):
    return render_carta(dep_permitido(i), 'staff')

# ---------------- Avisos por WhatsApp ----------------
def enviar_wa(cfg, celular, texto):
    url = f"https://graph.facebook.com/{cfg['version']}/{cfg['phone_id']}/messages"
    cuerpo = {'messaging_product': 'whatsapp', 'to': celular, 'type': 'template', 'template': {'name': cfg['plantilla'], 'language': {'code': cfg['idioma']},
              'components': [{'type': 'body', 'parameters': [{'type': 'text', 'text': re.sub(r'\s+', ' ', texto).strip()[:900]}]}]}}
    req = urllib.request.Request(url, json.dumps(cuerpo).encode(), {'Authorization': 'Bearer ' + cfg['token'], 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r: return r.status < 300, ''
    except urllib.error.HTTPError as e: return False, f'HTTP {e.code}: ' + e.read()[:200].decode('utf-8', 'ignore')
    except Exception as e: return False, str(e)[:200]

def encolar_morosos(slug=None):
    mes = date.today().strftime('%Y-%m'); n = 0
    for d in q("""SELECT * FROM deportistas d WHERE d.activo=1 AND d.acepta_whatsapp=1 AND d.acudiente_celular<>'' AND NOT EXISTS (SELECT 1 FROM mensualidades m WHERE m.deportista_id=d.id AND m.mes=?)
                  AND NOT EXISTS (SELECT 1 FROM avisos a WHERE a.deportista_id=d.id AND a.tipo='PAGO' AND substr(a.creado,1,7)=?)""", (mes, mes), slug=slug):
        n += encolar('PAGO', d['id'], f"💳 Recordatorio: la mensualidad de {d['nombre']} del mes {mes} está pendiente. Si ya la pagaste, ignora este mensaje.", d['acudiente_celular'], slug=slug)
    return n

def procesar_avisos(slug, enviar=None):
    enviar = enviar or enviar_wa; hoy = date.today(); mes = hoy.strftime('%Y-%m')
    if ajuste('wa_recordatorios', '1', slug) == '1' and ajuste('wa_ultimo_recordatorio', '', slug) != mes and hoy.day > int(ajuste('dia_gracia', DIA_GRACIA, slug)):
        encolar_morosos(slug); ex('INSERT OR REPLACE INTO ajustes(clave,valor) VALUES(?,?)', ('wa_ultimo_recordatorio', mes), slug=slug)
    cfg = dict(phone_id=ajuste('wa_phone_id', '', slug), token=ajuste('wa_token', '', slug), plantilla=ajuste('wa_plantilla', '', slug), idioma=ajuste('wa_idioma', 'es', slug), version=ajuste('wa_version', 'v26.0', slug))
    if ajuste('wa_modo', 'manual', slug) != 'api' or not (cfg['phone_id'] and cfg['token'] and cfg['plantilla']): return 0
    n = 0
    for a in q("SELECT * FROM avisos WHERE estado='PENDIENTE' AND intentos<3 ORDER BY id LIMIT 25", slug=slug):
        ok, err = enviar(cfg, a['celular'], a['texto'])
        if ok: ex("UPDATE avisos SET estado='ENVIADO', enviado=datetime('now','localtime'), error=NULL WHERE id=?", (a['id'],), slug=slug); n += 1
        else: ex("UPDATE avisos SET intentos=intentos+1, error=?, estado=CASE WHEN intentos+1>=3 THEN 'ERROR' ELSE estado END WHERE id=?", (err, a['id']), slug=slug)
    return n

def trabajador():
    while True:
        try:
            for r in pq("SELECT slug FROM clubes WHERE estado IN ('TRIAL','ACTIVE') AND vence>=date('now','localtime')"):
                try: procesar_avisos(r['slug'])
                except Exception as e: print('avisos', r['slug'], e)
                if ajuste('cloud', '0', r['slug']) == '1' and time.time() - ULTIMA_SYNC.get(r['slug'], 0) > 300:
                    ULTIMA_SYNC[r['slug']] = time.time()
                    try: sincronizar_club(r['slug'])
                    except Exception as e: print('sincronizar', r['slug'], e)
        except Exception as e: print('trabajador', e)
        time.sleep(30)

app.jinja_env.filters['urlq'] = lambda s: urllib.parse.quote(s or '')

@app.route('/avisos')
@admin_required
def avisos():
    return render_template('avisos.html', rows=q('SELECT a.*, d.nombre FROM avisos a LEFT JOIN deportistas d ON d.id=a.deportista_id ORDER BY a.id DESC LIMIT 80'),
                           pend=q("SELECT COUNT(*) n FROM avisos WHERE estado='PENDIENTE'", one=True)['n'], modo=ajuste('wa_modo', 'manual'))

@app.post('/avisos/pagos')
@admin_required
def avisos_pagos():
    flash(f'{encolar_morosos()} recordatorios de pago en cola', 'ok'); return redirect('/avisos')

@app.post('/avisos/<int:i>/enviado')
@admin_required
def aviso_enviado(i):
    ex("UPDATE avisos SET estado='ENVIADO', enviado=datetime('now','localtime') WHERE id=?", (i,)); return redirect('/avisos')

# ---------------- Modo sin conexión: paquete y sincronización ----------------
@app.route('/api/csrf')
@login_required
def api_csrf():
    return jsonify(csrf=session['csrf'])

@app.route('/api/offline/paquete')
@login_required
def api_paquete():
    cats = cats_permitidas()
    deps = [dict(r) for r in q(f'SELECT id, nombre, categoria FROM deportistas WHERE activo=1 AND categoria IN ({marcadores(cats)}) ORDER BY nombre', cats)]
    out = dict(club=g.club, generado=datetime.now().isoformat(timespec='seconds'), umbral=UMBRAL_FACIAL, margen=MARGEN_FACIAL, deportistas=deps, rostros=[])
    if request.args.get('rostros') == '1':
        ids = {d['id'] for d in deps}
        out['rostros'] = [dict(id=r['i'], d=json.loads(r['s'])) for r in q('SELECT r.deportista_id i, r.descriptor s FROM rostros r JOIN deportistas d ON d.id=r.deportista_id WHERE d.activo=1 AND d.consentimiento_biometrico IS NOT NULL') if r['i'] in ids]
    return jsonify(out)

@app.post('/api/offline/sync')
@login_required
def api_sync():
    marcas = (request.get_json(silent=True) or {}).get('marcas')
    if not isinstance(marcas, list) or len(marcas) > 300: return jsonify(ok=False), 400
    cats = cats_permitidas(); nuevos = ya = rechazadas = 0; ahora = datetime.now()
    for m in marcas:
        try:
            did = int(m.get('id')); cuando = datetime.strptime(str(m.get('ts')), '%Y-%m-%d %H:%M:%S')
            dist = round(float(m['dist']), 4) if m.get('dist') is not None else None
        except (TypeError, ValueError, AttributeError): rechazadas += 1; continue
        if cuando > ahora + timedelta(minutes=10) or cuando < ahora - timedelta(days=3): rechazadas += 1; continue
        d = q('SELECT * FROM deportistas WHERE id=? AND activo=1', (did,), True)
        if not d or d['categoria'] not in cats: rechazadas += 1; continue
        try:
            ex('INSERT INTO asistencias(deportista_id, entrenador, metodo, distancia, fecha) VALUES(?,?,?,?,?)', (did, session['user'], 'FACIAL' if m.get('metodo') == 'FACIAL' else 'MANUAL', dist, cuando.strftime('%Y-%m-%d %H:%M:%S')))
            nuevos += 1; avisar_llegada(d, cuando)
        except sqlite3.IntegrityError: ya += 1
    return jsonify(ok=True, nuevos=nuevos, ya=ya, rechazadas=rechazadas)

# ---------------- Plataforma: landing, registro, suscripción y panel ----------------
INTENTOS_REG = {}

def slug_de(txt):
    return re.sub(r'[^a-z0-9]+', '-', norm(txt)).strip('-')[:30].strip('-')

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        f = request.form; ip = request.remote_addr; recientes = [t for t in INTENTOS_REG.get(ip, []) if time.time() - t < 3600]
        slug = slug_de(f.get('codigo') or f.get('nombre', '')); usuario = f.get('usuario', '').strip().lower(); err = None
        if len(recientes) >= 3: err = 'Demasiados registros desde esta conexión. Intenta más tarde.'
        elif len(f.get('nombre', '').strip()) < 3: err = 'Escribe el nombre del club'
        elif len(slug) < 3 or slug in RESERVADOS: err = 'Elige otro código de club (3 a 30 letras o números)'
        elif estado_club(slug): err = 'Ese código ya está en uso. Prueba con otro.'
        elif not re.fullmatch(r'[a-z0-9]{3,20}', usuario): err = 'El usuario debe tener de 3 a 20 letras o números, sin espacios'
        elif len(f.get('clave', '')) < 8: err = 'La contraseña debe tener mínimo 8 caracteres'
        elif not f.get('acepta'): err = 'Debes aceptar el tratamiento de datos para continuar'
        if not err:
            try: crear_club(slug, f['nombre'].strip()[:80], f.get('email', '').strip()[:80], f.get('celular', '').strip()[:20], usuario, f['clave'], f.get('admin', '').strip()[:80])
            except sqlite3.IntegrityError: err = 'Ese código ya está en uso. Prueba con otro.'
        if err:
            flash(err, 'err'); return render_template('registro.html', v=f)
        INTENTOS_REG[ip] = recientes + [time.time()]
        u = q('SELECT * FROM usuarios WHERE username=?', (usuario,), True, slug=slug)
        session.clear(); session.permanent = True; session.update(uid=u['id'], user=usuario, rol='admin', cambiar=0, club=slug)
        flash(f'¡Listo! Tu club tiene {TRIAL_DIAS} días de prueba. Tu código de club es: {slug}', 'ok'); return redirect('/resumen')
    return render_template('registro.html', v={})

@app.route('/suscripcion')
def suscripcion():
    if 'uid' not in session or not session.get('club'): return redirect('/login')
    return render_template('suscripcion.html', i=estado_club(session['club']), slug=session['club'], es_admin=session.get('rol') == 'admin')

@app.post('/webhook/pagos')
def webhook_pagos():
    raw = request.get_data()
    if not WEBHOOK_SECRET: abort(404)
    if not hmac.compare_digest(hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest(), request.headers.get('X-Signature', '')): abort(401)
    try: j = json.loads(raw); slug, plan = j['slug'], j.get('plan')
    except (ValueError, KeyError, TypeError): abort(400)
    info = estado_club(slug) or abort(404)
    if j.get('paid') and plan in PLANES:
        base = max(date.fromisoformat(info['vence']), date.today())
        pex("UPDATE clubes SET plan=?, estado='ACTIVE', vence=?, ultimo_pago=datetime('now','localtime') WHERE slug=?", (plan, (base + timedelta(days=PLANES[plan]['dias'])).isoformat(), slug))
    elif not j.get('paid'): pex("UPDATE clubes SET estado='SUSPENDIDO' WHERE slug=?", (slug,))
    return jsonify(ok=True)

@app.route('/plataforma/login', methods=['GET', 'POST'])
def plataforma_login():
    if request.method == 'POST':
        clave = ('super', request.remote_addr); fallos = [t for t in INTENTOS.get(clave, []) if time.time() - t < 300]
        if len(fallos) < 5 and SUPER_PASS and hmac.compare_digest(request.form.get('clave', '').encode(), SUPER_PASS.encode()):
            session['super'] = True; return redirect('/plataforma')
        INTENTOS[clave] = fallos + [time.time()]; flash('Clave incorrecta', 'err')
    return render_template('plataforma_login.html')

@app.route('/plataforma')
def plataforma():
    if not session.get('super'): return redirect('/plataforma/login')
    filas = []
    for r in pq('SELECT * FROM clubes ORDER BY creado DESC'):
        d = estado_club(r['slug'])
        try: d['deportistas'] = q('SELECT COUNT(*) n FROM deportistas WHERE activo=1', one=True, slug=r['slug'])['n']; d['usuarios'] = q('SELECT COUNT(*) n FROM usuarios', one=True, slug=r['slug'])['n']
        except Exception: d['deportistas'] = d['usuarios'] = '?'
        filas.append(d)
    return render_template('plataforma.html', filas=filas)

@app.post('/plataforma/<slug>/accion')
def plataforma_accion(slug):
    if not session.get('super'): abort(403)
    info = estado_club(slug) or abort(404); a = request.form.get('accion'); base = max(date.fromisoformat(info['vence']), date.today())
    if a in ('activar_mensual', 'activar_anual'):
        plan = 'MENSUAL' if a == 'activar_mensual' else 'ANUAL'
        pex("UPDATE clubes SET plan=?, estado='ACTIVE', vence=?, ultimo_pago=datetime('now','localtime') WHERE slug=?", (plan, (base + timedelta(days=PLANES[plan]['dias'])).isoformat(), slug))
    elif a == 'suspender': pex("UPDATE clubes SET estado='SUSPENDIDO' WHERE slug=?", (slug,))
    elif a == 'sumar_dias':
        try: dias = min(max(int(request.form.get('dias') or 0), 1), 365)
        except ValueError: dias = 7
        pex("UPDATE clubes SET vence=?, estado=CASE estado WHEN 'SUSPENDIDO' THEN 'ACTIVE' ELSE estado END WHERE slug=?", ((base + timedelta(days=dias)).isoformat(), slug))
    return redirect('/plataforma')

@app.route('/plataforma/salir')
def plataforma_salir():
    session.pop('super', None); return redirect('/')

# ---------------- Acceso único desde la plataforma cloud (FastAPI / Next.js) ----------------
# ---------------- Sincronización con la plataforma cloud ----------------
ROL_FLASK = {'club_admin': 'admin', 'trainer': 'entrenador'}
PLAN_FLASK = {'MONTHLY': 'MENSUAL', 'ANNUAL': 'ANUAL'}
ULTIMA_SYNC = {}

def firmar_puente(slug, cuerpo=b''):
    ts = str(int(time.time()))
    firma = hmac.new(BRIDGE_SECRET.encode(), f'{slug}.{ts}.{hashlib.sha256(cuerpo).hexdigest()}'.encode(), hashlib.sha256).hexdigest()
    return {'X-Bridge-Time': ts, 'X-Bridge-Signature': firma, 'Content-Type': 'application/json'}

def api_cloud(metodo, ruta, slug, cuerpo=None):
    """Llamada firmada a la API cloud. Devuelve (código HTTP, JSON); código 0 si no hay conexión."""
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else b''
    req = urllib.request.Request(API_URL + ruta, datos or None, firmar_puente(slug, datos), method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=10) as r: return r.status, json.loads(r.read() or b'null')
    except urllib.error.HTTPError as e: return e.code, None
    except Exception: return 0, None

def copiar_suscripcion(slug, plan, estado, vence):
    estado = {'SUSPENDED': 'SUSPENDIDO'}.get(estado, estado); plan = PLAN_FLASK.get(plan, plan)
    if estado in ('TRIAL', 'ACTIVE', 'SUSPENDIDO') and plan in PLANES:
        try: pex('UPDATE clubes SET plan=?, estado=?, vence=? WHERE slug=?', (plan, estado, date.fromisoformat(vence).isoformat(), slug))
        except (ValueError, TypeError): pass

def alta_usuario_cloud(slug, email, nombre, rol):
    base = re.sub(r'[^a-z0-9]', '', email.split('@')[0])[:16] or 'usuario'; usuario = base
    while q('SELECT 1 FROM usuarios WHERE username=?', (usuario,), True, slug=slug): usuario = base[:12] + secrets.token_hex(2)
    return ex('INSERT INTO usuarios(username,password,rol,cambiar,nombre_completo,email,origen) VALUES(?,?,?,0,?,?,?)',
              (usuario, generate_password_hash(secrets.token_urlsafe(24)), rol, nombre[:80], email, 'cloud'), slug=slug)

def empujar_deportista(slug, d):
    """Envía a la plataforma un deportista que nació en Flask. Si no hay conexión queda pendiente y se reintenta solo."""
    estado, r = api_cloud('POST', f'/api/v1/bridge/athletes/{slug}', slug, {'full_name': d['nombre'], 'category': d['categoria']})
    if estado in (200, 201) and r: ex('UPDATE deportistas SET cloud_id=? WHERE id=?', (r['id'], d['id']), slug=slug); return True
    return False

def sincronizar_club(slug):
    """Deja el club igual que en la plataforma: personal con sus categorías, deportistas y suscripción.
    La plataforma manda sobre usuarios, roles, categorías y nombre/categoría/estado de los deportistas."""
    if not (BRIDGE_SECRET and API_URL): return None
    enviados = sum(1 for d in q('SELECT * FROM deportistas WHERE cloud_id IS NULL AND activo=1', slug=slug) if empujar_deportista(slug, d))
    estado, snap = api_cloud('GET', f'/api/v1/bridge/snapshot/{slug}', slug)
    if estado != 200 or not snap: return None
    res = dict(usuarios=0, deportistas=0, enviados=enviados); correos = set()
    for u in snap['users']:
        rol = ROL_FLASK.get(u['role']); email = u['email'].strip().lower()
        if not rol: continue
        correos.add(email); activo = 1 if u['is_active'] else 0
        fila = q('SELECT * FROM usuarios WHERE lower(email)=?', (email,), True, slug=slug)
        if fila:
            ex('UPDATE usuarios SET rol=?, activo=?, nombre_completo=?, origen=? WHERE id=?', (rol, activo, u['full_name'][:80], 'cloud', fila['id']), slug=slug); uid = fila['id']
        else:
            uid = alta_usuario_cloud(slug, email, u['full_name'], rol)
            if not activo: ex('UPDATE usuarios SET activo=0 WHERE id=?', (uid,), slug=slug)
        ex('DELETE FROM usuario_categorias WHERE usuario_id=?', (uid,), slug=slug)
        if rol == 'entrenador':
            for c in u.get('categories', []):
                if c in CATEGORIAS: ex('INSERT OR IGNORE INTO usuario_categorias VALUES(?,?)', (uid, c), slug=slug)
        res['usuarios'] += 1
    for f in q("SELECT id, lower(email) e FROM usuarios WHERE origen='cloud'", slug=slug):
        if f['e'] not in correos: ex('UPDATE usuarios SET activo=0 WHERE id=?', (f['id'],), slug=slug)
    sin_enlace = list(q('SELECT * FROM deportistas WHERE cloud_id IS NULL', slug=slug)); con_enlace = {r['cloud_id']: r for r in q('SELECT * FROM deportistas WHERE cloud_id IS NOT NULL', slug=slug)}
    for a in snap['athletes']:
        if a['category'] not in CATEGORIAS: continue
        d = con_enlace.get(a['id'])
        if not d:
            d = next((r for r in sin_enlace if r['categoria'] == a['category'] and norm(r['nombre']) == norm(a['full_name'])), None)
            if d: sin_enlace.remove(d); ex('UPDATE deportistas SET cloud_id=? WHERE id=?', (a['id'], d['id']), slug=slug)
        if d: ex('UPDATE deportistas SET nombre=?, categoria=?, activo=? WHERE id=?', (a['full_name'], a['category'], 1 if a['is_active'] else 0, d['id']), slug=slug)
        else:
            did = ex('INSERT INTO deportistas(documento,nombre,categoria,rol_deportivo,activo,cloud_id) VALUES(?,?,?,?,?,?)', ('tmp' + secrets.token_hex(4), a['full_name'], a['category'], ROLES[0], 1 if a['is_active'] else 0, a['id']), slug=slug)
            ex('UPDATE deportistas SET documento=? WHERE id=?', (f'SD-{did:05d}', did), slug=slug)
        res['deportistas'] += 1
    copiar_suscripcion(slug, snap.get('plan'), snap.get('status'), snap.get('valid_until'))
    return res

@app.post('/sincronizar')
@admin_required
def sincronizar():
    r = sincronizar_club(g.club)
    flash(f"Sincronizado con la plataforma: {r['usuarios']} usuarios, {r['deportistas']} deportistas" + (f", {r['enviados']} enviados" if r['enviados'] else '') if r else 'No se pudo conectar con la plataforma. Reintenta en unos minutos.', 'ok' if r else 'err')
    return redirect('/configuracion')

SSO_USADOS = {}

def verificar_puente(token):
    try:
        crudo, firma = token.split('.')
        if not hmac.compare_digest(hmac.new(BRIDGE_SECRET.encode(), crudo.encode(), hashlib.sha256).hexdigest(), firma): return None
        datos = json.loads(base64.urlsafe_b64decode(crudo + '=' * (-len(crudo) % 4)))
    except (ValueError, TypeError): return None
    ahora = time.time()
    for k in [k for k, v in SSO_USADOS.items() if v < ahora]: SSO_USADOS.pop(k, None)
    if not isinstance(datos, dict) or datos.get('exp', 0) < ahora or datos.get('jti') in SSO_USADOS: return None
    SSO_USADOS[datos['jti']] = datos['exp']
    return datos

@app.route('/sso')
def sso():
    d = verificar_puente(request.args.get('t', '')) if BRIDGE_SECRET else None
    if not d: abort(403)
    slug, email, rol = d.get('slug', ''), (d.get('email') or '').strip().lower(), d.get('role')
    if not SLUG_RE.match(slug) or slug in RESERVADOS or '@' not in email or rol not in ('club_admin', 'trainer'): abort(403)
    base = re.sub(r'[^a-z0-9]', '', email.split('@')[0])[:16] or 'usuario'
    nombre = (d.get('name') or '')[:80]
    if not estado_club(slug):
        if rol != 'club_admin': abort(403)
        crear_club(slug, (d.get('club') or slug)[:80], email, '', base, secrets.token_urlsafe(24), nombre)
    ex('INSERT OR REPLACE INTO ajustes(clave,valor) VALUES(?,?)', ('cloud', '1'), slug=slug)
    copiar_suscripcion(slug, d.get('plan'), d.get('status'), d.get('valid_until'))
    sincronizar_club(slug)   # trae personal, categorías y deportistas: nadie crea nada a mano en Flask
    u = q('SELECT * FROM usuarios WHERE lower(email)=?', (email,), True, slug=slug)
    if not u:   # la API no respondió: se crea desde los datos firmados del enlace
        uid = alta_usuario_cloud(slug, email, nombre, 'admin' if rol == 'club_admin' else 'entrenador'); u = q('SELECT * FROM usuarios WHERE id=?', (uid,), True, slug=slug)
    if u['activo'] == 0: abort(403)   # desactivado en la plataforma
    ex('UPDATE usuarios SET origen=?, nombre_completo=COALESCE(NULLIF(?,\'\'), nombre_completo), rol=? WHERE id=?', ('cloud', nombre, 'admin' if rol == 'club_admin' else 'entrenador', u['id']), slug=slug)
    u = q('SELECT * FROM usuarios WHERE id=?', (u['id'],), True, slug=slug)
    session.clear(); session.permanent = True
    session.update(uid=u['id'], user=u['username'], rol=u['rol'], cambiar=0, club=slug)
    return redirect('/')

# ---------------- Resumen (admin) ----------------
@app.route('/resumen')
@admin_required
def resumen():
    mes = datetime.now().strftime('%Y-%m'); uno = lambda sql, a=(): q(sql, a, True)[0]
    k = dict(
        activos=uno('SELECT COUNT(*) FROM deportistas WHERE activo=1'),
        hoy=uno("SELECT COUNT(*) FROM asistencias WHERE date(fecha)=date('now','localtime')"),
        pendientes=uno('SELECT COUNT(*) FROM deportistas d WHERE d.activo=1 AND NOT EXISTS (SELECT 1 FROM mensualidades m WHERE m.deportista_id=d.id AND m.mes=?)', (mes,)),
        mens=uno('SELECT COALESCE(SUM(monto),0) FROM mensualidades WHERE substr(fecha,1,7)=?', (mes,)),
        tienda=uno('SELECT COALESCE(SUM(total),0) FROM ventas WHERE substr(fecha,1,7)=?', (mes,)),
        egresos=uno('SELECT COALESCE(SUM(monto),0) FROM egresos WHERE substr(fecha,1,7)=?', (mes,)),
        bajo=uno('SELECT COUNT(*) FROM productos WHERE activo=1 AND stock<=stock_minimo'),
        con_rostro=uno('SELECT COUNT(DISTINCT deportista_id) FROM rostros'),
        cajas=uno("SELECT COUNT(*) FROM cajas WHERE estado='ABIERTA'"),
        avisos=uno("SELECT COUNT(*) FROM avisos WHERE estado='PENDIENTE'"),
        eventos=uno('SELECT COUNT(*) FROM eventos WHERE substr(fecha,1,7)=?', (mes,)))
    return render_template('resumen.html', k=k, mes=mes, cats=q('SELECT categoria, COUNT(*) n FROM deportistas WHERE activo=1 GROUP BY categoria ORDER BY categoria'))

# ---------------- Reportes (Excel / impresión ligera) ----------------
REPORTES = {
 'deportistas': ('Deportistas', False, False, "SELECT documento Documento, nombre Nombre, categoria Categoria, rol_deportivo Rol, acudiente_nombre Acudiente, acudiente_celular Celular, contacto_emergencia Emergencia, CASE activo WHEN 1 THEN 'Activo' ELSE 'Inactivo' END Estado FROM deportistas ORDER BY categoria, nombre"),
 'asistencias': ('Asistencias', True, False, "SELECT a.fecha Fecha, d.documento Documento, d.nombre Deportista, d.categoria Categoria, a.entrenador Registro, a.metodo Metodo FROM asistencias a JOIN deportistas d ON d.id=a.deportista_id WHERE date(a.fecha) BETWEEN ?1 AND ?2 ORDER BY a.fecha DESC"),
 'ingresos': ('Ventas y Mensualidades', True, True, """SELECT m.fecha Fecha, 'Mensualidad' Tipo, d.nombre || ' (' || m.mes || ')' Detalle, m.medio_pago Medio, m.monto Valor, m.cajero Cajero FROM mensualidades m JOIN deportistas d ON d.id=m.deportista_id WHERE date(m.fecha) BETWEEN ?1 AND ?2
    UNION ALL SELECT v.fecha, 'Tienda', (SELECT group_concat(descripcion || ' x' || cantidad, ', ') FROM venta_items WHERE venta_id=v.id), v.metodo_pago, v.total, v.cajero FROM ventas v WHERE date(v.fecha) BETWEEN ?1 AND ?2 ORDER BY 1 DESC"""),
 'inventario': ('Inventario', False, False, "SELECT codigo Codigo, producto Producto, talla Talla, costo Costo, precio Precio, stock Stock, stock_minimo Minimo, CASE WHEN stock<=stock_minimo THEN 'REPONER' ELSE 'OK' END Alerta FROM productos WHERE activo=1 ORDER BY producto"),
 'estadisticas': ('Estadísticas por jugador', False, False, "SELECT d.nombre Deportista, d.categoria Categoria, COUNT(CASE WHEN e.tipo='PARTIDO' THEN 1 END) Partidos, COALESCE(SUM(CASE WHEN e.tipo='PARTIDO' THEN s.goles END),0) Goles, COALESCE(SUM(CASE WHEN e.tipo='PARTIDO' THEN s.asistencias END),0) Pases_gol, COALESCE(SUM(s.amarillas),0) Amarillas, COALESCE(SUM(s.rojas),0) Rojas, COALESCE(SUM(s.minutos),0) Minutos, ROUND(AVG(NULLIF(CASE WHEN e.tipo='PARTIDO' THEN s.calificacion END,0)),1) Calificacion_prom, ROUND(AVG(NULLIF(s.actitud,0)),1) Actitud_prom FROM deportistas d LEFT JOIN estadisticas s ON s.deportista_id=d.id LEFT JOIN eventos e ON e.id=s.evento_id WHERE d.activo=1 GROUP BY d.id ORDER BY d.categoria, d.nombre"),
 'morosos': ('Mensualidades pendientes del mes', False, False, "SELECT d.nombre Deportista, d.categoria Categoria, d.acudiente_nombre Acudiente, d.acudiente_celular Celular FROM deportistas d WHERE d.activo=1 AND NOT EXISTS (SELECT 1 FROM mensualidades m WHERE m.deportista_id=d.id AND m.mes=strftime('%Y-%m','now','localtime')) ORDER BY d.categoria, d.nombre"),
 'caja': ('Cierres de Caja', True, True, "SELECT id Turno, cajero Cajero, apertura Apertura, cierre Cierre, base Base, esperado Esperado, contado Contado, diferencia Diferencia, estado Estado FROM cajas WHERE date(apertura) BETWEEN ?1 AND ?2 ORDER BY id DESC"),
}

@app.route('/reporte/<mod>')
@login_required
def reporte(mod):
    if mod not in REPORTES: abort(404)
    titulo, fechado, solo_admin, sql = REPORTES[mod]
    if solo_admin and session['rol'] != 'admin': abort(403)
    desde, hasta = request.args.get('desde') or '2000-01-01', request.args.get('hasta') or '2999-12-31'
    params = (desde, hasta) if fechado else ()
    if request.args.get('fmt') == 'xlsx':
        import pandas as pd
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter
        c = db(); df = pd.read_sql_query(sql, c, params=params); c.close()
        if 'Categoria' in df.columns and session['rol'] != 'admin': df = df[df['Categoria'].isin(cats_permitidas())]
        buf = io.BytesIO(); hoja = titulo[:31]
        with pd.ExcelWriter(buf, engine='openpyxl') as w:
            df.to_excel(w, index=False, sheet_name=hoja); ws = w.sheets[hoja]; ws.freeze_panes = 'A2'
            for i, col in enumerate(df.columns, 1):
                ws.column_dimensions[get_column_letter(i)].width = min(45, max([len(str(col))] + [len(str(v)) for v in df[col].head(300)]) + 3)
            for cell in ws[1]:
                cell.font = Font(bold=True, color='FFFFFF'); cell.fill = PatternFill('solid', fgColor='0F172A')
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name=f'{mod}_{datetime.now():%Y%m%d}.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    c = db(); cur = c.execute(sql, params); cols = [d[0] for d in cur.description]; rows = cur.fetchall(); c.close()
    if 'Categoria' in cols and session['rol'] != 'admin':
        k = cols.index('Categoria'); ok = cats_permitidas(); rows = [r for r in rows if r[k] in ok]
    return render_template('print.html', titulo=titulo, mod=mod, cols=cols, rows=rows, fechado=fechado, desde=request.args.get('desde', ''), hasta=request.args.get('hasta', ''),
                           now=datetime.now().strftime('%d/%m/%Y %H:%M'))

# ---------------- Plantillas ----------------
CSS = """
:root{--bg:#0F172A;--card:#1E293B;--g:#10B981;--b:#3B82F6;--y:#F59E0B;--r:#EF4444;--t:#F8FAFC;--m:#94A3B8;--bd:#334155}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--t);font:15px 'Segoe UI',system-ui,sans-serif}
.nav{background:var(--card);border-bottom:1px solid var(--bd);padding:10px 20px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.nav b{color:var(--g);margin-right:14px}.nav a{color:var(--t);text-decoration:none;padding:7px 12px;border-radius:8px}.nav a:hover{background:var(--bd)}.nav .out{color:var(--r)}.sp{flex:1}
main{max-width:1180px;margin:0 auto;padding:20px}.card{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:18px;margin-bottom:18px}
h2,h3{margin:0 0 12px}h3{color:var(--g);font-size:16px}.row{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:18px}
input,select,textarea{width:100%;padding:9px 10px;border-radius:8px;border:1px solid var(--bd);background:var(--bg);color:var(--t)}
button,.btn{background:var(--g);color:#fff;border:0;padding:9px 15px;border-radius:8px;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block;font-size:14px}
.btn-blue{background:var(--b)}.btn-gold{background:var(--y);color:#000}.btn-red{background:var(--r)}.btn-sm{padding:5px 10px;font-size:13px}
table{width:100%;border-collapse:collapse}th,td{padding:8px 10px;border-bottom:1px solid var(--bd);text-align:left}th{color:var(--m);font-size:12px;text-transform:uppercase}
.msg{padding:10px 14px;border-radius:10px;margin-bottom:12px;border:1px solid}.ok{background:#10B98122;border-color:var(--g)}.err{background:#EF444422;border-color:var(--r)}
.warn{background:#F59E0B14;border-color:#F59E0B66;color:#FCD34D;font-size:13px;padding:6px 12px}
.dot{color:var(--y);font-size:12px}.muted{color:var(--m)}.low{color:var(--y);font-weight:700}.pos{color:var(--g)}.neg{color:var(--r)}
.dd{position:relative;display:inline-block}.dd summary{list-style:none}.dd summary::-webkit-details-marker{display:none}
.dd-menu{position:absolute;right:0;z-index:5;background:var(--card);border:1px solid var(--bd);border-radius:10px;min-width:230px;margin-top:4px;overflow:hidden}
.dd-menu a{display:block;padding:10px 14px;color:var(--t);text-decoration:none}.dd-menu a:hover{background:var(--bd)}
.big{font-size:26px;font-weight:800}.kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-bottom:14px}.kpi div{background:var(--bg);border-radius:10px;padding:12px}
video.cam{width:100%;max-width:560px;border-radius:14px;border:3px solid var(--b);transform:scaleX(-1);background:#000}
@media print{body{background:#fff;color:#000}.noprint,.nav{display:none!important}.card{border:0;box-shadow:none;padding:0}th,td{border-color:#999;color:#000}main{max-width:none;padding:0}.msg{display:none}}
"""
T = {}
T['_m.html'] = """{% macro reportes(mod, etq='📑 Reportes') %}<details class="dd noprint"><summary class="btn btn-blue">{{ etq }} ▾</summary><div class="dd-menu">
<a href="/reporte/{{ mod }}?fmt=xlsx">📊 Descargar en Excel</a><a href="/reporte/{{ mod }}" target="_blank">📄 Versión PDF / Impresión</a></div></details>{% endmacro %}
{% macro tok() %}<input type="hidden" name="csrf" value="{{ csrf() }}">{% endmacro %}"""
T['base.html'] = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{ club.nombre }}</title><link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#0F172A"><link rel="icon" href="/static/icon-192.png"><style>/*CSS*/</style></head><body>
<nav class="nav noprint"><b>⚽ {{ club.nombre }}</b><a href="/asistencia">Asistencia</a><a href="/deportistas">Deportistas</a><a href="/cobros">Cobros y Tienda</a><a href="/inventario">Inventario</a><a href="/caja">Caja</a><a href="/asistencia/facial">📸 Facial</a>{% if session.rol == 'admin' %}<a href="/resumen">Resumen</a><a href="/usuarios">Usuarios</a><a href="/configuracion">Configuración</a>{% endif %}
<span class="sp"></span><a href="/cuenta">{{ session.user }} · {{ session.rol }}</a><a href="/logout" class="out">Salir</a></nav>
<main>{% for cat, msg in get_flashed_messages(with_categories=true) %}<div class="msg {{ cat }}">{{ msg }}</div>{% endfor %}{% block body %}{% endblock %}</main><script>if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js')</script></body></html>"""
T['login.html'] = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><title>Ingreso · {{ club.nombre }}</title><style>/*CSS*/body{display:flex;justify-content:center;align-items:center;height:100vh}</style></head><body>
<div class="card" style="width:340px"><h2 style="color:var(--g)">⚽ Trazelio Sport</h2><p class="muted">{{ club.nombre }}</p>
{% for cat, msg in get_flashed_messages(with_categories=true) %}<div class="msg {{ cat }}">{{ msg }}</div>{% endfor %}
<form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><input name="username" placeholder="Usuario" required autofocus><br><br><input name="password" type="password" placeholder="Contraseña" required><br><br><button style="width:100%">Ingresar</button></form></div></body></html>"""
T['cuenta.html'] = """{% extends 'base.html' %}{% import '_m.html' as m %}{% block body %}<div class="card" style="max-width:420px"><h3>🔐 Cambiar contraseña</h3>
{% if session.cambiar %}<p class="muted">Por seguridad debes cambiar la contraseña inicial.</p>{% endif %}
<form method="post">{{ m.tok() }}<input type="password" name="actual" placeholder="Contraseña actual" required><br><br><input type="password" name="nueva" placeholder="Nueva contraseña (mínimo 8)" required><br><br><button>Guardar</button></form></div>{% endblock %}"""
T['deportistas.html'] = """{% extends 'base.html' %}{% import '_m.html' as m %}{% block body %}
<div class="row"><h2>Deportistas</h2>{{ m.reportes('deportistas') }}</div>
<div class="card"><h3>{{ 'Editar deportista' if e.id else 'Registro rápido' }}</h3><form method="post" action="/deportistas/guardar">{{ m.tok() }}<input type="hidden" name="id" value="{{ e.id }}">
<div class="grid"><input name="nombre" placeholder="Nombre completo" value="{{ e.nombre }}" required autofocus>
<select name="categoria">{% for c in categorias %}<option {{ 'selected' if e.categoria == c }}>{{ c }}</option>{% endfor %}</select>
<button name="siguiente" value="">Guardar</button><button name="siguiente" value="rostro" class="btn-gold">Guardar y registrar rostro 📸</button></div>
<details {{ 'open' if e.id }} style="margin-top:12px"><summary class="muted" style="cursor:pointer">Más datos (opcional)</summary><div class="grid" style="margin-top:10px">
<input name="documento" placeholder="Documento (opcional)" value="{{ e.documento if e.documento and not e.documento.startswith('SD-') }}">
<select name="rol_deportivo">{% for r in roles %}<option {{ 'selected' if e.rol_deportivo == r }}>{{ r }}</option>{% endfor %}</select>
<input name="acudiente_nombre" placeholder="Acudiente" value="{{ e.acudiente_nombre }}"><input name="acudiente_celular" placeholder="Celular del acudiente" value="{{ e.acudiente_celular }}">
<input name="contacto_emergencia" placeholder="Contacto de emergencia" value="{{ e.contacto_emergencia }}"></div></details></form></div>
<div class="card"><form class="row" method="get"><input name="q" value="{{ t }}" placeholder="Buscar por nombre o documento" style="max-width:340px"><button class="btn-blue">Buscar</button></form>
<table><tr><th>Nombre</th><th>Categoría</th><th>Acudiente</th><th>Documento</th><th></th></tr>
{% for r in rows %}<tr style="{{ 'opacity:.5' if not r.activo }}"><td>{{ r.nombre }} {{ '📸' if r.rostros }}</td><td>{{ r.categoria }}</td><td>{{ r.acudiente_nombre or '' }} {{ r.acudiente_celular or '' }}</td><td class="muted">{{ '' if r.documento.startswith('SD-') else r.documento }}</td>
<td style="white-space:nowrap"><a class="btn btn-sm btn-gold" href="/deportistas/{{ r.id }}/rostro">📸</a> <a class="btn btn-sm" href="/deportistas/{{ r.id }}/enlace">🔗 Acudiente</a> <a class="btn btn-sm btn-blue" href="/deportistas?edit={{ r.id }}">Editar</a>
{% if session.rol == 'admin' %}<form method="post" action="/deportistas/{{ r.id }}/estado" style="display:inline">{{ m.tok() }}<button class="btn-sm btn-gold">{{ 'Desactivar' if r.activo else 'Activar' }}</button></form>{% endif %}</td></tr>{% endfor %}</table></div>{% endblock %}"""
T['asistencia.html'] = """{% extends 'base.html' %}{% import '_m.html' as m %}{% block body %}
<div class="row"><h2>Control de Asistencia</h2><div><a class="btn btn-blue" href="/asistencia/facial">📸 Modo facial</a> {{ m.reportes('asistencias') }}</div></div>
<div class="two"><div class="card"><h3>⚡ Marcar por nombre</h3><input id="buscar" placeholder="Escribe el nombre o apellido…" autocomplete="off" autofocus><div id="res" style="margin-top:8px"></div>
<details style="margin-top:10px"><summary class="muted" style="cursor:pointer">Usar documento o lector</summary><form method="post" action="/asistencia/marcar" style="margin-top:8px">{{ m.tok() }}<input name="documento" placeholder="Documento"><br><br><button class="btn-sm">Registrar</button></form></details></div>
<div class="card"><h3>Hoy</h3>{% for h in hoy %}<div>{{ h.fecha[11:16] }} · <b>{{ h.nombre }}</b> {{ '📸' if h.metodo == 'FACIAL' }} <span class="muted">{{ h.categoria }}</span>{% if h.pend %} <span class="dot" title="Mensualidad pendiente">●</span>{% endif %}</div>{% else %}<span class="muted">Sin registros todavía.</span>{% endfor %}</div></div>
<div class="card"><form class="row" method="get"><h3 style="margin:0">Lista por categoría</h3><select name="cat" onchange="this.form.submit()" style="max-width:240px">{% for c in categorias %}<option {{ 'selected' if c == cat }}>{{ c }}</option>{% endfor %}</select></form>
<table>{% for r in rows %}<tr><td>{{ r.nombre }} {% if gracia and not r.pagado %}<span class="dot" title="Mensualidad pendiente">●</span>{% endif %}</td><td class="muted">{{ r.rol_deportivo }}</td>
<td>{% if r.presente %}<span class="pos">✔ Presente</span>{% else %}<form method="post" action="/asistencia/marcar">{{ m.tok() }}<input type="hidden" name="id" value="{{ r.id }}"><input type="hidden" name="cat" value="{{ cat }}"><button class="btn-sm">Marcar</button></form>{% endif %}</td></tr>
{% else %}<tr><td class="muted">No hay deportistas activos en esta categoría.</td></tr>{% endfor %}</table></div>
<script>const CSRF="{{ csrf() }}",box=document.getElementById('res');let t=null;
document.getElementById('buscar').addEventListener('input',e=>{clearTimeout(t);const v=e.target.value.trim();if(v.length<2){box.textContent='';return}
 t=setTimeout(async()=>{const j=await (await fetch('/api/deportistas/buscar?q='+encodeURIComponent(v))).json();box.textContent='';
  if(!j.length){box.textContent='Sin resultados. ¿Está registrado?';return}
  j.forEach(d=>{const f=document.createElement('form');f.method='post';f.action='/asistencia/marcar';f.style.cssText='display:flex;justify-content:space-between;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--bd)';
   const mk=(n,x)=>{const i=document.createElement('input');i.type='hidden';i.name=n;i.value=x;f.appendChild(i)};mk('csrf',CSRF);mk('id',d.id);mk('cat',d.categoria);
   const s=document.createElement('span');s.textContent=d.nombre+' · '+d.categoria;f.appendChild(s);
   const b=document.createElement(d.presente?'span':'button');b.textContent=d.presente?'✔ Presente':'Marcar';if(!d.presente)b.className='btn-sm';f.appendChild(b);box.appendChild(f)})},250)});</script>{% endblock %}"""
T['cobros.html'] = """{% extends 'base.html' %}{% import '_m.html' as m %}{% block body %}
<div class="row"><h2>Cobros y Tienda</h2><div>{{ m.reportes('morosos', '⏳ Pendientes del mes') }} {% if session.rol == 'admin' %}{{ m.reportes('ingresos') }}{% endif %}</div></div>
{% if not caja %}<div class="msg err">No tienes caja abierta. <a href="/caja" style="color:#fff">Abrir caja →</a></div>{% endif %}
<div class="two"><div class="card"><h3>🎟️ Cobrar mensualidad</h3><form method="post" action="/cobros/mensualidad" class="grid" style="grid-template-columns:1fr">{{ m.tok() }}
<select name="deportista_id" id="dep-m" required><option value="">Deportista…</option>{% for d in deps %}<option value="{{ d.id }}" data-t="{{ tarifas.get(d.categoria, sugerida)|int }}">{{ d.nombre }} · {{ d.categoria }}</option>{% endfor %}</select>
<input type="month" name="mes" value="{{ mes }}" required><input type="number" step="any" min="1" name="monto" id="monto-m" value="{{ sugerida }}" required>
<select name="medio">{% for x in medios %}<option>{{ x }}</option>{% endfor %}</select><button class="btn-gold">Registrar pago</button></form>
<h3 style="margin-top:18px">Últimos pagos</h3>{% for u in ult %}<div class="muted">{{ u.nombre }} · {{ u.mes }} · {{ u.monto|cop }} · {{ u.medio_pago }}</div>{% endfor %}</div>
<div class="card"><h3>🛒 Tienda del club</h3><form method="post" action="/cobros/venta">{{ m.tok() }}
<table><tr><th>Producto</th><th>Talla</th><th>Precio</th><th>Stock</th><th>Cant.</th></tr>
{% for p in prods %}<tr><td>{{ p.producto }}</td><td>{{ p.talla or '' }}</td><td>{{ p.precio|cop }}</td><td class="{{ 'low' if p.stock <= p.stock_minimo }}">{{ p.stock }}</td><td style="width:80px"><input type="number" name="qty_{{ p.id }}" min="0" max="{{ p.stock }}" value="0"></td></tr>
{% else %}<tr><td class="muted" colspan="5">Sin productos con stock. Agrégalos en Inventario.</td></tr>{% endfor %}</table><br>
<div class="grid"><select name="deportista_id"><option value="">Cliente mostrador</option>{% for d in deps %}<option value="{{ d.id }}">{{ d.nombre }}</option>{% endfor %}</select>
<select name="medio">{% for x in medios %}<option>{{ x }}</option>{% endfor %}</select></div><br><button style="width:100%">Cobrar y generar tirilla</button></form></div></div><script>document.getElementById('dep-m').addEventListener('change',e=>{const o=e.target.selectedOptions[0];if(o&&o.dataset.t)document.getElementById('monto-m').value=o.dataset.t})</script>{% endblock %}"""
T['ticket.html'] = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><title>Tirilla #{{ v.id }}</title><style>body{font:13px monospace;width:72mm;margin:8px auto}hr{border:0;border-top:1px dashed #000}td:last-child{text-align:right}table{width:100%}@media print{.noprint{display:none}}</style></head><body onload="window.print()">
<center><b>{{ club.nombre }}</b><br>{{ club.nit }}<br>Tel. {{ club.telefono }}</center><hr>Ticket #{{ v.id }} · {{ v.fecha }}<br>Cajero: {{ v.cajero }}<hr>
<table>{% for i in items %}<tr><td>{{ i.cantidad }} x {{ i.descripcion }}</td><td>{{ (i.cantidad * i.precio)|cop }}</td></tr>{% endfor %}</table><hr><b>TOTAL: {{ v.total|cop }}</b><br>Pago: {{ v.metodo_pago }}<hr><center>¡Gracias por apoyar al club!</center>
<p class="noprint"><a href="/cobros">← Volver</a></p></body></html>"""
T['inventario.html'] = """{% extends 'base.html' %}{% import '_m.html' as m %}{% block body %}
<div class="row"><h2>Inventario</h2>{{ m.reportes('inventario') }}</div>
{% if session.rol == 'admin' %}<div class="card"><h3>{{ 'Editar' if e.id else 'Nuevo' }} producto / ingreso de stock</h3><form method="post" action="/inventario/guardar" class="grid">{{ m.tok() }}
<input name="codigo" placeholder="Código" value="{{ e.codigo }}" required><input name="producto" placeholder="Producto" value="{{ e.producto }}" required><input name="talla" placeholder="Talla" value="{{ e.talla }}">
<input type="number" step="any" min="0" name="costo" placeholder="Costo" value="{{ e.costo }}" required><input type="number" step="any" min="0" name="precio" placeholder="Precio venta" value="{{ e.precio }}" required>
<input type="number" min="0" name="stock_minimo" placeholder="Stock mínimo" value="{{ e.stock_minimo if e.id else 5 }}"><input type="number" name="agregar" placeholder="Unidades a sumar (ingreso)" value="0"><button>Guardar</button></form></div>{% endif %}
<div class="card"><table><tr><th>Código</th><th>Producto</th><th>Talla</th><th>Costo</th><th>Precio</th><th>Stock</th><th></th></tr>
{% for r in rows %}<tr style="{{ 'opacity:.5' if not r.activo }}"><td>{{ r.codigo }}</td><td>{{ r.producto }}</td><td>{{ r.talla or '' }}</td><td>{{ r.costo|cop }}</td><td>{{ r.precio|cop }}</td>
<td class="{{ 'low' if r.stock <= r.stock_minimo }}">{{ r.stock }}{% if r.stock <= r.stock_minimo %} ⚠ reponer{% endif %}</td><td>{% if session.rol == 'admin' %}<a class="btn btn-sm btn-blue" href="/inventario?edit={{ r.id }}">Editar</a>
<form method="post" action="/inventario/{{ r.id }}/estado" style="display:inline">{{ m.tok() }}<button class="btn-sm btn-gold">{{ 'Ocultar' if r.activo else 'Activar' }}</button></form>{% endif %}</td></tr>{% endfor %}</table></div>{% endblock %}"""
T['caja.html'] = """{% extends 'base.html' %}{% import '_m.html' as m %}{% block body %}
<div class="row"><h2>Caja</h2>{% if session.rol == 'admin' %}{{ m.reportes('caja') }}{% endif %}</div>
{% if not abierta %}<div class="card" style="max-width:460px"><h3>Abrir caja</h3><form method="post" action="/caja/abrir">{{ m.tok() }}<label class="muted">Base inicial en efectivo</label><input type="number" step="any" min="0" name="base" value="0" required><br><br><button style="width:100%">Abrir turno</button></form></div>
{% else %}<div class="card"><h3>Turno abierto desde {{ abierta.apertura }}</h3><div class="kpi"><div><span class="muted">Base inicial</span><div class="big">{{ abierta.base|cop }}</div></div>
{% if ver %}<div><span class="muted">Mensualidades</span><div class="big">{{ res.mens|cop }}</div></div><div><span class="muted">Tienda</span><div class="big">{{ res.tienda|cop }}</div></div><div><span class="muted">Egresos</span><div class="big neg">{{ res.egresos|cop }}</div></div>
<div><span class="muted">Efectivo esperado en gaveta</span><div class="big pos">{{ res.esperado|cop }}</div></div>{% endif %}</div>
{% if ver %}<table><tr><th>Medio de pago</th><th>Total</th></tr>{% for k, v in res.por.items() %}<tr><td>{{ k }}</td><td>{{ v|cop }}</td></tr>{% endfor %}</table>{% else %}<p class="muted">Cierre ciego activo: cuenta el efectivo físico antes de ver los totales.</p>{% endif %}</div>
<div class="two"><div class="card"><h3>Egresos y gastos</h3><form method="post" action="/caja/egreso" class="grid">{{ m.tok() }}<input name="concepto" placeholder="Concepto" required><input type="number" step="any" min="1" name="monto" placeholder="Valor" required><button class="btn-gold">Registrar egreso</button></form>
<table>{% for g in egr %}<tr><td>{{ g.concepto }}</td><td class="neg">{{ g.monto|cop }}</td></tr>{% endfor %}</table></div>
<div class="card"><h3>Arqueo y cierre</h3><form method="post" action="/caja/cerrar" onsubmit="return confirm('¿Cerrar la caja con este conteo?')">{{ m.tok() }}<label class="muted">Efectivo contado en gaveta</label><input type="number" step="any" min="0" name="contado" required><br><br><textarea name="notas" rows="2" placeholder="Notas (opcional)"></textarea><br><br><button class="btn-red" style="width:100%">Cerrar caja</button></form></div></div>{% endif %}
<div class="card"><h3>Cierres anteriores</h3><table><tr><th>#</th><th>Cajero</th><th>Apertura</th><th>Diferencia</th><th></th></tr>{% for h in hist %}<tr><td>{{ h.id }}</td><td>{{ h.cajero }}</td><td>{{ h.apertura }}</td><td class="{{ 'neg' if h.diferencia < -0.5 else 'pos' }}">{{ h.diferencia|cop }}</td><td><a class="btn btn-sm btn-blue" href="/caja/{{ h.id }}">Ver</a></td></tr>{% endfor %}</table></div>{% endblock %}"""
T['caja_cierre.html'] = """{% extends 'base.html' %}{% block body %}
<div class="row noprint"><h2>Cierre de caja #{{ c.id }}</h2><div><button onclick="window.print()" class="btn-blue">🖨️ Imprimir / PDF</button> <a class="btn" href="{{ wa }}" target="_blank">📲 Enviar por WhatsApp</a> <a class="btn btn-gold" href="/caja">Volver</a></div></div>
<div class="card"><h2>{{ club.nombre }} — Cierre de caja</h2><p>Cajero: <b>{{ c.cajero }}</b> · {{ c.apertura }} → {{ c.cierre }}</p>
<div class="kpi"><div><span class="muted">Efectivo esperado</span><div class="big">{{ c.esperado|cop }}</div></div><div><span class="muted">Efectivo contado</span><div class="big">{{ c.contado|cop }}</div></div>
<div><span class="muted">Diferencia · {{ estado }}</span><div class="big {{ 'pos' if estado == 'CUADRADA' else 'neg' }}">{{ c.diferencia|cop }}</div></div></div>
<table><tr><th>Concepto</th><th>Valor</th></tr><tr><td>Base inicial</td><td>{{ c.base|cop }}</td></tr><tr><td>Mensualidades</td><td>{{ res.mens|cop }}</td></tr><tr><td>Tienda</td><td>{{ res.tienda|cop }}</td></tr>
{% for k, v in res.por.items() %}<tr><td class="muted">&nbsp;&nbsp;{{ k }}</td><td class="muted">{{ v|cop }}</td></tr>{% endfor %}<tr><td>Egresos</td><td>{{ res.egresos|cop }}</td></tr></table>
{% for g in egr %}<div class="muted">· {{ g.concepto }}: {{ g.monto|cop }}</div>{% endfor %}{% if c.notas %}<p>Notas: {{ c.notas }}</p>{% endif %}</div>
<div class="card noprint"><h3>Resumen para copiar</h3><textarea rows="12" onclick="this.select()" readonly>{{ texto }}</textarea></div>{% endblock %}"""
T['print.html'] = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><title>{{ titulo }}</title><style>body{font:12px Arial,sans-serif;margin:16px;color:#000}table{width:100%;border-collapse:collapse}th,td{border:1px solid #999;padding:4px 6px;text-align:left}th{background:#eee}
.noprint{margin-bottom:12px}@media print{.noprint{display:none}}</style></head><body>
<div class="noprint"><button onclick="window.print()">🖨️ Imprimir / Guardar como PDF</button> <a href="/reporte/{{ mod }}?fmt=xlsx&desde={{ desde }}&hasta={{ hasta }}">📊 Excel</a>
{% if fechado %}<form method="get" style="display:inline;margin-left:14px">Desde <input type="date" name="desde" value="{{ desde }}"> Hasta <input type="date" name="hasta" value="{{ hasta }}"> <button>Filtrar</button></form>{% endif %}</div>
<h2 style="margin:0">{{ club.nombre }} — {{ titulo }}</h2><p>Generado: {{ now }} · {{ rows|length }} registros</p>
<table><tr>{% for c in cols %}<th>{{ c }}</th>{% endfor %}</tr>{% for r in rows %}<tr>{% for v in r %}<td>{{ v if v is not none else '' }}</td>{% endfor %}</tr>{% endfor %}</table></body></html>"""
T['facial.html'] = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Asistencia facial</title><link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#0F172A"><style>/*CSS*/
body{display:flex;flex-direction:column;align-items:center;min-height:100vh;padding:12px}#wrap,#banner,#log,.top{width:min(94vw,640px)}.top{display:flex;justify-content:space-between;align-items:center}
#banner{margin-top:14px;padding:18px;border-radius:14px;text-align:center;font-size:22px;font-weight:800;background:var(--card);border:2px solid var(--bd)}.okb{border-color:var(--g)!important;background:#10B98122!important}.wb{border-color:var(--y)!important}
#log{margin-top:12px;font-size:14px}#log div{padding:5px 0;border-bottom:1px solid var(--bd)}</style></head><body>
<div class="top"><b style="color:var(--g)">⚽ {{ club.nombre }} · Asistencia facial</b><span>{% if session.rol != 'kiosco' %}<a href="/asistencia" style="color:var(--m)">Manual</a> · {% endif %}<a href="/logout" style="color:var(--r)">Salir</a></span></div>
<div id="wrap" style="margin-top:12px"><video id="video" class="cam" autoplay muted playsinline></video></div><div id="banner">Iniciando…</div><div id="log"></div>
<script src="/static/face-api.js"></script><script>
const CSRF="{{ csrf() }}", banner=document.getElementById('banner'), logEl=document.getElementById('log'), video=document.getElementById('video');
let busy=false, ultimo={n:null,t:0}, msgT=0;
function aviso(t,c){banner.textContent=t;banner.className=c||''}
function agregar(j){const d=document.createElement('div');const h=new Date().toTimeString().slice(0,5);
 d.textContent=h+' · '+j.nombre+' · '+j.categoria+(j.pendiente?' ●':'');logEl.prepend(d);while(logEl.children.length>12)logEl.lastChild.remove();}
async function iniciar(){try{
 aviso('Cargando reconocimiento…');
 await faceapi.nets.tinyFaceDetector.loadFromUri('/static/models');await faceapi.nets.faceLandmark68Net.loadFromUri('/static/models');await faceapi.nets.faceRecognitionNet.loadFromUri('/static/models');
 video.srcObject=await navigator.mediaDevices.getUserMedia({video:{facingMode:'user',width:{ideal:640},height:{ideal:480}},audio:false});
 await video.play();aviso('Acércate a la cámara');ciclo();
}catch(e){aviso('No se pudo iniciar la cámara ('+e.message+'). Se requiere HTTPS y permiso de cámara.','wb')}}
async function ciclo(){
 if(!busy){busy=true;try{
  const det=await faceapi.detectSingleFace(video,new faceapi.TinyFaceDetectorOptions({inputSize:320,scoreThreshold:0.6})).withFaceLandmarks().withFaceDescriptor();
  if(det&&det.detection.box.width>110)await enviar(Array.from(det.descriptor));
 }catch(e){}busy=false}
 setTimeout(ciclo,600)}
async function enviar(d){
 const r=await fetch('/api/facial/identificar',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF':CSRF},body:JSON.stringify({descriptor:d})});
 if(r.status===401||r.status===302){location.href='/login';return}
 const j=await r.json(),now=Date.now();
 if(j.estado==='ok'){if(ultimo.n===j.nombre&&now-ultimo.t<8000)return;ultimo={n:j.nombre,t:now};
  aviso(j.ya?'Ya registrado hoy: '+j.nombre:'¡Bienvenido, '+j.nombre+'!',j.ya?'':'okb');if(!j.ya)agregar(j);}
 else if(now-msgT>3000){msgT=now;aviso(j.estado==='ambiguo'?'Rostro dudoso: usa el ingreso por documento':'Rostro no reconocido','wb')}}
iniciar();</script></body></html>"""
T['rostro.html'] = """{% extends 'base.html' %}{% import '_m.html' as m %}{% block body %}
<div class="row"><h2>📸 Rostro de {{ d.nombre }}</h2><a class="btn btn-sm btn-blue" href="/deportistas">← Deportistas</a></div>
{% if not d.consentimiento_biometrico %}<div class="card" style="max-width:560px"><h3>1. Autorización del acudiente</h3>
<p class="muted">El rostro es un dato biométrico sensible (Ley 1581 de 2012). Para menores se requiere autorización expresa del padre, madre o acudiente.</p>
<form method="post" action="/deportistas/{{ d.id }}/consentimiento">{{ m.tok() }}<input name="autoriza" placeholder="Nombre de quien autoriza (acudiente)" value="{{ d.acudiente_nombre or '' }}" required><br><br>
<label><input type="checkbox" name="acepta" value="1" style="width:auto" required> El acudiente autorizó el uso del rostro para control de asistencia y fue informado de que puede pedir su eliminación.</label><br><br><button>Registrar autorización</button></form></div>
{% else %}<div class="card"><p class="muted">Autorización: {{ d.consentimiento_biometrico }}</p><h3>2. Capturar muestras (<span id="n">{{ n }}</span>/{{ maximo }})</h3>
<p class="muted">Toma 3 a 5 muestras con buena luz, de frente y con pequeños cambios de gesto o ángulo.</p><video id="video" class="cam" autoplay muted playsinline></video>
<div id="estado" class="msg" style="margin-top:10px">Cargando…</div><button id="cap" disabled>📸 Capturar muestra</button></div>
{% if session.rol == 'admin' %}<form method="post" action="/deportistas/{{ d.id }}/rostro/borrar" onsubmit="return confirm('¿Eliminar rostros y autorización de este deportista?')">{{ m.tok() }}<button class="btn-red btn-sm">Eliminar datos biométricos</button></form>{% endif %}
<script src="/static/face-api.js"></script><script>
const CSRF="{{ csrf() }}",ID={{ d.id }},video=document.getElementById('video'),est=document.getElementById('estado'),cap=document.getElementById('cap');
(async()=>{try{await faceapi.nets.tinyFaceDetector.loadFromUri('/static/models');await faceapi.nets.faceLandmark68Net.loadFromUri('/static/models');await faceapi.nets.faceRecognitionNet.loadFromUri('/static/models');
 video.srcObject=await navigator.mediaDevices.getUserMedia({video:{facingMode:'user'},audio:false});await video.play();est.textContent='Cámara lista';cap.disabled=false;
}catch(e){est.textContent='No se pudo iniciar la cámara ('+e.message+'). Requiere HTTPS y permiso de cámara.';est.className='msg err'}})();
cap.onclick=async()=>{cap.disabled=true;try{
 const det=await faceapi.detectSingleFace(video,new faceapi.TinyFaceDetectorOptions({inputSize:416,scoreThreshold:0.6})).withFaceLandmarks().withFaceDescriptor();
 if(!det){est.textContent='No se detectó un rostro. Acércate y mejora la luz.';est.className='msg err'}
 else{const r=await fetch('/api/facial/enrolar',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF':CSRF},body:JSON.stringify({deportista_id:ID,descriptor:Array.from(det.descriptor)})});const j=await r.json();
  if(j.ok){document.getElementById('n').textContent=j.total;est.textContent='Muestra '+j.total+' guardada ✔';est.className='msg ok'}else{est.textContent=j.msg;est.className='msg err'}}
}catch(e){est.textContent='Error: '+e.message;est.className='msg err'}cap.disabled=false};</script>{% endif %}{% endblock %}"""
T['usuarios.html'] = """{% extends 'base.html' %}{% import '_m.html' as m %}{% block body %}<h2>Usuarios</h2>
<div class="card"><h3>Nuevo usuario</h3><form method="post" class="grid">{{ m.tok() }}<input name="username" placeholder="Usuario (sin espacios)" required><input name="password" type="password" placeholder="Contraseña (mínimo 8)" required>
<select name="rol"><option value="entrenador">Entrenador / cajero</option><option value="admin">Administrador</option><option value="kiosco">Kiosco de asistencia facial</option></select><button>Crear</button></form>
<p class="muted">El rol "Kiosco" solo abre la pantalla de asistencia facial: úsalo en la tablet de la entrada.</p></div>
<div class="card"><table><tr><th>Usuario</th><th>Rol</th><th>Estado</th><th></th></tr>{% for r in rows %}<tr><td>{{ r.username }}</td><td>{{ r.rol }}</td><td>{{ 'Activo' if r.activo else 'Inactivo' }}</td><td style="white-space:nowrap">
<form method="post" action="/usuarios/{{ r.id }}/clave" style="display:inline">{{ m.tok() }}<input name="password" type="password" placeholder="Nueva clave" style="width:140px;display:inline-block;margin:0"> <button class="btn-sm btn-blue">Restablecer</button></form>
{% if r.id != session.uid %}<form method="post" action="/usuarios/{{ r.id }}/estado" style="display:inline">{{ m.tok() }}<button class="btn-sm btn-gold">{{ 'Desactivar' if r.activo else 'Activar' }}</button></form>{% endif %}</td></tr>{% endfor %}</table></div>{% endblock %}"""
T['config.html'] = """{% extends 'base.html' %}{% import '_m.html' as m %}{% block body %}<h2>Configuración</h2>
<form method="post">{{ m.tok() }}<div class="two"><div class="card"><h3>Datos del club</h3><input name="nombre" value="{{ club.nombre }}" placeholder="Nombre del club" required><br><br><input name="nit" value="{{ club.nit }}" placeholder="NIT"><br><br><input name="telefono" value="{{ club.telefono }}" placeholder="Teléfono"></div>
<div class="card"><h3>Reglas</h3><label class="muted">Día del mes desde el cual la mensualidad se considera vencida</label><input type="number" name="dia_gracia" min="0" max="28" value="{{ dia }}"><br><br>
<label><input type="checkbox" name="cierre_ciego" value="1" style="width:auto" {{ 'checked' if ciego }}> Cierre de caja ciego para entrenadores</label></div></div>
<div class="card"><h3>Mensualidad por categoría</h3><p class="muted">Se sugiere automáticamente al cobrar. Déjalo vacío para usar el valor general.</p><div class="grid">
{% for i, c, v in filas %}<div><label class="muted">{{ c }}</label><input type="number" step="any" min="0" name="tarifa_{{ i }}" value="{{ v|int if v is not none }}"></div>{% endfor %}</div></div><button>Guardar configuración</button></form>{% endblock %}"""
T['enlace.html'] = """{% extends 'base.html' %}{% import '_m.html' as m %}{% block body %}<div class="row"><h2>🔗 Enlace para el acudiente</h2><a class="btn btn-sm btn-blue" href="/deportistas">← Deportistas</a></div>
<div class="card" style="max-width:640px"><p>Con este enlace el acudiente de <b>{{ d.nombre }}</b> ve la asistencia y el estado de pagos, sin usuario ni contraseña. Compártelo solo con el acudiente.</p>
<input value="{{ url }}" readonly onclick="this.select()"><br><br><a class="btn" href="{{ wa }}" target="_blank">📲 Enviar por WhatsApp</a>
<form method="post" style="display:inline" onsubmit="return confirm('El enlace actual dejará de funcionar. ¿Generar uno nuevo?')">{{ m.tok() }}<button class="btn-red">Generar enlace nuevo</button></form></div>{% endblock %}"""
T['portal.html'] = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>{{ d.nombre }} · {{ club.nombre }}</title><style>/*CSS*/body{padding:14px;max-width:560px;margin:0 auto}</style></head><body>
<h3 style="color:var(--g)">⚽ {{ club.nombre }}</h3><div class="card"><h2>{{ d.nombre }}</h2><p class="muted">{{ d.categoria }} · {{ d.rol_deportivo }}</p>
<div class="kpi"><div><span class="muted">Mensualidad {{ mes }}</span><div class="big {{ 'pos' if al_dia else 'low' }}">{{ 'Al día ✔' if al_dia else 'Pendiente' }}</div></div><div><span class="muted">Asistencias del mes</span><div class="big">{{ n_mes }}</div></div></div></div>
<div class="card"><h3>Últimas asistencias</h3>{% for a in asis %}<div>{{ a.fecha[:10] }} · {{ a.fecha[11:16] }}</div>{% else %}<span class="muted">Aún sin registros.</span>{% endfor %}</div>
<div class="card"><h3>Pagos recientes</h3>{% for p in pagos %}<div>{{ p.mes }} · {{ p.monto|cop }} · {{ p.medio_pago }}</div>{% else %}<span class="muted">Sin pagos registrados.</span>{% endfor %}</div>
<p class="muted" style="text-align:center;font-size:12px">Contacto del club: {{ club.telefono }}</p></body></html>"""
T['resumen.html'] = """{% extends 'base.html' %}{% block body %}<div class="row"><h2>Resumen · {{ mes }}</h2></div>
<div class="kpi"><a href="/asistencia" style="text-decoration:none;color:inherit"><div><span class="muted">Presentes hoy</span><div class="big pos">{{ k.hoy }}</div><span class="muted">de {{ k.activos }} activos</span></div></a>
<a href="/reporte/morosos" target="_blank" style="text-decoration:none;color:inherit"><div><span class="muted">Mensualidades pendientes</span><div class="big low">{{ k.pendientes }}</div></div></a>
<div><span class="muted">Recaudo del mes</span><div class="big">{{ (k.mens + k.tienda)|cop }}</div><span class="muted">Mensualidades {{ k.mens|cop }} · Tienda {{ k.tienda|cop }}</span></div>
<div><span class="muted">Egresos del mes</span><div class="big neg">{{ k.egresos|cop }}</div></div>
<a href="/inventario" style="text-decoration:none;color:inherit"><div><span class="muted">Productos por reponer</span><div class="big low">{{ k.bajo }}</div></div></a>
<a href="/deportistas" style="text-decoration:none;color:inherit"><div><span class="muted">Con rostro registrado</span><div class="big">{{ k.con_rostro }}/{{ k.activos }}</div></div></a>
<a href="/caja" style="text-decoration:none;color:inherit"><div><span class="muted">Cajas abiertas</span><div class="big">{{ k.cajas }}</div></div></a></div>
<div class="card"><h3>Deportistas por categoría</h3>{% for c in cats %}<div>{{ c.categoria }}: <b>{{ c.n }}</b></div>{% else %}<span class="muted">Aún no hay deportistas.</span>{% endfor %}</div>{% endblock %}"""
app.jinja_env.loader = ChoiceLoader([FileSystemLoader(os.path.join(BASE, 'templates')), DictLoader({k: v.replace('/*CSS*/', CSS) for k, v in T.items()})])

if __name__ == '__main__':
    init_db()
    threading.Thread(target=trabajador, daemon=True).start()
    print(f'Trazelio Sport activo en http://{HOST}:{PORT}  (Ctrl+C para cerrar)')
    if HOST == '127.0.0.1': threading.Timer(1.2, lambda: webbrowser.open(f'http://127.0.0.1:{PORT}')).start()
    try:
        from waitress import serve
        serve(app, host=HOST, port=PORT, threads=8)
    except ImportError:
        app.run(host=HOST, port=PORT, debug=False, threaded=True)
