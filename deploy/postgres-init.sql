-- 使用 PostgreSQL 管理员账号执行，例如：
-- psql -h <host> -U postgres -d postgres \
--   -v app_password='<strong-password>' -f deploy/postgres-init.sql
\set ON_ERROR_STOP on

\if :{?app_password}
\else
\echo '缺少 app_password，请通过 -v app_password=... 传入数据库密码。'
\quit 1
\endif

SELECT format(
    'CREATE ROLE lob_browser LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION',
    :'app_password'
)
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'lob_browser')\gexec

SELECT format(
    'ALTER ROLE lob_browser WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION',
    :'app_password'
)\gexec

SELECT 'CREATE DATABASE lob_browser OWNER lob_browser ENCODING ''UTF8'''
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'lob_browser')\gexec

\connect lob_browser

REVOKE ALL ON DATABASE lob_browser FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE lob_browser TO lob_browser;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO lob_browser;

-- 业务表由 API 服务启动时自动创建。
