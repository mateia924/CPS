# Paths to change the fatma Accountant user's password on live (2026-10-19)

Read-only investigation. Nothing was executed, nothing changed. Live DB was queried only with
`BEGIN READ ONLY` + `default_transaction_read_only=on`. The containers were inspected with
grep/cat/printenv (no values printed). One plain `GET /admin/login/` returned 200.

Target row on live: exactly 1 `accounts_user` row for the Accountant user
(tenant fatma, role Accountant, is_active=t, must_change_password=f).

## 1. Owner resets another user's password from the UI: YES (the only working path)

- Screen: sidebar "rolesAndUsers" -> `/dashboard/roles`, users table, per-row button
  `resetPassword` (`frontend/src/app/dashboard/roles/page.tsx:309-312`). It opens a prompt
  for the new value and calls `POST /api/users/<id>/reset_password/` (page.tsx:134).
- Permission: `roles.manage` (`backend/apps/access/views.py:118`). The sidebar link shows only
  when `me.permissions` includes it (`frontend/src/app/dashboard/layout.tsx:76,289`). The user
  queryset is limited to the caller's own tenant (views.py:127).
- Live has it. `infra-backend-1:/app/apps/access/views.py` and `serializers.py` are identical
  to HEAD (empty diff), and the live frontend bundle contains `reset_password`.
- Who can do it in fatma, live query:

      the first fatma Owner           Owner       has_roles_manage = t
      the second fatma Owner          Owner       has_roles_manage = t
      the Accountant user             Accountant  has_roles_manage = f

- Validation (`access/serializers.py:129-143`): Django's password validators, plus a check
  that the password is not the user's own email.
- WRITES TO THE LIVE TENANT: yes.
  - `accounts_user`: `password` (new hash) and `must_change_password = true`
    (`update_fields`, views.py:207-209). The accountant must choose a new password at next
    login.
  - `invalidate_all_sessions` (`accounts/services.py:126-137`): inserts a
    `token_blacklist_blacklistedtoken` row for every outstanding refresh token of that user,
    and sets `accounts_usersession.revoked_at = now()` on their open sessions. The accountant
    is logged out everywhere.
  - `platform_auditlog`: one row, `action=tenant_user.reset_password`, actor = the Owner,
    target = the accountant, tenant_id = fatma.
  - No accounting table is touched.

## 2. Self-service "forgot password" on live: DOES NOT EXIST on live

It is more than "no mail sent": the code is not deployed. Inside `infra-backend-1`:

    grep -c "class PasswordResetRequestView" /app/apps/accounts/views.py  -> 0
    grep -c "password-reset"                 /app/apps/accounts/urls.py   -> 0
    to_regclass('accounts_passwordresettoken')                             -> (null)

The endpoints, the task and the token table exist only at HEAD (sprint 7.2.9), not on live.
It writes nothing on live today.

The email part is confirmed and matters for the first deploy that ships 7.2.9. In both
`infra-backend-1` and `infra-celery_worker-1`, `EMAIL_HOST` is set but empty and
`CPS_ENVIRONMENT` is unset. So `config/settings.py:445-461` selects
`django.core.mail.backends.console.EmailBackend`, and no mail would be sent. The console
backend writes the whole message to the worker's stdout. That message includes the raw reset
link with its token (`accounts/tasks.py:54-72`), so `docker logs infra-celery_worker-1` would
show it. This contradicts the comment at tasks.py:56-59 ("never logged anywhere"). Current
count of such links in that log is 0 (worker started 2026-10-13 20:46 UTC; the task has never
run there).

What it would write once deployed: delete the user's unused `accounts_passwordresettoken`
rows and insert one new row (request). On confirm: `accounts_user.password`,
`must_change_password=false`, `used_at` on the token row, session invalidation as in 1, and
an audit row `tenant_user.password_reset`.

## 3. Django admin (/admin/): REACHABLE, but NO ONE can log in

- Reachable publicly. Host nginx `/etc/nginx/conf.d/cps.conf` serves `app.cps-oracle.com` and
  `*.app.cps-oracle.com` on 80/443 with `location / -> 127.0.0.1:3000`. The container nginx
  has `location /admin/ -> backend` (`infra/nginx/nginx.conf:72`).
  `GET http://localhost:3000/admin/login/` -> 200.
- Login: an admin login sends no subdomain, and the only backend, `TenantEmailBackend`
  (`accounts/backends.py`), then accepts only `is_superuser=True` users.
  Live `accounts_user` has 0 rows with `is_superuser = t`. Platform users live in a separate
  table (`platform_platformuser`, 1 super_admin) and this backend never authenticates them.
- `is_staff = t` on 50 tenant users (every registered Owner, set at
  `accounts/serializers.py:115`, both fatma Owners included) does NOT open admin. The login
  path above rejects non-superusers before is_staff matters.
- WRITES: nothing today, because there is no account that can use it. Creating a superuser
  to enable this path would itself be a write to live `accounts_user`.

## 4. `manage.py changepassword` in the live backend container: AVAILABLE

- `/app/manage.py` exists, and Django's `contrib/auth/management/commands/changepassword.py`
  ships in the image.
- The container's DATABASE_URL user is `cps` (the table owner). `accounts_user` has RLS
  enabled but not forced, so the owner sees all rows. The lookup
  `_default_manager.get(email=...)` would find the single row. (An email held in two tenants
  would raise MultipleObjectsReturned. Not the case here: 1 row.)
- WRITES TO THE LIVE TENANT: yes, and with less than path 1.
  - It runs `u.set_password(p1); u.save()`, a full-row `save()` with no `update_fields`. All
    columns of that `accounts_user` row are rewritten, with only `password` changed in value.
  - `must_change_password` is not set, so the operator's chosen password stays permanent.
  - No session invalidation: existing refresh tokens keep working.
  - No `platform_auditlog` row.
  - It bypasses the password validators that path 1 enforces. The interactive command runs
    Django's validators but lets the operator override with "y".

## Summary

| Path | On live today | Writes |
|---|---|---|
| 1. Owner UI reset (`/dashboard/roles`, `roles.manage`) | works | user.password, must_change_password=t, token blacklist, sessions revoked, audit row |
| 2. Self-service reset | not deployed | nothing (would log the token link to the worker log, console backend) |
| 3. Django admin | reachable, no superuser can log in | nothing |
| 4. `manage.py changepassword` | available | full-row save of the user, no audit, no session revoke, no forced change |

Path 1 is the only path that is designed, audited and tenant-scoped.
