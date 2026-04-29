#!/usr/bin/env python3
"""Streamlit UI for ii-to-soren."""

import copy
import json
import os
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import streamlit as st
import yaml

CONFIG_FILE = Path("config.yaml")

st.set_page_config(
    page_title="II to Soren",
    page_icon="📊",
    layout="wide",
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_config():
    if not CONFIG_FILE.exists():
        return None
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


def strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def run_and_stream(args, env_extra=None):
    """Run ii_download.py, streaming output into a st.code block.
    Returns (success: bool, log: str)."""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)

    proc = subprocess.Popen(
        [sys.executable, "ii_download.py"] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        cwd=Path(__file__).parent,
    )

    output_box = st.empty()
    lines = []
    for line in proc.stdout:
        lines.append(strip_ansi(line))
        output_box.code("".join(lines), language=None)
    proc.wait()
    return proc.returncode == 0, "".join(lines)


def run_all_users(user_tokens, common_args):
    """Run ii_download.py once per user (sequentially), streaming combined output.
    user_tokens: {email: token}. Returns (all_ok: bool, combined_log: str)."""
    env = os.environ.copy()
    output_box = st.empty()
    all_lines = []
    all_ok = True

    for email, token in user_tokens.items():
        args = ["--user", email, "--token", token] + common_args
        proc = subprocess.Popen(
            [sys.executable, "ii_download.py"] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            cwd=Path(__file__).parent,
        )
        for line in proc.stdout:
            all_lines.append(strip_ansi(line))
            output_box.code("".join(all_lines), language=None)
        proc.wait()
        if proc.returncode != 0:
            all_ok = False

    return all_ok, "".join(all_lines)


# ── Bookmarklet JS (shared between onboarding and the Bookmarklet tab) ────────

BM_JS = (
    "javascript:(function(){"
    "function notify(msg,bg){"
    "var d=document.createElement('div');"
    "d.textContent=msg;"
    "d.style.cssText='position:fixed;top:20px;right:20px;background:'+bg+';color:#fff;"
    "padding:12px 20px;border-radius:8px;font-family:sans-serif;font-size:14px;"
    "font-weight:700;z-index:99999;box-shadow:0 4px 12px rgba(0,0,0,.3)';"
    "document.body.appendChild(d);setTimeout(function(){d.remove()},3000);}"
    "function capture(token){"
    "navigator.clipboard.writeText(token)"
    ".then(function(){notify('\\u2713 II token copied to clipboard!','#22c55e');})"
    ".catch(function(){window.prompt('Copy this token:',token);});}"
    "var _f=window.fetch;"
    "window.fetch=function(r,i){"
    "var res=_f.apply(this,arguments);"
    "try{"
    "var url=(r instanceof Request)?r.url:r;"
    "if(url&&url.includes('api-prod.ii.co.uk')){"
    "var auth=null;"
    "if(r instanceof Request)auth=r.headers.get('Authorization');"
    "else if(i&&i.headers){"
    "if(i.headers instanceof Headers)auth=i.headers.get('Authorization');"
    "else auth=i.headers['Authorization']||i.headers['authorization'];}"
    "if(auth&&auth.startsWith('Bearer '))capture(auth.substring(7));}}"
    "catch(e){}return res;};"
    "var _o=XMLHttpRequest.prototype.open;"
    "var _s=XMLHttpRequest.prototype.setRequestHeader;"
    "XMLHttpRequest.prototype.open=function(m,url){"
    "this._iiurl=url;return _o.apply(this,arguments);};"
    "XMLHttpRequest.prototype.setRequestHeader=function(h,v){"
    "if(this._iiurl&&this._iiurl.includes('api-prod.ii.co.uk')"
    "&&h.toLowerCase()==='authorization'&&v.startsWith('Bearer '))"
    "capture(v.substring(7));"
    "return _s.apply(this,arguments);};"
    "notify('\\u23f3 Waiting for II API request...','#3b82f6');"
    "})();"
)


def render_bookmarklet_button():
    """Render the draggable bookmarklet button."""
    st.components.v1.html(
        f"""
        <div style="margin:16px 0 8px;">
          <a href="{BM_JS}"
             style="display:inline-block;background:#3b82f6;color:white;
                    padding:12px 28px;border-radius:8px;text-decoration:none;
                    font-family:-apple-system,BlinkMacSystemFont,sans-serif;
                    font-size:15px;font-weight:600;
                    box-shadow:0 2px 8px rgba(0,0,0,0.18);cursor:grab;"
             onclick="alert('Drag this button to your bookmarks bar — don\\'t click it on this page!');return false;">
            🔖 Get II Token
          </a>
          <span style="margin-left:14px;font-family:sans-serif;font-size:13px;color:#6b7280;">
            ← drag to your bookmarks bar
          </span>
        </div>
        """,
        height=70,
    )


# ── Config ────────────────────────────────────────────────────────────────────

config = load_config()

# Disable browser autofill on all text inputs (Streamlit exposes no autocomplete param).
# The MutationObserver re-applies it after every Streamlit rerun that swaps DOM nodes.
st.components.v1.html("""
<script>
(function () {
    function patch() {
        try {
            window.parent.document.querySelectorAll('input').forEach(function (el) {
                el.setAttribute('autocomplete', 'off');
            });
        } catch (e) {}
    }
    patch();
    var obs = new MutationObserver(patch);
    try {
        obs.observe(window.parent.document.body, { childList: true, subtree: true });
    } catch (e) {}
})();
</script>
""", height=0)


def show_onboarding():
    """Full-page first-time setup wizard shown when config.yaml doesn't exist."""

    CURRENCIES = ["AUD", "CAD", "CHF", "DKK", "EUR", "GBP", "HKD", "JPY", "NOK", "SEK", "SGD", "USD"]

    st.title("📊 Welcome to II → Soren")
    st.info(
        "👋 No config file found yet — let's create one. "
        "Fill in your details below and click **Create Config** to get started."
    )

    if "wiz_cfg" not in st.session_state:
        st.session_state.wiz_cfg = {
            "ii_request_delay": {"min": 1, "max": 3},
            "cgt": {"api_url": "https://app.getsoren.app"},
            "users": [{"email": "", "accounts": [
                {"id": "", "name": "", "start_date": "2024-01-01", "currencies": ["GBP"]}
            ]}],
        }

    cfg = st.session_state.wiz_cfg

    def wiz_sync():
        """Flush current widget values back into wiz_cfg before structural changes."""
        for i, user in enumerate(cfg["users"]):
            user["email"] = st.session_state.get(f"wu{i}_email", user["email"])
            for j, acct in enumerate(user["accounts"]):
                acct["name"] = st.session_state.get(f"wu{i}_a{j}_name", acct["name"])
                acct["id"] = st.session_state.get(f"wu{i}_a{j}_id", acct["id"])
                acct["start_date"] = st.session_state.get(f"wu{i}_a{j}_start", acct["start_date"])
                acct["currencies"] = st.session_state.get(f"wu{i}_a{j}_cur", acct["currencies"])

    # ── Auto-discovery ────────────────────────────────────────────────────────
    st.subheader("Your Interactive Investor Accounts")

    with st.expander("✨ Auto-discover accounts (recommended)", expanded=not st.session_state.get("wiz_disc_done")):
        st.markdown(
            "Paste your II bearer token to automatically discover your accounts, "
            "start dates, and currencies — no manual config needed. "
            "Takes about 1–2 minutes."
        )
        st.caption(
            "Don't have a token yet? Use the **🔖 Bookmarklet** tab after setup, "
            "or grab one manually: log into ii.co.uk → DevTools → Network → any "
            "request to api-prod.ii.co.uk → copy the Authorization header."
        )

        col_tok, col_btn = st.columns([5, 1])
        col_tok.text_input(
            "II Bearer Token",
            key="wiz_discover_token",
            placeholder="eyJhbGci...",
            label_visibility="collapsed",
        )
        disc_clicked = col_btn.button("🔍 Discover", type="primary", key="wiz_disc_btn")

        if disc_clicked:
            if not st.session_state.get("wiz_discover_token", "").strip():
                st.error("Paste your II bearer token above first.")
            else:
                st.session_state["wiz_disc_running"] = True
                st.rerun()

        # ── Run discovery subprocess ──────────────────────────────────────────
        if st.session_state.get("wiz_disc_running"):
            _disc_token = st.session_state.get("wiz_discover_token", "").strip()
            with st.status("Discovering accounts from Interactive Investor…", expanded=True) as _disc_status:
                _ok, _log = run_and_stream(["--discover", "--token", _disc_token])
                _discovered = None
                for _line in _log.splitlines():
                    _clean = strip_ansi(_line).strip()
                    if _clean.startswith("DISCOVERED:"):
                        try:
                            _discovered = json.loads(_clean[len("DISCOVERED:"):])
                        except Exception:
                            pass
                        break
                if _discovered and _ok:
                    _disc_status.update(
                        label=f"✓ Found {len(_discovered)} account(s)", state="complete"
                    )
                else:
                    _disc_status.update(label="✗ Discovery failed — check token", state="error")

            # Outside the status block — update state and repopulate form
            st.session_state["wiz_disc_running"] = False
            if _discovered and _ok:
                # Clear any previously-rendered account widget values so the
                # form re-renders with the discovered data on the next run
                for _j in range(20):
                    for _sfx in ["name", "id", "start", "cur"]:
                        st.session_state.pop(f"wu0_a{_j}_{_sfx}", None)
                new_accounts = []
                for a in _discovered:
                    acct = {
                        "id": a["id"],
                        "name": a["name"],
                        "start_date": a["start_date"],
                        "currencies": a["currencies"],
                    }
                    if a.get("currency_start_dates"):
                        acct["currency_start_dates"] = a["currency_start_dates"]
                    new_accounts.append(acct)
                cfg["users"][0]["accounts"] = new_accounts
                st.session_state["wiz_disc_done"] = True
            st.rerun()

        # ── Post-discovery status message ─────────────────────────────────────
        if st.session_state.get("wiz_disc_done"):
            n = len(cfg["users"][0].get("accounts", []))
            st.success(
                f"✓ {n} account(s) discovered and pre-filled below. "
                "Review them, enter your email, then click **Create Config**."
            )
            if st.button("🔄 Re-discover", key="wiz_redisc"):
                st.session_state["wiz_disc_done"] = False
                st.session_state["wiz_disc_running"] = True
                st.rerun()

    st.caption("Add each II login you want to include.")

    for i, user in enumerate(cfg["users"]):
        with st.container(border=True):
            col_e, col_del = st.columns([4, 1])
            col_e.text_input("II Login Email", value=user["email"],
                             placeholder="you@example.com", key=f"wu{i}_email")
            if len(cfg["users"]) > 1 and col_del.button("Remove", key=f"wiz_del_user_{i}"):
                wiz_sync()
                cfg["users"].pop(i)
                st.rerun()

            st.caption("**Accounts**")
            for j, acct in enumerate(user["accounts"]):
                col_n, col_id, col_d, col_cur, col_a = st.columns([2, 2, 2, 4, 1])
                col_n.text_input("Name", value=acct["name"],
                                 placeholder="ISA", key=f"wu{i}_a{j}_name")
                col_id.text_input("Account ID", value=acct["id"],
                                  placeholder="1234567",
                                  help="7-digit account number from ii.co.uk",
                                  key=f"wu{i}_a{j}_id")
                col_d.text_input("Start Date", value=acct["start_date"],
                                 placeholder="YYYY-MM-DD",
                                 help="Earliest date to pull transactions from. It doesn't matter if you set this too early, but try not to set it too late.",
                                 key=f"wu{i}_a{j}_start")
                col_cur.multiselect("Currencies", CURRENCIES,
                                    default=acct["currencies"], key=f"wu{i}_a{j}_cur")
                col_a.markdown("<br>", unsafe_allow_html=True)
                if len(user["accounts"]) > 1 and col_a.button("🗑", key=f"wiz_del_acct_{i}_{j}",
                                                               help="Remove account"):
                    wiz_sync()
                    user["accounts"].pop(j)
                    st.rerun()

            if st.button("＋ Add Account", key=f"wiz_add_acct_{i}"):
                wiz_sync()
                user["accounts"].append({"id": "", "name": "",
                                         "start_date": str(date.today()),
                                         "currencies": ["GBP"]})
                st.rerun()

    if st.button("＋ Add another II login"):
        wiz_sync()
        cfg["users"].append({"email": "", "accounts": [
            {"id": "", "name": "", "start_date": str(date.today()), "currencies": ["GBP"]}
        ]})
        st.rerun()

    # ── Global settings (collapsed by default — defaults are fine for most) ───
    with st.expander("⚙️ Advanced Settings"):
        st.caption("The defaults work for most setups — only change these if needed.")
        col1, col2, col3 = st.columns([1, 1, 3])
        col1.number_input("Request delay min (s)", min_value=0, max_value=60,
                          value=int(cfg["ii_request_delay"]["min"]), key="wiz_dmin")
        col2.number_input("Request delay max (s)", min_value=0, max_value=60,
                          value=int(cfg["ii_request_delay"]["max"]), key="wiz_dmax")
        col3.text_input("Soren API URL", value=cfg["cgt"]["api_url"], key="wiz_cgt_url")
        st.text_input("Soren API Key (optional — saves re-pasting each time)",
                      value=cfg["cgt"].get("api_key", ""), key="wiz_cgt_key")

    # Render validation errors from previous submit attempt (above the button)
    for err in st.session_state.get("wiz_errors", []):
        st.error(err)

    st.divider()

    if st.button("✓ Create Config", type="primary"):
        wiz_sync()

        # Pull advanced settings
        cfg["ii_request_delay"]["min"] = st.session_state.get("wiz_dmin", 1)
        cfg["ii_request_delay"]["max"] = st.session_state.get("wiz_dmax", 3)
        cfg["cgt"]["api_url"] = st.session_state.get("wiz_cgt_url", "https://app.getsoren.app")
        key = st.session_state.get("wiz_cgt_key", "").strip()
        if key:
            cfg["cgt"]["api_key"] = key
        else:
            cfg["cgt"].pop("api_key", None)

        # Validate
        errors = []
        for i, user in enumerate(cfg["users"]):
            label = user["email"] or f"User {i + 1}"
            if not user["email"]:
                errors.append(f"**{label}**: email is required")
            for j, acct in enumerate(user["accounts"]):
                alabel = acct["name"] or f"Account {j + 1}"
                if not acct["id"]:
                    errors.append(f"**{label} / {alabel}**: account ID is required")
                if not acct["start_date"]:
                    errors.append(f"**{label} / {alabel}**: start date is required")
                if not acct["currencies"]:
                    errors.append(f"**{label} / {alabel}**: select at least one currency")

        st.session_state["wiz_errors"] = errors
        if errors:
            st.rerun()
        else:
            with open(CONFIG_FILE, "w") as f:
                yaml.dump(cfg, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            del st.session_state.wiz_cfg
            st.session_state["wiz_step"] = 2
            st.rerun()


def show_bookmarklet_step():
    """Step 2 of onboarding: explain and set up the bookmarklet."""
    st.title("📊 One last thing — getting your token")
    st.success("✓ Config saved! You're nearly ready.")

    st.markdown("""
When you download from Interactive Investor, the app needs to prove it's really you.
II does this with a short-lived access code — called a **bearer token** — that it issues
when you log in. It's a bit like a temporary visitor pass: valid for about 30 minutes,
then it expires and you need a fresh one.

Getting this code manually means digging through browser developer tools, which isn't fun.
The **Get II Token** bookmarklet is a one-click shortcut that handles it for you:

- **Save it once** — drag the button below to your browser's bookmarks bar
- **Use it each time** — click it while you're on ii.co.uk, navigate anywhere on the site,
  and it quietly copies your token to the clipboard the moment it spots it
- **Paste and go** — come back here and paste it into the token field in the Download tab

Nothing is sent anywhere. The token never leaves your browser.
""")

    st.info(
        "**To show your bookmarks bar:** "
        "**Mac** — ⌘ Cmd + Shift + B  ·  "
        "**Windows/Linux** — Ctrl + Shift + B"
    )

    render_bookmarklet_button()

    st.divider()

    if st.button("✓ Done — take me to the app", type="primary"):
        st.session_state.pop("wiz_step", None)
        st.rerun()

    st.caption("You can always find this button again in the 🔖 Bookmarklet tab.")


if not config:
    show_onboarding()
    st.stop()

if st.session_state.get("wiz_step") == 2:
    show_bookmarklet_step()
    st.stop()

# ── Session state ─────────────────────────────────────────────────────────────

for _key, _default in [
    ("dl_running", False), ("dl_user_tokens", {}), ("dl_common_args", []),
    ("dl_last_ok", None), ("dl_last_log", ""),
    ("push_running", False), ("push_args", []), ("push_env", {}),
    ("push_last_ok", None), ("push_last_log", ""),
    ("ii_tokens", {}),
]:
    if _key not in st.session_state:
        st.session_state[_key] = _default

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_dl, tab_push, tab_cfg, tab_bm = st.tabs(["📥 Download", "📤 Push to Soren", "⚙️ Config", "🔖 Bookmarklet"])


# ─── Download ─────────────────────────────────────────────────────────────────

with tab_dl:
    st.title("📊 II → Soren")
    st.header("Download from Interactive Investor")

    _dl_users = config.get("users", [])

    # ── Options ───────────────────────────────────────────────────────────────

    # Account dropdown — all accounts across all users, deduped by ID
    _dl_acct_map = {"All": None}
    _dl_seen: set = set()
    for _u in _dl_users:
        for _a in _u.get("accounts", []):
            if _a["id"] not in _dl_seen:
                _dl_acct_map[f"{_a.get('name', _a['id'])} ({_a['id']})"] = _a["id"]
                _dl_seen.add(_a["id"])

    col_port, col_tx, col_acct = st.columns(3)
    do_portfolio    = col_port.checkbox("Portfolio & Cash", value=True, disabled=st.session_state.dl_running)
    do_transactions = col_tx.checkbox("Transactions",       value=True, disabled=st.session_state.dl_running)
    _dl_acct_sel    = col_acct.selectbox("Account", list(_dl_acct_map.keys()), disabled=st.session_state.dl_running)
    account_filter  = _dl_acct_map[_dl_acct_sel]

    _cgt_key = config.get("cgt", {}).get("api_key", "")
    col_push, col_create = st.columns(2)
    also_push = col_push.checkbox(
        "Push to Soren after download",
        value=bool(_cgt_key),
        disabled=st.session_state.dl_running or not _cgt_key,
        help=None if _cgt_key else "Add a Soren API key in ⚙️ Config to enable this",
    )
    dl_create_accounts = col_create.checkbox(
        "Create missing Soren accounts",
        value=True,
        disabled=st.session_state.dl_running or not _cgt_key or not also_push,
        help="If an account exists in your II config but not yet in Soren, create it automatically",
    )
    if not _cgt_key:
        st.info("💡 Add a Soren API key in the **⚙️ Config** tab to enable pushing after download.")

    with st.expander("Advanced options"):
        to_date = st.date_input(
            "Transaction end date",
            value=date.today(),
            help="Defaults to today. The current-year file is always refreshed on the next run, so downloading today's transactions is safe.",
            disabled=st.session_state.dl_running,
        )

    # ── Per-user token inputs ─────────────────────────────────────────────────

    st.divider()
    for _u in _dl_users:
        _email = _u["email"]
        _tok_key = f"ii_tok_{_email}"
        col_e, col_t = st.columns([2, 3])
        col_e.markdown(f"**{_email}**")

        def _make_save(_e=_email, _k=_tok_key):
            def _cb(): st.session_state.ii_tokens[_e] = st.session_state[_k]
            return _cb

        col_t.text_input(
            "II Bearer Token",
            value=st.session_state.ii_tokens.get(_email, ""),
            key=_tok_key,
            on_change=_make_save(),
            placeholder="Paste token — use the 🔖 Bookmarklet tab",
            label_visibility="collapsed",
            disabled=st.session_state.dl_running,
        )

    # ── Run ───────────────────────────────────────────────────────────────────

    if st.session_state.get("dl_error"):
        st.error(st.session_state.dl_error)
        st.session_state.dl_error = ""

    if st.button("▶ Run Download", type="primary", disabled=st.session_state.dl_running):
        # Collect users that have a token
        _user_tokens = {
            _u["email"]: st.session_state.ii_tokens.get(_u["email"], "")
            for _u in _dl_users
            if st.session_state.ii_tokens.get(_u["email"], "")
        }
        if not _user_tokens:
            st.session_state.dl_error = "Paste at least one II bearer token above."
            st.rerun()
        common = []
        if do_portfolio and not do_transactions:
            common += ["--portfolio"]
        elif do_transactions and not do_portfolio:
            common += ["--transactions"]
        if account_filter:
            common += ["--account", account_filter]
        common += ["--to-date", to_date.isoformat()]
        if also_push and _cgt_key:
            common += ["--push"]
            if dl_create_accounts:
                common += ["--create-accounts"]
        st.session_state.dl_user_tokens = _user_tokens
        st.session_state.dl_common_args = common
        st.session_state.dl_running = True
        st.rerun()

    if st.session_state.dl_running:
        with st.status("Downloading from Interactive Investor…", expanded=True) as status:
            ok, log = run_all_users(st.session_state.dl_user_tokens, st.session_state.dl_common_args)
            status.update(
                label="Download complete ✓" if ok else "Download failed ✗",
                state="complete" if ok else "error",
            )
        st.session_state.dl_running = False
        st.session_state.dl_last_ok = ok
        st.session_state.dl_last_log = log
        st.rerun()

    if st.session_state.dl_last_ok is not None:
        if st.session_state.dl_last_ok:
            st.success("✓ Download completed successfully")
        else:
            st.error("✗ Download failed — see logs below")
        with st.expander("View logs"):
            st.code(st.session_state.dl_last_log, language=None)


# ─── Push ─────────────────────────────────────────────────────────────────────

with tab_push:
    st.header("Push to Soren")

    # Account dropdown — options from all users in config (deduped by ID)
    _push_acct_map = {"All": None}
    _seen_ids: set = set()
    for _u in config.get("users", []):
        for _a in _u.get("accounts", []):
            if _a["id"] not in _seen_ids:
                _push_acct_map[f"{_a.get('name', _a['id'])} ({_a['id']})"] = _a["id"]
                _seen_ids.add(_a["id"])

    _push_cgt_key = config.get("cgt", {}).get("api_key", "")
    if not _push_cgt_key:
        st.info("💡 Add a Soren API key in the **⚙️ Config** tab to enable pushing.")

    col_acct_push, col_create_push = st.columns(2)
    _push_acct_sel = col_acct_push.selectbox("Account", list(_push_acct_map.keys()),
                                              key="acct_push",
                                              disabled=st.session_state.push_running)
    account_filter_push = _push_acct_map[_push_acct_sel]
    push_create_accounts = col_create_push.checkbox(
        "Create missing Soren accounts",
        value=True,
        disabled=not _push_cgt_key or st.session_state.push_running,
        help="If an account exists locally but not yet in Soren, create it automatically",
        key="push_create_accounts",
    )

    if st.button("▶ Push", type="primary",
                 disabled=not _push_cgt_key or st.session_state.push_running):
        st.session_state.push_args = ["--push-only"]
        if account_filter_push:
            st.session_state.push_args += ["--account", account_filter_push]
        if push_create_accounts:
            st.session_state.push_args += ["--create-accounts"]
        st.session_state.push_env = {}
        st.session_state.push_running = True
        st.rerun()

    if st.session_state.push_running:
        with st.status("Pushing to Soren…", expanded=True) as status:
            ok, log = run_and_stream(st.session_state.push_args, st.session_state.push_env)
            status.update(
                label="Push complete ✓" if ok else "Push failed ✗",
                state="complete" if ok else "error",
            )
        st.session_state.push_running = False
        st.session_state.push_last_ok = ok
        st.session_state.push_last_log = log
        st.rerun()

    if st.session_state.push_last_ok is not None:
        if st.session_state.push_last_ok:
            st.success("✓ Push completed successfully")
        else:
            st.error("✗ Push failed — see logs below")
        with st.expander("View logs"):
            st.code(st.session_state.push_last_log, language=None)


# ─── Config ───────────────────────────────────────────────────────────────────

CURRENCIES = ["AUD", "CAD", "CHF", "DKK", "EUR", "GBP", "HKD", "JPY", "NOK", "SEK", "SGD", "USD"]


def sync_form_to_cfg():
    """Collect current widget values from session state into cfg_edit."""
    cfg = st.session_state.cfg_edit
    cfg.setdefault("ii_request_delay", {})["min"] = st.session_state.get("cfg_delay_min", 1)
    cfg["ii_request_delay"]["max"] = st.session_state.get("cfg_delay_max", 3)
    cfg.setdefault("cgt", {})["api_url"] = st.session_state.get("cfg_cgt_url", "")
    _key = st.session_state.get("cfg_cgt_key", "").strip()
    if _key:
        cfg["cgt"]["api_key"] = _key
    else:
        cfg["cgt"].pop("api_key", None)
    for i, user in enumerate(cfg.get("users", [])):
        user["email"] = st.session_state.get(f"u{i}_email", user.get("email", ""))
        for j, acct in enumerate(user.get("accounts", [])):
            acct["name"] = st.session_state.get(f"u{i}_a{j}_name", acct.get("name", ""))
            acct["id"] = st.session_state.get(f"u{i}_a{j}_id", acct.get("id", ""))
            acct["start_date"] = st.session_state.get(f"u{i}_a{j}_start", acct.get("start_date", ""))
            acct["currencies"] = st.session_state.get(f"u{i}_a{j}_cur", acct.get("currencies", ["GBP"]))


with tab_cfg:
    st.header("Configuration")

    if "cfg_edit" not in st.session_state:
        st.session_state.cfg_edit = copy.deepcopy(config)

    cfg = st.session_state.cfg_edit

    # ── Global settings ───────────────────────────────────────────────────────
    st.subheader("Global Settings")
    col1, col2, col3 = st.columns([1, 1, 3])
    col1.number_input(
        "Request delay min (s)", min_value=0, max_value=60,
        value=int(cfg.get("ii_request_delay", {}).get("min", 1)),
        key="cfg_delay_min",
    )
    col2.number_input(
        "Request delay max (s)", min_value=0, max_value=60,
        value=int(cfg.get("ii_request_delay", {}).get("max", 3)),
        key="cfg_delay_max",
    )
    col3.text_input(
        "Soren API URL",
        value=cfg.get("cgt", {}).get("api_url", ""),
        key="cfg_cgt_url",
    )
    st.text_input(
        "Soren API Key",
        value=cfg.get("cgt", {}).get("api_key", ""),
        key="cfg_cgt_key",
        help="Long-lived API key — stored in config.yaml (which is gitignored)",
    )

    # ── Users & accounts ──────────────────────────────────────────────────────
    st.subheader("Users & Accounts")

    for i, user in enumerate(cfg.get("users", [])):
        with st.expander(f"👤  {user.get('email', 'New User')}", expanded=True):
            col_e, col_del = st.columns([4, 1])
            col_e.text_input("Email", value=user.get("email", ""), key=f"u{i}_email")
            if col_del.button("🗑 Remove user", key=f"del_user_{i}"):
                sync_form_to_cfg()
                cfg["users"].pop(i)
                st.rerun()

            st.caption("**Accounts**")

            for j, acct in enumerate(user.get("accounts", [])):
                with st.container(border=True):
                    col_n, col_id, col_d, col_cur, col_a = st.columns([2, 2, 2, 4, 1])
                    col_n.text_input(
                        "Name", value=acct.get("name", ""), key=f"u{i}_a{j}_name"
                    )
                    col_id.text_input(
                        "Account ID", value=acct.get("id", ""), key=f"u{i}_a{j}_id"
                    )
                    col_d.text_input(
                        "Start date", value=acct.get("start_date", ""),
                        placeholder="YYYY-MM-DD", key=f"u{i}_a{j}_start",
                        help="Earliest date to pull transactions from. It doesn't matter if you set this too early, but try not to set it too late.",
                    )
                    col_cur.multiselect(
                        "Currencies", CURRENCIES,
                        default=acct.get("currencies", ["GBP"]),
                        key=f"u{i}_a{j}_cur",
                    )
                    col_a.markdown("<br>", unsafe_allow_html=True)
                    if col_a.button("🗑", key=f"del_acct_{i}_{j}", help="Remove account"):
                        sync_form_to_cfg()
                        user["accounts"].pop(j)
                        st.rerun()

            if st.button("＋ Add Account", key=f"add_acct_{i}"):
                sync_form_to_cfg()
                user["accounts"].append({
                    "id": "", "name": "",
                    "start_date": str(date.today()),
                    "currencies": ["GBP"],
                })
                st.rerun()

    if st.button("＋ Add User"):
        sync_form_to_cfg()
        cfg["users"].append({"email": "", "accounts": []})
        st.rerun()

    st.divider()

    col_save, col_reset, _ = st.columns([2, 2, 8])

    if col_save.button("💾 Save Config", type="primary"):
        sync_form_to_cfg()
        with open(CONFIG_FILE, "w") as f:
            yaml.dump(
                st.session_state.cfg_edit, f,
                default_flow_style=False, sort_keys=False, allow_unicode=True,
            )
        st.success("✓ Config saved")
        del st.session_state.cfg_edit   # reload from file on next run
        st.rerun()

    if col_reset.button("↺ Reset from file"):
        del st.session_state.cfg_edit
        st.rerun()


# ─── Bookmarklet ──────────────────────────────────────────────────────────────

with tab_bm:
    st.header("🔖 II Token Bookmarklet")

    st.markdown("""
The bookmarklet patches your browser's network layer to intercept the next request
to Interactive Investor's API and copy the bearer token to your clipboard automatically —
no digging through DevTools required.

**One-time setup:**
1. Make sure your bookmarks bar is visible — **Cmd+Shift+B** (Mac) / **Ctrl+Shift+B** (Windows)
2. Drag the button below onto your bookmarks bar

**Each time you need a fresh token:**
1. Log into [ii.co.uk](https://www.ii.co.uk/) in your browser
2. Click **Get II Token** in your bookmarks bar — a blue banner appears
3. Navigate anywhere on the site (e.g. click your portfolio)
4. The banner turns green: **token copied ✓**
5. Come back here and paste into the token field above
""")

    render_bookmarklet_button()

    with st.expander("View bookmarklet source"):
        st.code(BM_JS, language="javascript")
