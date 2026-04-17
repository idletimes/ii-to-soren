#!/usr/bin/env python3
"""Streamlit UI for ii-csv-downloader."""

import copy
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
    page_title="II CSV Downloader",
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
    """Run ii_download.py, streaming output into a st.code block. Returns True on success."""
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
    return proc.returncode == 0


# ── Config ────────────────────────────────────────────────────────────────────

config = load_config()


def show_onboarding():
    """Full-page first-time setup wizard shown when config.yaml doesn't exist."""

    CURRENCIES = ["AUD", "CAD", "CHF", "DKK", "EUR", "GBP", "HKD", "JPY", "NOK", "SEK", "SGD", "USD"]

    st.title("📊 Welcome to II Downloader")
    st.info(
        "👋 No config file found yet — let's create one. "
        "Fill in your details below and click **Create Config** to get started."
    )

    if "wiz_cfg" not in st.session_state:
        st.session_state.wiz_cfg = {
            "ii_request_delay": {"min": 1, "max": 3},
            "cgt": {"api_url": "http://localhost:8000"},
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

    # ── Users ─────────────────────────────────────────────────────────────────
    st.subheader("Your Interactive Investor Accounts")
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
        col3.text_input("tradeCGT API URL", value=cfg["cgt"]["api_url"], key="wiz_cgt_url")

    st.divider()

    if st.button("✓ Create Config", type="primary"):
        wiz_sync()

        # Pull advanced settings
        cfg["ii_request_delay"]["min"] = st.session_state.get("wiz_dmin", 1)
        cfg["ii_request_delay"]["max"] = st.session_state.get("wiz_dmax", 3)
        cfg["cgt"]["api_url"] = st.session_state.get("wiz_cgt_url", "http://localhost:8000")

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

        if errors:
            for err in errors:
                st.error(err)
        else:
            with open(CONFIG_FILE, "w") as f:
                yaml.dump(cfg, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            del st.session_state.wiz_cfg
            st.success("✓ Config created — loading the app…")
            st.rerun()


if not config:
    show_onboarding()
    st.stop()

# ── Session state ─────────────────────────────────────────────────────────────

for _key, _default in [("dl_running", False), ("dl_args", []), ("dl_env", {}),
                        ("push_running", False), ("push_args", []), ("push_env", {})]:
    if _key not in st.session_state:
        st.session_state[_key] = _default

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_dl, tab_push, tab_cfg, tab_bm = st.tabs(["📥 Download", "📤 Push to tradeCGT", "⚙️ Config", "🔖 Bookmarklet"])


# ─── Download ─────────────────────────────────────────────────────────────────

with tab_dl:
    st.title("📊 II Downloader")
    st.header("Download from Interactive Investor")

    users = config.get("users", [])
    user_emails = [u["email"] for u in users]

    # Per-user token memory (session only — never written to config)
    if "ii_tokens" not in st.session_state:
        st.session_state.ii_tokens = {}

    col_user, col_token = st.columns([2, 3])
    with col_user:
        selected_user = st.selectbox("User", user_emails, key="selected_user",
                                     disabled=st.session_state.dl_running)

    # When the user selection changes, load that user's stored token
    if st.session_state.get("_prev_user") != selected_user:
        st.session_state["ii_token_input"] = st.session_state.ii_tokens.get(selected_user, "")
        st.session_state["_prev_user"] = selected_user

    def _save_token():
        st.session_state.ii_tokens[st.session_state.selected_user] = st.session_state["ii_token_input"]

    with col_token:
        ii_token = st.text_input(
            "II Bearer Token",
            key="ii_token_input",
            on_change=_save_token,
            placeholder="Paste your token — use the 🔖 Bookmarklet tab to get it",
            disabled=st.session_state.dl_running,
        )

    col_port, col_tx, col_acct = st.columns(3)
    do_portfolio = col_port.checkbox("Portfolio & Cash", value=True, disabled=st.session_state.dl_running)
    do_transactions = col_tx.checkbox("Transactions", value=True, disabled=st.session_state.dl_running)
    account_filter = col_acct.text_input("Account ID (optional)", placeholder="e.g. 0970887",
                                         disabled=st.session_state.dl_running)

    also_push = st.checkbox("Push to tradeCGT after download", value=True,
                            disabled=st.session_state.dl_running)
    cgt_token_dl = ""
    if also_push:
        cgt_token_dl = st.text_input(
            "tradeCGT Bearer Token",
            type="default",
            key="cgt_dl",
            disabled=st.session_state.dl_running,
        )

    with st.expander("Advanced options"):
        to_date = st.date_input(
            "Transaction end date",
            value=date.today() - timedelta(days=1),
            help="Defaults to yesterday to avoid partial-day issues",
            disabled=st.session_state.dl_running,
        )

    if st.button("▶ Run Download", type="primary",
                 disabled=st.session_state.dl_running):
        if not ii_token:
            st.error("Please paste an II bearer token before running.")
            st.stop()
        args = ["--user", selected_user, "--token", ii_token]
        if do_portfolio and not do_transactions:
            args += ["--portfolio"]
        elif do_transactions and not do_portfolio:
            args += ["--transactions"]
        if account_filter:
            args += ["--account", account_filter]
        args += ["--to-date", to_date.isoformat()]
        env_extra = {}
        if also_push:
            args += ["--push"]
            if cgt_token_dl:
                env_extra["CGT_TOKEN"] = cgt_token_dl
        st.session_state.dl_args = args
        st.session_state.dl_env = env_extra
        st.session_state.dl_running = True
        st.rerun()

    if st.session_state.dl_running:
        with st.status("Downloading from Interactive Investor…", expanded=True) as status:
            ok = run_and_stream(st.session_state.dl_args, st.session_state.dl_env)
            status.update(
                label="Download complete ✓" if ok else "Download failed ✗",
                state="complete" if ok else "error",
            )
        st.session_state.dl_running = False
        st.rerun()


# ─── Push ─────────────────────────────────────────────────────────────────────

with tab_push:
    st.header("Push to tradeCGT")

    col_token2, col_acct2 = st.columns([3, 2])
    with col_token2:
        cgt_token = st.text_input(
            "tradeCGT Bearer Token",
            type="default",
            key="cgt_push",
            disabled=st.session_state.push_running,
        )
    with col_acct2:
        account_filter_push = st.text_input(
            "Account ID (optional)",
            placeholder="e.g. 0970887",
            key="acct_push",
            disabled=st.session_state.push_running,
        )

    if st.button("▶ Push", type="primary",
                 disabled=not cgt_token or st.session_state.push_running):
        st.session_state.push_args = ["--push-only"]
        if account_filter_push:
            st.session_state.push_args += ["--account", account_filter_push]
        st.session_state.push_env = {"CGT_TOKEN": cgt_token}
        st.session_state.push_running = True
        st.rerun()

    if st.session_state.push_running:
        with st.status("Pushing to tradeCGT…", expanded=True) as status:
            ok = run_and_stream(st.session_state.push_args, st.session_state.push_env)
            status.update(
                label="Push complete ✓" if ok else "Push failed ✗",
                state="complete" if ok else "error",
            )
        st.session_state.push_running = False
        st.rerun()


# ─── Config ───────────────────────────────────────────────────────────────────

CURRENCIES = ["AUD", "CAD", "CHF", "DKK", "EUR", "GBP", "HKD", "JPY", "NOK", "SEK", "SGD", "USD"]


def sync_form_to_cfg():
    """Collect current widget values from session state into cfg_edit."""
    cfg = st.session_state.cfg_edit
    cfg.setdefault("ii_request_delay", {})["min"] = st.session_state.get("cfg_delay_min", 1)
    cfg["ii_request_delay"]["max"] = st.session_state.get("cfg_delay_max", 3)
    cfg.setdefault("cgt", {})["api_url"] = st.session_state.get("cfg_cgt_url", "")
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
        "tradeCGT API URL",
        value=cfg.get("cgt", {}).get("api_url", ""),
        key="cfg_cgt_url",
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

    # Bookmarklet JS — intercepts both fetch and XHR
    bm_js = (
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

    st.components.v1.html(
        f"""
        <div style="margin:16px 0 8px;">
          <a href="{bm_js}"
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

    with st.expander("View bookmarklet source"):
        st.code(bm_js, language="javascript")
