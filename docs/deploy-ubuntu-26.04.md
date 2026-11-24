# Установка knowbase-md 2.0.2 на чистую Ubuntu 26.04

Инструкция рассчитана на **пустой сервер Ubuntu Server 26.04 LTS**, доступ по SSH и собственный домен. Команды на сервере выполняются от `root` в Bash. Для сервера с уже работающими сайтами не удаляйте их конфигурацию: используйте [инструкцию обновления существующей установки](site-guide.md).

Схема работы:

```text
Браузер -> HTTPS :443 -> Nginx -> HTTP 127.0.0.1:8000 -> main.py
```

Python запускается отдельным непривилегированным пользователем через systemd. Порты 80 и 443 занимает Nginx; порт 8000 не открывается наружу. Docker, Gunicorn, Node.js и отдельный сервер базы данных не требуются.

## 1. Домен И Подключение

Укажите в DNS домена A-запись с IPv4 нового сервера. Если есть AAAA-запись, она тоже должна вести на этот сервер; удалите устаревшую AAAA-запись, если IPv6 не используете. В панели хостинга разрешите входящие SSH, HTTP 80 и HTTPS 443.

В локальном PowerShell подключитесь:

```powershell
ssh root@SERVER_IP
```

Замените `SERVER_IP` реальным адресом нового сервера. Далее в этой SSH-консоли:

```bash
DOMAIN=vdn.robo548.ru
EMAIL=you@example.com
```

Замените домен при необходимости и обязательно укажите свой действующий email. Не закрывайте эту SSH-консоль до конца установки: переменные используются в следующих командах. Если подключитесь заново, задайте их повторно.

## 2. Пакеты, Пользователь И Код

```bash
apt update
apt install -y git python3 python3-venv nginx ufw openssl curl snapd
python3 --version

useradd --system --user-group --home-dir /opt/knowbase-md --shell /usr/sbin/nologin knowbase
git clone --branch master https://github.com/vdnrobo/knowbase-md.git /opt/knowbase-md
cd /opt/knowbase-md
git checkout --detach v2.0.2

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

install -d -o root -g knowbase -m 750 articles authors learning-paths
install -d -o knowbase -g knowbase -m 750 data
```

Ветка проекта называется `master`. Переключение на тег `v2.0.2` устанавливает именно этот релиз; detached HEAD здесь ожидаем. Код и виртуальное окружение остаются принадлежащими `root`, пользователь `knowbase` получает право записи только в данные приложения.

Nginx устанавливается из репозитория Ubuntu. Официальное руководство: [установка Nginx](https://ubuntu.com/server/docs/how-to/web-services/install-nginx/).

## 3. Перенос Статей И Другого Контента

**В GitHub нет учебных материалов.** После клонирования категории и статьи автоматически не появятся. Отдельно переносятся:

| Путь | Содержимое |
| --- | --- |
| `articles/` | Категории, статьи, `media/`, `files/` и общий `glossary.json` |
| `authors/` | Профили и фотографии авторов |
| `learning-paths/` | Markdown-файлы учебных маршрутов, если созданы |
| `announcement.md` | Необязательное объявление на главной |
| `data/` | Прежние базы, только если нужна миграция статистики и замечаний |

Не переносите `.venv`, локальный `.env` или тестовый пароль администратора. Если демонстрационная статья нужна на сервере, она переносится вместе с `articles/03-site-manual/`.

Не закрывая SSH, откройте **второе окно локального PowerShell** в директории проекта:

```powershell
Set-Location C:\Users\vdn\PycharmProjects\site
$server = "root@SERVER_IP"
scp -r .\articles .\authors "${server}:/opt/knowbase-md/"
if (Test-Path .\learning-paths) { scp -r .\learning-paths "${server}:/opt/knowbase-md/" }
if (Test-Path .\announcement.md) { scp .\announcement.md "${server}:/opt/knowbase-md/" }
```

Замените `SERVER_IP`. Если нужно перенести только некоторые категории, вместо `articles/` укажите их папки, а `articles/glossary.json` передайте отдельно, если статьи используют определения.

Вернитесь в SSH-консоль и назначьте права:

```bash
cd /opt/knowbase-md
chown -R root:knowbase articles authors learning-paths
chmod -R u=rwX,g=rX,o= articles authors learning-paths
if [ -f announcement.md ]; then
    chown root:knowbase announcement.md
    chmod 640 announcement.md
fi
```

Для полностью новой установки `data/` остаётся пустой: базы создадутся автоматически. Если переносите старые базы, копируйте их при остановленном старом приложении, затем назначьте владельца `knowbase:knowbase`. Они содержат персональные данные, поэтому не публикуйте их и не делайте общедоступными.

## 4. Настройки И Новый Пароль Администратора

Следующий блок создаёт **новый серверный** `.env`. Не выполняйте его поверх уже настроенного `.env`, иначе замените действующие параметры.

```bash
cd /opt/knowbase-md
umask 077
ADMIN_PASSWORD="$(openssl rand -hex 24)"
cat > .env <<EOF
HOST=127.0.0.1
PORT=8000
DATA_DIR=/opt/knowbase-md/data
ADMIN_PASSWORD=${ADMIN_PASSWORD}
ARTICLE_PASSWORD_10_3D=
EOF
chown root:knowbase .env
chmod 640 .env
umask 022
printf 'Пароль администратора: %s\n' "$ADMIN_PASSWORD"
unset ADMIN_PASSWORD
```

Сохраните выведенный пароль в своём менеджере паролей. Он используется на `/admin/feedback` и включает приём замечаний. Если эта функция не нужна, оставьте `ADMIN_PASSWORD=` пустым.

После создания `.env` обязательно возвращается `umask 022`. Это не меняет его права `640`, но позволяет пользователю сервиса читать новые файлы кода при последующих установках зависимостей и обновлениях Git.

При необходимости задайте пароли защищённых категорий:

```bash
nano /opt/knowbase-md/.env
```

Например, категория `articles/10-3D` использует `ARTICLE_PASSWORD_10_3D`, а `articles/05-knowledge-base` — `ARTICLE_PASSWORD_05_KNOWLEDGE_BASE`. Задайте свои уникальные значения, не `change-me`. При пустом или отсутствующем пароле защищённые статьи не откроются; обычные продолжат работать.

## 5. Проверки

```bash
cd /opt/knowbase-md
.venv/bin/python -m py_compile main.py knowledge.py feedback.py learning_paths.py
.venv/bin/python -m unittest discover -s tests
runuser -u knowbase -- .venv/bin/python tools/check_content.py
```

Тесты проверяют движок, а `check_content.py` — именно перенесённые материалы. Утилита ничего не меняет. Ошибки ссылок, изображений или шагов маршрута исправляйте отдельно; в ранее созданных статьях могут оставаться старые адреса. До переноса материалов пустые каталоги дают пустую главную, что само по себе не является ошибкой установки.

## 6. Постоянный Процесс Через Systemd

```bash
cat > /etc/systemd/system/knowbase-md.service <<'EOF'
[Unit]
Description=Knowbase Markdown Site
After=network.target

[Service]
Type=simple
User=knowbase
Group=knowbase
WorkingDirectory=/opt/knowbase-md
ExecStart=/opt/knowbase-md/.venv/bin/python -u /opt/knowbase-md/main.py
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/opt/knowbase-md/data

[Install]
WantedBy=multi-user.target
EOF
chmod 644 /etc/systemd/system/knowbase-md.service
systemctl daemon-reload
systemctl enable --now knowbase-md
systemctl status knowbase-md --no-pager
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/
```

Ожидаемый статус — `active (running)`, HTTP-код — `200`. Здесь используется GET: обработчик приложения не поддерживает HEAD, поэтому `curl -I` для внутреннего порта не подходит.

Если сервис перезапускается с ошибкой:

```bash
journalctl -u knowbase-md -n 80 --no-pager
ss -ltnp 'sport = :8000'
```

При `Address already in use` сначала выясните, кто занимает порт. Не завершайте неизвестные процессы. Если выбираете другой внутренний порт, измените и `.env`, и `proxy_pass` в следующем разделе.

## 7. Nginx И Публичный Домен

```bash
cat > /etc/nginx/sites-available/knowbase-md <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    client_max_body_size 1m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 10s;
        proxy_read_timeout 60s;
    }
}
EOF
chmod 644 /etc/nginx/sites-available/knowbase-md
ln -sfn /etc/nginx/sites-available/knowbase-md /etc/nginx/sites-enabled/knowbase-md
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx
systemctl reload nginx
curl -sS --resolve "${DOMAIN}:80:127.0.0.1" -o /dev/null -w '%{http_code}\n' "http://${DOMAIN}/"
```

Ожидаемый код — `200`. Команда удаления относится только к стандартной ссылке `default` на **пустом сервере**. Не удаляйте конфигурации других сайтов.

Весь трафик идёт через приложение. Не задавайте `root /opt/knowbase-md`: прямое обслуживание директории проекта может раскрыть `.env`, базы или исходные Markdown-файлы, обходя проверки приложения. `X-Forwarded-Proto` задаётся самим Nginx и нужен для корректного `Secure` у cookie администратора и формы замечаний.

## 8. Firewall И HTTPS

Сначала разрешите SSH, **потом** включайте firewall. При нестандартном порте SSH добавьте отдельное правило для него до `ufw enable`. Не закрывайте текущую SSH-сессию, пока не проверите новое подключение.

```bash
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw enable
ufw status
```

Порт 8000 не открывайте. Если у хостинга есть отдельный firewall/security group, разрешите там 80 и 443 тоже. Справочник Ubuntu: [настройка firewall](https://ubuntu.com/server/docs/how-to/security/firewalls/).

До запуска Certbot проверьте, что `http://ваш-домен/` доступен из внешней сети, а DNS уже указывает на новый сервер. Установите Certbot через snap согласно [официальной инструкции для Nginx](https://certbot.eff.org/instructions?ws=nginx&os=snap):

```bash
snap install --classic certbot
/snap/bin/certbot --nginx -d "$DOMAIN" --email "$EMAIL" --agree-tos --non-interactive --redirect
nginx -t
/snap/bin/certbot renew --dry-run
curl -sS -o /dev/null -w '%{http_code}\n' "https://${DOMAIN}/"
```

Ожидаемый код HTTPS — `200`. Certbot включает автоматическое продление сертификата; `renew --dry-run` проверяет процедуру. Не закрывайте 80 после выпуска сертификата: он нужен для проверки домена и перенаправления HTTP на HTTPS.

Если Certbot пишет, что не нашёл server block, проверьте:

```bash
nginx -T
```

В активном конфиге должен быть ровно ваш `server_name`, а ссылка в `sites-enabled` должна указывать на созданный файл. При ошибке проверки домена проверьте A/AAAA и доступность 80 снаружи.

## 9. Финальная Проверка

Откройте `https://ваш-домен/` и проверьте:

1. Главная показывает перенесённые категории, в футере стоит `v2.0.2`.
2. Изображения, скачивание файлов, формулы, код и вкладки отображаются.
3. `/authors` и `/paths` показывают перенесённые профили и маршруты, если они созданы.
4. Защищённая статья требует пароль соответствующей категории.
5. `/admin/feedback` принимает новый серверный пароль; замечания не видны без входа.
6. После перезагрузки сервера systemd поднимает приложение автоматически.

Вложения и медиа публичны по прямым ссылкам, даже если статья защищена. Markdown с HTML публикуют только доверенные администраторы. Парольная защита учебных материалов и формы замечаний не заменяет полноценную систему учётных записей или защиты от атак.

## 10. Последующие Обновления

Первый выпуск закреплён на теге. Для перехода на следующие опубликованные изменения ветки `master`:

```bash
cd /opt/knowbase-md
git status --short
umask 022
git fetch origin
git switch master
git pull --ff-only origin master
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests
runuser -u knowbase -- .venv/bin/python tools/check_content.py
systemctl restart knowbase-md
systemctl status knowbase-md --no-pager
```

Выполняйте рестарт после успешной проверки кода и разбора ошибок контента. Не используйте `git reset --hard` для устранения конфликтов. Контент и настройки сохраняются, поскольку исключены из Git; изменения статей и маршрутов переносятся отдельно. После загрузки новых файлов повторяйте команды назначения владельца и прав из раздела 3.

Общие команды обслуживания:

```bash
systemctl restart knowbase-md
journalctl -u knowbase-md -f
nginx -t
systemctl reload nginx
```

Ctrl+C прекращает просмотр журнала, а не останавливает сайт. Данные `data/` и `.env` содержат чувствительную информацию; сохраняйте их при обслуживании и не публикуйте в репозитории.
