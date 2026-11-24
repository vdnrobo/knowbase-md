"""Private feedback storage and password-only administrator UI."""

from contextlib import closing
from http.cookies import CookieError, SimpleCookie
import hashlib
import hmac
import html
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import parse_qs, quote, urlparse

SESSION_COOKIE = 'feedback_session'
ADMIN_COOKIE = 'feedback_admin'
MAX_REQUEST = 65536


def telegram_handle(value):
    value = value.strip()
    if value.startswith('https://'):
        parsed = urlparse(value)
        if parsed.netloc != 't.me' or parsed.query or parsed.fragment:
            return ''
        value = parsed.path.strip('/')
    value = value.removeprefix('@')
    return '@' + value if re.fullmatch(r'[A-Za-z0-9_]{1,64}', value) else ''


class FeedbackMixin:
    def feedback_secret(self):
        return os.environ.get('ADMIN_PASSWORD', '')

    def feedback_sign(self, value):
        return hmac.new(self.feedback_secret().encode('utf-8'), value.encode('utf-8'), hashlib.sha256).hexdigest()

    def feedback_cookies(self):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get('Cookie', ''))
        except CookieError:
            return SimpleCookie()
        return cookies

    def feedback_secure(self):
        return '; Secure' if self.headers.get('X-Forwarded-Proto', '').split(',')[0].strip().lower() == 'https' else ''

    def feedback_session(self, create=False):
        cookie = self.feedback_cookies().get(SESSION_COOKIE)
        value = cookie.value if cookie else ''
        if re.fullmatch(r'[0-9a-f]{32}', value):
            return value
        if create:
            value = secrets.token_hex(16)
            self.feedback_cookie = f'{SESSION_COOKIE}={value}; Path=/; HttpOnly; SameSite=Strict' + self.feedback_secure()
            return value
        return ''

    def feedback_csrf(self, purpose, session=None):
        session = session or self.feedback_session(create=True)
        stamp = str(int(time.time()))
        return stamp + '.' + self.feedback_sign(f'csrf:{purpose}:{session}:{stamp}')

    def feedback_valid_csrf(self, token, purpose):
        origin = self.headers.get('Origin')
        if origin and (urlparse(origin).scheme not in ('http', 'https') or urlparse(origin).netloc != self.headers.get('Host', '')):
            return False
        session = self.feedback_session()
        match = re.fullmatch(r'(\d{10,12})\.([0-9a-f]{64})', token)
        if not session or not match:
            return False
        stamp, signature = match.groups()
        if not -60 <= time.time() - int(stamp) <= 7200:
            return False
        return hmac.compare_digest(signature, self.feedback_sign(f'csrf:{purpose}:{session}:{stamp}'))

    def feedback_connection(self):
        path = Path(self.feedback_database_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('''CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL,
            quote TEXT NOT NULL, surname TEXT NOT NULL, first_name TEXT NOT NULL,
            telegram TEXT NOT NULL, message TEXT NOT NULL, created REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'open', visitor TEXT NOT NULL)''')
        db.execute('CREATE INDEX IF NOT EXISTS feedback_visitor_date ON feedback(visitor, created)')
        db.execute('CREATE TABLE IF NOT EXISTS admin_attempts (visitor TEXT NOT NULL, created REAL NOT NULL)')
        return db

    def feedback_form(self, article, values=None, error=''):
        values = values or {}
        esc = lambda value: html.escape(str(value), quote=True)
        fields = ''
        for key, label, limit, complete in (
            ('surname', 'Фамилия', 100, 'family-name'),
            ('first_name', 'Имя', 100, 'given-name'),
            ('telegram', 'Telegram', 200, 'off'),
        ):
            placeholder = ' placeholder="@username или https://t.me/username"' if key == 'telegram' else ''
            fields += f'<label>{label}<input name="{key}" value="{esc(values.get(key, ""))}" maxlength="{limit}" autocomplete="{complete}" required{placeholder}></label>'
        token = self.feedback_csrf(article['url'])
        return f'''<form class="feedback-form" method="post" action="{esc(article['url'])}/feedback" data-feedback-form>
            <input type="hidden" name="csrf" value="{token}">
            <input type="hidden" name="anchor" value="{esc(values.get('anchor', ''))}">
            <label class="feedback-honeypot" aria-hidden="true">Website<input name="website" tabindex="-1" autocomplete="off"></label>
            <div class="feedback-identity">{fields}</div>
            <label>Цитата<textarea name="quote" maxlength="1000" rows="3">{esc(values.get('quote', ''))}</textarea></label>
            <label>Замечание<textarea name="message" maxlength="4000" rows="5" required>{esc(values.get('message', ''))}</textarea></label>
            <p class="feedback-privacy">Имя и контакт видит только администратор.</p>
            <p class="feedback-result" role="status">{esc(error)}</p>
            <button type="submit" class="reader-command"><img class="ui-icon" src="/static/icons/send.svg" alt="">Отправить</button>
        </form>'''

    def render_article_feedback(self, article):
        if not self.feedback_secret():
            return ''
        return '<section class="article-feedback"><details data-feedback-panel><summary>Сообщить об ошибке</summary>' + self.feedback_form(article) + '</details></section>'

    def feedback_read_form(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1:
                return None, 400
            if length > MAX_REQUEST:
                return None, 413
            if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/x-www-form-urlencoded':
                return None, 415
            data = parse_qs(self.rfile.read(length).decode('utf-8'), keep_blank_values=True, max_num_fields=20)
            if any(len(values) != 1 for values in data.values()):
                return None, 400
            return {key: values[0] for key, values in data.items()}, 200
        except (ValueError, UnicodeError):
            return None, 400

    def feedback_reply(self, article, message, status=200, values=None, success=False):
        headers = {'Cache-Control': 'private, no-store'}
        if 'application/json' in self.headers.get('Accept', ''):
            encoded = json.dumps({'ok': success, 'message': message}, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'private, no-store')
            self.end_headers()
            self.wfile.write(encoded)
            return
        body = f'<p role="status">{html.escape(message)}</p>'
        if not success and article and self.feedback_secret():
            body += self.feedback_form(article, values)
        if article:
            body += f'<p><a href="{html.escape(article["url"])}">К статье</a></p>'
        self.render_utility_page('Замечание к статье', body, status, headers)

    def handle_article_feedback(self, article):
        self.is_content_page = False
        if not self.feedback_secret():
            self.feedback_reply(article, 'Приём замечаний не настроен.', 503)
            return
        if not self.has_article_access(article):
            self.render_password_page(article, status=403)
            return
        form, status = self.feedback_read_form()
        if form is None:
            self.feedback_reply(article, 'Некорректный или слишком большой запрос.', status)
            return
        if not self.feedback_valid_csrf(form.get('csrf', ''), article['url']):
            self.feedback_reply(article, 'Форма устарела. Обновите страницу и повторите отправку.', 403, form)
            return
        if form.get('website', '').strip():
            self.feedback_reply(article, 'Замечание отправлено.', success=True)
            return
        limits = {'surname': 100, 'first_name': 100, 'telegram': 200, 'message': 4000, 'quote': 1000, 'anchor': 256}
        values = {key: form.get(key, '').strip() for key in limits}
        missing = any(not values[key] for key in ('surname', 'first_name', 'telegram', 'message'))
        invalid = any(len(value) > limits[key] or '\x00' in value for key, value in values.items())
        if missing or invalid or not telegram_handle(values['telegram']):
            self.feedback_reply(article, 'Укажите фамилию, имя, Telegram (@username или https://t.me/username) и замечание. Проверьте длину полей.', 400, form)
            return
        values['telegram'] = telegram_handle(values['telegram'])
        visitor = hashlib.sha256(self.feedback_session().encode('ascii')).hexdigest()
        url = article['url'] + ('#' + quote(values['anchor'], safe='-_') if values['anchor'] else '')
        try:
            with closing(self.feedback_connection()) as db, db:
                db.execute('BEGIN IMMEDIATE')
                count = db.execute('SELECT COUNT(*) FROM feedback WHERE visitor=? AND created>?', (visitor, time.time() - 600)).fetchone()[0]
                if count >= 3:
                    self.feedback_reply(article, 'Слишком много обращений. Повторите через десять минут.', 429, form)
                    return
                db.execute('''INSERT INTO feedback (url,title,quote,surname,first_name,telegram,message,created,visitor)
                    VALUES (?,?,?,?,?,?,?,?,?)''', (url, article['title'], values['quote'], values['surname'], values['first_name'], values['telegram'], values['message'], time.time(), visitor))
        except (OSError, sqlite3.Error):
            self.feedback_reply(article, 'Не удалось сохранить замечание. Попробуйте позже.', 503, form)
            return
        self.feedback_reply(article, 'Замечание отправлено.', success=True)

    def feedback_is_admin(self):
        cookie = self.feedback_cookies().get(ADMIN_COOKIE)
        return bool(self.feedback_secret() and cookie and hmac.compare_digest(cookie.value.encode('utf-8'), self.feedback_sign('admin-session').encode('ascii')))

    def handle_feedback_admin(self, method='GET'):
        self.is_content_page = False
        headers = {'Cache-Control': 'private, no-store', 'X-Frame-Options': 'DENY'}
        if not self.feedback_secret():
            self.render_utility_page('Замечания', '<p>Приём замечаний не настроен.</p>', 503, headers)
            return
        error, status = '', 200
        if method == 'POST':
            form, status = self.feedback_read_form()
            if form is None or not self.feedback_valid_csrf(form.get('csrf', ''), '/admin/feedback'):
                self.render_utility_page('Замечания', '<p>Запрос отклонён. Обновите страницу.</p>', status if form is None else 403, headers)
                return
            action = form.get('action', '')
            if action == 'login':
                visitor = self.feedback_session()
                try:
                    with closing(self.feedback_connection()) as db, db:
                        db.execute('BEGIN IMMEDIATE')
                        db.execute('DELETE FROM admin_attempts WHERE created<?', (time.time() - 600,))
                        attempts = db.execute('SELECT COUNT(*) FROM admin_attempts WHERE visitor=?', (visitor,)).fetchone()[0]
                        if attempts >= 5:
                            error, status = 'Повторите вход через десять минут.', 429
                        elif hmac.compare_digest(form.get('password', '').encode('utf-8'), self.feedback_secret().encode('utf-8')):
                            db.execute('DELETE FROM admin_attempts WHERE visitor=?', (visitor,))
                            self.send_response(303)
                            self.send_header('Location', '/admin/feedback')
                            self.send_header('Cache-Control', 'private, no-store')
                            self.send_header('Set-Cookie', f'{ADMIN_COOKIE}={self.feedback_sign("admin-session")}; Path=/admin; HttpOnly; SameSite=Strict' + self.feedback_secure())
                            self.end_headers()
                            return
                        else:
                            db.execute('INSERT INTO admin_attempts VALUES (?,?)', (visitor, time.time()))
                            error, status = 'Пароль не подошёл.', 403
                except (OSError, sqlite3.Error):
                    error, status = 'Вход временно недоступен.', 503
            elif self.feedback_is_admin():
                if action == 'logout':
                    self.send_response(303)
                    self.send_header('Location', '/admin/feedback')
                    self.send_header('Set-Cookie', f'{ADMIN_COOKIE}=; Path=/admin; Max-Age=0; HttpOnly; SameSite=Strict' + self.feedback_secure())
                    self.end_headers()
                    return
                try:
                    identifier = int(form.get('id', ''))
                    with closing(self.feedback_connection()) as db, db:
                        if action == 'delete':
                            db.execute('DELETE FROM feedback WHERE id=?', (identifier,))
                        elif action in ('close', 'reopen'):
                            db.execute('UPDATE feedback SET status=? WHERE id=?', ('closed' if action == 'close' else 'open', identifier))
                        else:
                            raise ValueError('invalid action')
                except (ValueError, OSError, sqlite3.Error):
                    self.render_utility_page('Замечания', '<p>Не удалось выполнить действие.</p>', 400, headers)
                    return
                self.send_response(303)
                self.send_header('Location', '/admin/feedback')
                self.send_header('Cache-Control', 'private, no-store')
                self.end_headers()
                return
            else:
                error, status = 'Требуется вход.', 403
        token = self.feedback_csrf('/admin/feedback')
        if not self.feedback_is_admin():
            body = f'''<p role="alert">{html.escape(error)}</p><form method="post" class="auth-form">
                <input type="hidden" name="csrf" value="{token}"><input type="hidden" name="action" value="login">
                <label>Пароль администратора<input name="password" type="password" autocomplete="current-password" required></label>
                <button type="submit">Войти</button></form>'''
            self.render_utility_page('Замечания: вход', body, status, headers)
            return
        query = parse_qs(urlparse(self.path).query)
        selected = 'closed' if query.get('status', ['open'])[0] == 'closed' else 'open'
        try:
            page = max(1, min(100000, int(query.get('page', ['1'])[0])))
        except ValueError:
            page = 1
        try:
            with closing(self.feedback_connection()) as db:
                rows = db.execute('SELECT * FROM feedback WHERE status=? ORDER BY created DESC,id DESC LIMIT 51 OFFSET ?', (selected, (page - 1) * 50)).fetchall()
        except (OSError, sqlite3.Error):
            self.render_utility_page('Замечания', '<p>Список временно недоступен.</p>', 503, headers)
            return
        esc = lambda value: html.escape(str(value), quote=True)
        body = f'''<nav class="feedback-filters"><a href="?status=open">Новые</a><a href="?status=closed">Обработанные</a>
            <form method="post"><input type="hidden" name="csrf" value="{token}"><button name="action" value="logout">Выйти</button></form></nav>'''
        for row in rows[:50]:
            action, label = ('close', 'Обработано') if selected == 'open' else ('reopen', 'Открыть снова')
            body += f'''<article class="feedback-entry"><h2><a href="{esc(row['url'])}">{esc(row['title'])}</a></h2>
                <p>{esc(row['surname'])} {esc(row['first_name'])} · <a href="https://t.me/{quote(row['telegram'][1:])}" target="_blank" rel="noopener noreferrer">{esc(row['telegram'])}</a></p>
                <time>{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(row['created']))}</time>
                <blockquote>{esc(row['quote'])}</blockquote><p class="feedback-message">{esc(row['message'])}</p>
                <form method="post" class="feedback-actions"><input type="hidden" name="csrf" value="{token}"><input type="hidden" name="id" value="{row['id']}">
                    <button name="action" value="{action}">{label}</button><button name="action" value="delete" data-confirm="Удалить замечание?">Удалить</button>
                </form></article>'''
        if not rows:
            body += '<p>Замечаний пока нет.</p>'
        body += '<nav class="feedback-pagination">'
        if page > 1:
            body += f'<a href="?status={selected}&page={page-1}">Предыдущая страница</a>'
        if len(rows) > 50:
            body += f'<a href="?status={selected}&page={page+1}">Следующая страница</a>'
        self.render_utility_page('Замечания', body + '</nav>', 200, headers)
