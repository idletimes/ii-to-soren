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

st.html(
    """
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
      html, body, [class*="st-"], .stApp, button, input, textarea, select,
      .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6,
      .stMarkdown, .stMarkdown * {
        font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
      }
      [data-testid="stIconMaterial"],
      [data-testid="stIconMaterial"] * {
        font-family: 'Material Symbols Rounded', 'Material Symbols Outlined', 'Material Icons' !important;
      }
      .stApp { background: #f8fafc; color: #0f1f3d; }
      .stApp h1, .stApp h2, .stApp h3, .stApp h4 {
        color: #0f1f3d !important;
        letter-spacing: -0.01em;
        font-weight: 600 !important;
      }
      .stApp h1 { font-weight: 700 !important; }
      a, a:visited { color: #0f766e; }
      a:hover { color: #115e59; }

      .stButton > button[kind="primary"],
      .stDownloadButton > button[kind="primary"],
      .stFormSubmitButton > button[kind="primary"] {
        background: #0f766e;
        border: 1px solid #0f766e;
        color: #ffffff;
        border-radius: 0.5rem;
        font-weight: 500;
      }
      .stButton > button[kind="primary"]:hover,
      .stDownloadButton > button[kind="primary"]:hover,
      .stFormSubmitButton > button[kind="primary"]:hover {
        background: #115e59;
        border-color: #115e59;
        color: #ffffff;
      }
      .stButton > button[kind="secondary"],
      .stDownloadButton > button[kind="secondary"] {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        color: #0f1f3d;
        border-radius: 0.5rem;
        font-weight: 500;
      }
      .stButton > button[kind="secondary"]:hover,
      .stDownloadButton > button[kind="secondary"]:hover {
        border-color: #0f766e;
        color: #0f766e;
      }

      .stTabs [data-baseweb="tab-list"] { gap: 1.75rem; border-bottom: 1px solid #e2e8f0; }
      .stTabs [data-baseweb="tab"] { color: #475569; padding-left: 0.25rem; padding-right: 0.25rem; }
      .stTabs [aria-selected="true"] { color: #0f766e !important; }
      .stTabs [data-baseweb="tab-highlight"] { background-color: #0f766e !important; }

      .stTextInput input, .stNumberInput input, .stDateInput input,
      .stTextArea textarea, .stSelectbox div[data-baseweb="select"] > div,
      .stMultiSelect div[data-baseweb="select"] > div {
        border-radius: 0.375rem;
        border-color: #e2e8f0;
      }
      .stTextInput input:focus, .stNumberInput input:focus, .stDateInput input:focus,
      .stTextArea textarea:focus {
        border-color: #0f766e;
        box-shadow: 0 0 0 1px #0f766e;
      }

      [data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 0.75rem;
        border-color: #e2e8f0 !important;
        background: #ffffff;
      }

      .stCode, pre, code {
        background: #f1f5f9 !important;
        color: #0f1f3d !important;
        border-radius: 0.375rem;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace !important;
      }

      .stAlert { border-radius: 0.5rem; border: 1px solid #e2e8f0; }
      div[data-baseweb="notification"] { border-radius: 0.5rem; }

      hr { border-color: #e2e8f0 !important; }

      .stCaption, [data-testid="stCaptionContainer"] { color: #64748b; }
    </style>
    """
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_config():
    if not CONFIG_FILE.exists():
        return None
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


def strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def extract_errors(log):
    """Pull failure lines out of a run log so they can be surfaced above the
    full log instead of being buried in it. Returns a list of short strings.

    The CLI's Summary / Push Summary blocks already emit one deduplicated
    `[FAIL] ...` line per failed item — those are authoritative, so we prefer
    them. We only fall back to inline markers (a crashed subprocess, a failed
    discovery) when no summary block was reached."""
    fails, inline = [], []
    for raw in log.splitlines():
        line = strip_ansi(raw).strip()
        if not line:
            continue
        if line.startswith("[FAIL]"):
            fails.append(line[len("[FAIL]"):].strip())
        elif line.endswith("delete failed") or "failed — skipping" in line:
            inline.append(line)
        elif line.startswith("Discovery failed") or "discovery failed for" in line:
            inline.append(line)
        elif line.startswith("CGT API error") or line.startswith("CGT API unreachable"):
            # Fatal before any summary block is reached — the push aborts here.
            inline.append(line)
        elif line.startswith("Traceback (most recent call last)"):
            inline.append("Unhandled error — see traceback in logs")
    result = fails if fails else inline
    seen, out = set(), []
    for e in result:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def render_run_result(ok, log, label):
    """Render the outcome of a run: a success/error banner, an error summary
    lifted out of the log when something failed, then the full log."""
    if ok:
        st.success(f"✓ {label} completed successfully")
        with st.expander("View logs"):
            st.code(log, language=None)
        return

    errs = extract_errors(log)
    if errs:
        count = f"{len(errs)} issue{'s' if len(errs) != 1 else ''}"
        st.error(
            f"✗ {label} failed — {count}:\n\n"
            + "\n".join(f"- `{e}`" for e in errs)
        )
    else:
        st.error(f"✗ {label} failed — see logs below")
    with st.expander("View logs", expanded=True):
        st.code(log, language=None)


def run_and_stream(args, env_extra=None, show_push_counter=False):
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

    counter_box = st.empty() if show_push_counter else None
    output_box = st.empty()
    lines = []
    files_pushed = 0
    current_user = ""

    for line in proc.stdout:
        clean = strip_ansi(line)
        lines.append(clean)
        if show_push_counter:
            stripped = clean.strip()
            if "pushed" in stripped:
                files_pushed += 1
            if stripped.startswith("Pushing:"):
                current_user = stripped.removeprefix("Pushing:").strip()
            counter_box.caption(
                f"📤 **{files_pushed} file{'s' if files_pushed != 1 else ''} pushed**" +
                (f" — {current_user}" if current_user else "")
            )
        output_box.code("".join(lines), language=None)
    proc.wait()
    return proc.returncode == 0, "".join(lines)


def run_all_users(user_tokens, common_args):
    """Run ii_download.py once per user (sequentially), streaming combined output.
    user_tokens: {email: token}. Returns (all_ok: bool, combined_log: str)."""
    env = os.environ.copy()
    counter_box = st.empty()
    output_box = st.empty()
    all_lines = []
    all_ok = True
    files_saved = 0
    current_op = ""

    def update_counter():
        counter_box.caption(f"📥 **{files_saved} file{'s' if files_saved != 1 else ''} processed**" +
                            (f" — {current_op}" if current_op else ""))

    def _load_cfg():
        if not CONFIG_FILE.exists():
            return {}
        with open(CONFIG_FILE) as f:
            return yaml.safe_load(f) or {}

    def _save_cfg(c):
        with open(CONFIG_FILE, "w") as f:
            yaml.dump(c, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    auto_discover = _load_cfg().get("auto_discover", True)

    for email, token in user_tokens.items():
        if auto_discover:
            current_op = f"discovering accounts — {email}"
            update_counter()
            disc_proc = subprocess.Popen(
                [sys.executable, "ii_download.py", "--discover", "--token", token],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                cwd=Path(__file__).parent,
            )
            discovered = None
            for line in disc_proc.stdout:
                clean = strip_ansi(line)
                stripped = clean.strip()
                if stripped.startswith("DISCOVERED:"):
                    try:
                        discovered = json.loads(stripped[len("DISCOVERED:"):])
                    except Exception:
                        pass
                    continue
                all_lines.append(clean)
                output_box.code("".join(all_lines), language=None)
            disc_proc.wait()
            if disc_proc.returncode == 0 and discovered is not None:
                cfg_now = _load_cfg()
                changed = False
                for u in cfg_now.get("users", []):
                    if u.get("email") == email:
                        existing_ids = {a.get("id") for a in u.get("accounts", [])}
                        for a in discovered:
                            if a["id"] in existing_ids:
                                continue
                            acct = {"id": a["id"], "name": a["name"],
                                    "start_date": a["start_date"],
                                    "currencies": a["currencies"]}
                            if a.get("currency_start_dates"):
                                acct["currency_start_dates"] = a["currency_start_dates"]
                            u.setdefault("accounts", []).append(acct)
                            changed = True
                            all_lines.append(f"  → new account discovered: {acct['name']} ({acct['id']})\n")
                        break
                if changed:
                    _save_cfg(cfg_now)
                    all_lines.append(f"  → config.yaml updated with new accounts for {email}\n")
                output_box.code("".join(all_lines), language=None)
            else:
                all_lines.append(f"  → discovery failed for {email} — continuing with existing accounts\n")
                output_box.code("".join(all_lines), language=None)

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
            clean = strip_ansi(line)
            all_lines.append(clean)
            stripped = clean.strip()
            if "saved →" in clean:
                files_saved += 1
            elif "pushed" in stripped:
                files_saved += 1
            if stripped.startswith("Downloading ") or stripped.startswith("Transactions "):
                current_op = stripped.split("...")[0].strip()
            elif stripped.startswith("Pushing:"):
                current_op = "pushing to Soren — " + stripped.removeprefix("Pushing:").strip()
            update_counter()
            output_box.code("".join(all_lines), language=None)
        proc.wait()
        if proc.returncode != 0:
            all_ok = False

    update_counter()
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
    """Multi-step first-time setup wizard shown when config.yaml doesn't exist."""

    CURRENCIES = ["AUD", "CAD", "CHF", "DKK", "EUR", "GBP", "HKD", "JPY", "NOK", "SEK", "SGD", "USD"]
    STEPS = ["Accounts", "Your logins", "Bookmarklet", "Get token", "Soren API key"]

    st.title("📊 Welcome to II → Soren")

    if "onb_step" not in st.session_state:
        st.session_state.onb_step = 0
    if "wiz_cfg" not in st.session_state:
        st.session_state.wiz_cfg = {
            "ii_request_delay": {"min": 1, "max": 3},
            "cgt": {"api_url": "https://app.getsoren.app"},
            "users": [{"email": "", "accounts": []}],
        }
    if "onb_auto_discover" not in st.session_state:
        st.session_state.onb_auto_discover = True

    cfg = st.session_state.wiz_cfg
    step = st.session_state.onb_step
    auto_discover = st.session_state.onb_auto_discover

    def sync_emails():
        for i, user in enumerate(cfg["users"]):
            val = st.session_state.get(f"onb_email_{i}", "")
            if val:
                user["email"] = val.strip()

    def wiz_sync():
        sync_emails()
        for i, user in enumerate(cfg["users"]):
            for j, acct in enumerate(user.get("accounts", [])):
                acct["name"] = st.session_state.get(f"wu{i}_a{j}_name", acct.get("name", ""))
                acct["id"] = st.session_state.get(f"wu{i}_a{j}_id", acct.get("id", ""))
                acct["start_date"] = st.session_state.get(f"wu{i}_a{j}_start", acct.get("start_date", ""))
                acct["currencies"] = st.session_state.get(f"wu{i}_a{j}_cur", acct.get("currencies", ["GBP"]))

    def nav_buttons(back_step, next_label, next_step=None, next_action=None):
        st.divider()
        col_back, _, col_next = st.columns([1, 3, 2])
        if col_back.button("← Back"):
            st.session_state.onb_step = back_step
            st.rerun()
        if col_next.button(next_label, type="primary"):
            if next_action:
                next_action()
            elif next_step is not None:
                st.session_state.onb_step = next_step
                st.rerun()

    # Step indicator
    cols = st.columns(len(STEPS))
    for idx, label in enumerate(STEPS):
        with cols[idx]:
            if idx < step:
                st.markdown(f"✓ {label}")
            elif idx == step:
                st.markdown(f"**→ {label}**")
            else:
                st.markdown(f"<span style='color:#6b7280'>{label}</span>", unsafe_allow_html=True)

    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 0 — Auto-discover preference
    # ══════════════════════════════════════════════════════════════════════════
    if step == 0:
        st.subheader("Setting up your accounts")
        st.markdown(
            "II → Soren downloads your transaction history and portfolio from "
            "Interactive Investor and syncs it to [Soren](https://app.getsoren.app).\n\n"
            "The easiest way to set up your accounts is **auto-discover**: "
            "once you're logged into ii.co.uk, it finds your accounts, start dates, "
            "and currencies automatically — no manual entry needed."
        )

        choice = st.radio(
            "How would you like to set up your accounts?",
            options=["Auto-discover (recommended)", "Enter account details manually"],
            index=0 if auto_discover else 1,
            key="onb_disc_choice",
        )
        st.session_state.onb_auto_discover = (choice == "Auto-discover (recommended)")

        st.divider()
        if st.button("Next →", type="primary"):
            st.session_state.onb_step = 1
            st.rerun()

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 1 — II login emails
    # ══════════════════════════════════════════════════════════════════════════
    elif step == 1:
        st.subheader("Your Interactive Investor logins")
        st.markdown(
            "Enter the email address you use to log into **ii.co.uk**. "
            "If you have more than one II account (e.g. a joint account under a different login), "
            "add each one separately."
        )

        for i, user in enumerate(cfg["users"]):
            col_e, col_del = st.columns([5, 1])
            col_e.text_input(
                "II Login Email" if i == 0 else f"II Login Email #{i + 1}",
                value=user["email"],
                placeholder="you@example.com",
                key=f"onb_email_{i}",
            )
            if len(cfg["users"]) > 1:
                col_del.markdown("<br>", unsafe_allow_html=True)
                if col_del.button("Remove", key=f"onb_del_{i}"):
                    sync_emails()
                    cfg["users"].pop(i)
                    for k in range(20):
                        st.session_state.pop(f"onb_email_{k}", None)
                    st.rerun()

        if st.button("＋ Add another II login"):
            sync_emails()
            cfg["users"].append({"email": "", "accounts": []})
            st.rerun()

        def _next_emails():
            sync_emails()
            if all(u["email"] for u in cfg["users"]):
                st.session_state.onb_step = 2
                st.rerun()
            else:
                st.error("Please enter an email address for each login.")

        nav_buttons(back_step=0, next_label="Next →", next_action=_next_emails)

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 2 — Install the bookmarklet
    # ══════════════════════════════════════════════════════════════════════════
    elif step == 2:
        st.subheader("Install the Get II Token bookmarklet")
        st.markdown("""
When you download from Interactive Investor, the app needs to prove it's really you.
II uses a short-lived access code called a **bearer token** — like a temporary visitor
pass, valid for about 30 minutes before you need a fresh one.

The **Get II Token** bookmarklet captures it automatically:

1. **Save it once** — drag the button below to your browser's bookmarks bar
2. **Use it each time** — go to ii.co.uk, click **Get II Token**, navigate anywhere,
   and it copies your token to the clipboard the moment it spots it
3. **Paste and go** — come back here and paste it in the next step

Nothing is sent anywhere. The token never leaves your browser.
""")

        st.info(
            "**To show your bookmarks bar:** "
            "**Mac** — ⌘ Cmd + Shift + B  ·  "
            "**Windows/Linux** — Ctrl + Shift + B"
        )

        render_bookmarklet_button()

        nav_buttons(back_step=1, next_label="Next — I've saved it →", next_step=3)

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 3 — Get bearer token(s) + manual account entry if not auto-discover
    # ══════════════════════════════════════════════════════════════════════════
    elif step == 3:
        if auto_discover:
            st.subheader("Get your II token")
            st.markdown(
                "Go to **[ii.co.uk](https://www.ii.co.uk/)**, click **Get II Token** "
                "in your bookmarks bar, navigate anywhere on the site (e.g. your portfolio), "
                "and the token will be copied to your clipboard. Paste it below."
            )
            st.caption("Accounts will be discovered automatically when you finish setup.")
            if len(cfg["users"]) > 1:
                st.warning(
                    "**Multiple logins:** use a separate browser profile for each II account. "
                    "Logging into a second account in the same profile will log out the first, "
                    "making its token unusable before discovery has run. "
                    "In Chrome: click your profile picture → **Add profile**. "
                    "In Firefox: open the **Profile Manager** (`about:profiles`)."
                )
        else:
            st.subheader("Your account details")
            st.markdown(
                "Enter the details for each II account you want to sync. "
                "You can find your 7-digit account number on the ii.co.uk website."
            )

        for i, user in enumerate(cfg["users"]):
            with st.container(border=True):
                st.markdown(f"**{user['email'].replace('@', '@​')}**")

                st.text_input(
                    "II Bearer Token",
                    key=f"wiz_token_{i}",
                    placeholder="eyJhbGci...",
                    label_visibility="collapsed",
                )

                if not auto_discover:
                    # Manual account entry
                    if user.get("accounts"):
                        st.caption("**Accounts**")
                        for j, acct in enumerate(user["accounts"]):
                            col_n, col_id, col_d, col_cur, col_a = st.columns([2, 2, 2, 4, 1])
                            col_n.text_input("Name", value=acct["name"], placeholder="ISA",
                                             key=f"wu{i}_a{j}_name")
                            col_id.text_input("Account ID", value=acct["id"], placeholder="1234567",
                                              help="7-digit account number from ii.co.uk",
                                              key=f"wu{i}_a{j}_id")
                            col_d.text_input("Start Date", value=acct["start_date"],
                                             placeholder="YYYY-MM-DD",
                                             help="Earliest date to pull transactions from. Too early is fine.",
                                             key=f"wu{i}_a{j}_start")
                            col_cur.multiselect("Currencies", CURRENCIES,
                                                default=acct["currencies"], key=f"wu{i}_a{j}_cur")
                            col_a.markdown("<br>", unsafe_allow_html=True)
                            if len(user["accounts"]) > 1 and col_a.button("🗑", key=f"wiz_del_{i}_{j}",
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

        def _next_tokens():
            # Store tokens; validate manual accounts if not auto-discover
            st.session_state["wiz_tokens"] = {
                i: st.session_state.get(f"wiz_token_{i}", "").strip()
                for i in range(len(cfg["users"]))
            }
            if not auto_discover:
                wiz_sync()
                errors = []
                for i, user in enumerate(cfg["users"]):
                    if not user.get("accounts"):
                        errors.append(f"**{user['email']}**: add at least one account")
                    for j, acct in enumerate(user.get("accounts", [])):
                        alabel = acct["name"] or f"Account {j + 1}"
                        if not acct["id"]:
                            errors.append(f"**{user['email']} / {alabel}**: account ID is required")
                        if not acct["start_date"]:
                            errors.append(f"**{user['email']} / {alabel}**: start date is required")
                        if not acct["currencies"]:
                            errors.append(f"**{user['email']} / {alabel}**: select at least one currency")
                st.session_state["wiz_errors"] = errors
                if errors:
                    st.rerun()
                    return
            st.session_state["wiz_errors"] = []
            st.session_state.onb_step = 4
            st.rerun()

        for err in st.session_state.get("wiz_errors", []):
            st.error(err)

        nav_buttons(back_step=2, next_label="Next →", next_action=_next_tokens)

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 4 — Soren API key + Finish (runs discovery if auto-discover)
    # ══════════════════════════════════════════════════════════════════════════
    elif step == 4:
        st.subheader("Connect to Soren")
        st.markdown("""
To push your data to Soren, you need an API key. Here's how to get one:

1. Log into **[app.getsoren.app](https://app.getsoren.app)**
2. Go to **Settings → API**
3. Click **Create new API key**
4. Copy the key and paste it below
""")

        st.text_input(
            "Soren API Key",
            value=cfg["cgt"].get("api_key", ""),
            placeholder="sk-...",
            key="wiz_cgt_key",
            help="Stored in config.yaml — keep this file private.",
        )

        st.caption("You can skip this for now and add the key later in the ⚙️ Config tab.")

        with st.expander("⚙️ Advanced Settings"):
            st.caption("The defaults work for most setups — only change these if needed.")
            col1, col2, col3 = st.columns([1, 1, 3])
            col1.number_input("Request delay min (s)", min_value=0, max_value=60,
                              value=int(cfg["ii_request_delay"]["min"]), key="wiz_dmin")
            col2.number_input("Request delay max (s)", min_value=0, max_value=60,
                              value=int(cfg["ii_request_delay"]["max"]), key="wiz_dmax")
            col3.text_input("Soren API URL", value=cfg["cgt"]["api_url"], key="wiz_cgt_url")

        st.divider()
        col_back, _, col_finish = st.columns([1, 3, 2])
        if col_back.button("← Back"):
            st.session_state.onb_step = 3
            st.rerun()

        finish_label = "✓ Finish Setup & Discover Accounts" if auto_discover else "✓ Finish Setup"
        if col_finish.button(finish_label, type="primary"):
            cfg["ii_request_delay"]["min"] = st.session_state.get("wiz_dmin", 1)
            cfg["ii_request_delay"]["max"] = st.session_state.get("wiz_dmax", 3)
            cfg["cgt"]["api_url"] = st.session_state.get("wiz_cgt_url", "https://app.getsoren.app").strip().rstrip("/")
            api_key = st.session_state.get("wiz_cgt_key", "").strip()
            if api_key:
                cfg["cgt"]["api_key"] = api_key
            else:
                cfg["cgt"].pop("api_key", None)
            st.session_state["wiz_finish_running"] = True
            st.rerun()

        if st.session_state.get("wiz_finish_running"):
            tokens = st.session_state.get("wiz_tokens", {})
            all_ok = True

            if auto_discover:
                for i, user in enumerate(cfg["users"]):
                    tok = tokens.get(i, "").strip()
                    if not tok:
                        st.error(f"No token provided for **{user['email']}** — go back and paste one.")
                        all_ok = False
                        continue
                    with st.status(f"Discovering accounts for {user['email']}…", expanded=True) as disc_status:
                        ok, log = run_and_stream(["--discover", "--token", tok])
                        discovered = None
                        for line in log.splitlines():
                            clean = strip_ansi(line).strip()
                            if clean.startswith("DISCOVERED:"):
                                try:
                                    discovered = json.loads(clean[len("DISCOVERED:"):])
                                except Exception:
                                    pass
                                break
                        if discovered and ok:
                            disc_status.update(label=f"✓ Found {len(discovered)} account(s)", state="complete")
                            new_accounts = []
                            for a in discovered:
                                acct = {"id": a["id"], "name": a["name"],
                                        "start_date": a["start_date"], "currencies": a["currencies"]}
                                if a.get("currency_start_dates"):
                                    acct["currency_start_dates"] = a["currency_start_dates"]
                                new_accounts.append(acct)
                            user["accounts"] = new_accounts
                        else:
                            disc_status.update(label=f"✗ Discovery failed for {user['email']}", state="error")
                            all_ok = False

            st.session_state["wiz_finish_running"] = False

            if all_ok:
                with open(CONFIG_FILE, "w") as f:
                    yaml.dump(cfg, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
                del st.session_state.wiz_cfg
                st.session_state.pop("onb_step", None)
                st.session_state.pop("onb_auto_discover", None)
                st.session_state.pop("wiz_tokens", None)
                st.rerun()
            else:
                st.error("Setup incomplete — fix the errors above and try again.")


if not config:
    show_onboarding()
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
    if "dl_create_accounts_pref" not in st.session_state:
        st.session_state.dl_create_accounts_pref = True
    if also_push:
        dl_create_accounts = col_create.checkbox(
            "Create missing Soren accounts",
            value=st.session_state.dl_create_accounts_pref,
            disabled=st.session_state.dl_running or not _cgt_key,
            help="If an account exists in your II config but not yet in Soren, create it automatically",
        )
        st.session_state.dl_create_accounts_pref = dl_create_accounts
    else:
        dl_create_accounts = False
    if not _cgt_key:
        st.info(
            "💡 To push to Soren, you need an API key. "
            "Get one from **Settings → API** inside Soren, then paste it in the **⚙️ Config** tab."
        )

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
        col_e.markdown(f"**{_email.replace('@', '@​')}**")

        def _make_save(_e=_email, _k=_tok_key):
            def _cb(): st.session_state.ii_tokens[_e] = st.session_state[_k]
            return _cb

        col_t.text_input(
            "II Bearer Token",
            value=st.session_state.ii_tokens.get(_email, ""),
            key=_tok_key,
            on_change=_make_save(),
            placeholder="Paste the ii token (use the 🔖 Bookmarklet)",
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
        render_run_result(st.session_state.dl_last_ok,
                          st.session_state.dl_last_log, "Download")


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
        st.info(
            "💡 To push to Soren, you need an API key. "
            "Get one from **Settings → API** inside Soren, then paste it in the **⚙️ Config** tab."
        )

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
            ok, log = run_and_stream(st.session_state.push_args, st.session_state.push_env, show_push_counter=True)
            status.update(
                label="Push complete ✓" if ok else "Push failed ✗",
                state="complete" if ok else "error",
            )
        st.session_state.push_running = False
        st.session_state.push_last_ok = ok
        st.session_state.push_last_log = log
        st.rerun()

    if st.session_state.push_last_ok is not None:
        render_run_result(st.session_state.push_last_ok,
                          st.session_state.push_last_log, "Push")


# ─── Config ───────────────────────────────────────────────────────────────────

CURRENCIES = ["AUD", "CAD", "CHF", "DKK", "EUR", "GBP", "HKD", "JPY", "NOK", "SEK", "SGD", "USD"]


def sync_form_to_cfg():
    """Collect current widget values from session state into cfg_edit."""
    cfg = st.session_state.cfg_edit
    cfg.setdefault("ii_request_delay", {})["min"] = st.session_state.get("cfg_delay_min", 1)
    cfg["ii_request_delay"]["max"] = st.session_state.get("cfg_delay_max", 3)
    cfg["auto_discover"] = st.session_state.get("cfg_auto_discover", True)
    cfg.setdefault("cgt", {})["api_url"] = st.session_state.get("cfg_cgt_url", "").strip().rstrip("/")
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
        help="Get this from Settings → API in your Soren account. Stored in config.yaml (which is gitignored).",
    )

    # ── Users & accounts ──────────────────────────────────────────────────────
    st.subheader("Users & Accounts")

    st.checkbox(
        "Auto-discover new accounts on download",
        value=cfg.get("auto_discover", True),
        key="cfg_auto_discover",
        help="Before each download, query the ii API with your bearer token to find any newly-opened accounts and add them automatically.",
    )

    for i, user in enumerate(cfg.get("users", [])):
        with st.expander(f"👤  {user.get('email', 'New User').replace('@', '@​')}", expanded=True):
            col_e, col_del = st.columns([4, 1])
            col_e.text_input("Email", value=user.get("email", ""), key=f"u{i}_email")
            if col_del.button("🗑 Remove user", key=f"del_user_{i}"):
                sync_form_to_cfg()
                cfg["users"].pop(i)
                st.rerun()

            # ── Accounts ──────────────────────────────────────────────────────
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
