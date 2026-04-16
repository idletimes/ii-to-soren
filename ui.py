#!/usr/bin/env python3
"""Streamlit UI for ii-csv-downloader."""

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

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("📊 II Downloader")
    st.divider()
    if config:
        st.success("✓ config.yaml loaded")
        for u in config.get("users", []):
            accts = u.get("accounts", [])
            st.caption(f"**{u['email']}**  \n{len(accts)} account{'s' if len(accts) != 1 else ''}")
    else:
        st.error("config.yaml not found")
        st.info("Copy config.example.yaml → config.yaml and fill in your details.")
        st.stop()

# ── Session state ─────────────────────────────────────────────────────────────

for _key, _default in [("dl_running", False), ("dl_args", []), ("dl_env", {}),
                        ("push_running", False), ("push_args", []), ("push_env", {})]:
    if _key not in st.session_state:
        st.session_state[_key] = _default

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_dl, tab_push, tab_bm = st.tabs(["📥 Download", "📤 Push to tradeCGT", "🔖 Bookmarklet"])


# ─── Download ─────────────────────────────────────────────────────────────────

with tab_dl:
    st.header("Download from Interactive Investor")

    users = config.get("users", [])
    user_emails = [u["email"] for u in users]

    col_token, col_user = st.columns([3, 2])
    with col_token:
        ii_token = st.text_input(
            "II Bearer Token",
            type="default",
            placeholder="Paste your token here — use the 🔖 Bookmarklet tab to get it",
            disabled=st.session_state.dl_running,
        )
    with col_user:
        selected_user = st.selectbox("User", user_emails, disabled=st.session_state.dl_running)

    col_port, col_tx, col_acct = st.columns(3)
    do_portfolio = col_port.checkbox("Portfolio & Cash", value=True, disabled=st.session_state.dl_running)
    do_transactions = col_tx.checkbox("Transactions", value=True, disabled=st.session_state.dl_running)
    account_filter = col_acct.text_input("Account ID (optional)", placeholder="e.g. 0970887",
                                         disabled=st.session_state.dl_running)

    with st.expander("Advanced options"):
        to_date = st.date_input(
            "Transaction end date",
            value=date.today() - timedelta(days=1),
            help="Defaults to yesterday to avoid partial-day issues",
            disabled=st.session_state.dl_running,
        )
        also_push = st.checkbox("Push to tradeCGT immediately after download",
                                disabled=st.session_state.dl_running)
        cgt_token_dl = ""
        if also_push:
            cgt_token_dl = st.text_input(
                "tradeCGT Bearer Token",
                type="default",
                key="cgt_dl",
                disabled=st.session_state.dl_running,
            )

    if st.button("▶ Run Download", type="primary",
                 disabled=not ii_token or st.session_state.dl_running):
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
