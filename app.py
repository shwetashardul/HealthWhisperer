import os
import time
import streamlit as st
from dotenv import load_dotenv
from auth.hashing import hash_password, verify_password
from auth.guards import logout_and_clear
from data.db import get_session, get_user_by_email, create_user, update_user, init_db, verify_schema, db_info


st.set_page_config(
    page_title="Health Whisperer",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded",
)

load_dotenv(override=False)

# Prefer Streamlit secrets for GEMINI_API_KEY; fallback to environment/.env
try:
    secret_key = st.secrets.get("GEMINI_API_KEY") if hasattr(st, "secrets") else None
except Exception:
    secret_key = None

if secret_key and not os.getenv("GEMINI_API_KEY"):
    os.environ["GEMINI_API_KEY"] = str(secret_key)

has_gemini_key = bool(os.getenv("GEMINI_API_KEY"))

HEADER_CSS = """
<style>
:root {
  --hw-primary: #3c9a6b;
  --hw-secondary: #d6f5e3;
  --hw-bg: #f7faf7;
  --hw-text: #101311;
}
[data-testid="stAppViewContainer"] {
  background-color: var(--hw-bg);
}
.sun-header {
  background: linear-gradient(135deg, rgba(255, 245, 230, 0.9) 0%, rgba(214, 245, 227, 0.9) 50%, rgba(198, 239, 206, 0.9) 100%);
  border: 1px solid rgba(60,154,107,0.15);
  border-radius: 14px;
  padding: 28px 24px;
  margin: 8px 0 18px 0;
  box-shadow: 0 2px 10px rgba(60,154,107,0.06), inset 0 0 60px rgba(255, 212, 94, 0.15);
}
.sun-title {
  color: var(--hw-text);
  font-size: 28px;
  font-weight: 800;
  margin: 0 0 4px 0;
}
.sun-subtitle {
  color: #2d3a33;
  font-size: 16px;
  margin: 0;
}
.sun-warning {
  margin-top: 10px;
  padding: 8px 12px;
  background: rgba(255, 187, 0, 0.12);
  border: 1px solid rgba(255, 187, 0, 0.25);
  border-radius: 10px;
  color: #2d2a1a;
  font-size: 14px;
}
</style>
"""


st.markdown(HEADER_CSS, unsafe_allow_html=True)

# DB startup hook
try:
    init_db()
    ver = verify_schema()
    st.session_state["db_boot"] = {"db_info": db_info(), "verify": ver, "ts": time.time()}
except Exception as _e:
    st.session_state["db_boot"] = {"db_info": db_info(), "verify": {"ok": False, "error": str(_e)}, "ts": time.time()}

dbb = st.session_state.get("db_boot", {})
info = dbb.get("db_info", {})
verify = dbb.get("verify", {})

banner = f"DB: {info.get('sqlite_path') or info.get('url')} • tables: {', '.join(verify.get('tables', []))}"
created_msg = " (created now)" if verify.get("created_now") else ""
st.caption(banner + created_msg)
if not verify.get("ok"):
    st.error("Database schema not initialized. Please reload.")
    st.stop()
st.markdown("""
<script>
// ensure the external notifications.js is loaded via <script src> if hosted; here we rely on globals defined in that file
</script>
""", unsafe_allow_html=True)
perm = st.session_state.get("notifications_permission")
iframe_flag = st.session_state.get("notifications_iframe")
st.sidebar.subheader("Notifications")
coln1, coln2 = st.sidebar.columns(2)
with coln1:
    if st.button("Check status"):
        st.markdown("<script>window._hw_ps = (window.hwPermissionStatus? hwPermissionStatus() : 'unsupported'); window._hw_if = (window.hwIsInIframe? hwIsInIframe() : false);</script>", unsafe_allow_html=True)
        st.session_state["notifications_permission"] = perm
        st.session_state["notifications_iframe"] = iframe_flag
with coln2:
    if st.button("Request permission"):
        st.markdown("<script>window.hwRequestPermission && hwRequestPermission().then((s)=>{ window._hw_ps = s; });</script>", unsafe_allow_html=True)
st.sidebar.caption("Status and Iframe will update on next action.")
if st.sidebar.button("🔔 Send test notification"):
    st.markdown("<script>window.hwNotify && hwNotify('Test','This is a test.');</script>", unsafe_allow_html=True)
warning_html = (
    """
    <div class="sun-warning">
      Missing GEMINI_API_KEY. Add it via Streamlit secrets or .env to enable AI suggestions.
    </div>
    """
    if not has_gemini_key
    else ""
)

header_html = f"""
    <div class=\"sun-header\">
      <div class=\"sun-title\">Health Whisperer</div>
      <p class=\"sun-subtitle\">Gentle nudges for a healthier you 🌿</p>
      {warning_html}
    </div>
"""

st.markdown(header_html, unsafe_allow_html=True)

# If already logged in, redirect to Home
if st.session_state.get("user"):
    try:
        st.caption("You’re already logged in. Redirecting…")
        st.switch_page("pages/1_🏠_Home.py")
    except Exception:
        st.experimental_rerun()

# Simple in-app auth
with st.expander("Account"):
    tab_login, tab_signup, tab_forgot = st.tabs(["Login", "Sign up", "Forgot password"])
    with tab_login:
        le = st.text_input("Email", key="login_email")
        lp = st.text_input("Password", type="password", key="login_pw")
        if st.button("Login"):
            with get_session() as s:
                u = get_user_by_email(s, le.strip().lower()) if le else None
                if u and u.password_hash and lp and verify_password(lp, u.password_hash):
                    st.session_state["user_email"] = u.email
                    st.session_state["user"] = {"id": u.id, "email": u.email, "name": u.name}
                    st.success("Logged in")
                    # Redirect back to intended page if set
                    dest = st.session_state.pop("auth_redirect_from", None) or "pages/1_🏠_Home.py"
                    try:
                        st.switch_page(dest)
                    except Exception:
                        st.experimental_rerun()
                else:
                    st.error("Invalid credentials")
    with tab_signup:
        se = st.text_input("Email", key="signup_email")
        sp = st.text_input("Password", type="password", key="signup_pw")
        if st.button("Create account"):
            with get_session() as s:
                if se and get_user_by_email(s, se.strip().lower()):
                    st.error("An account with this email already exists.")
                elif se and sp:
                    new_user = create_user(s, email=se.strip().lower(), name="", password_hash=hash_password(sp), preferences=None)
                    st.session_state["user_email"] = new_user.email
                    st.session_state["user"] = {"id": new_user.id, "email": new_user.email, "name": new_user.name}
                    st.success("Account created. Redirecting…")
                    dest = st.session_state.pop("auth_redirect_from", None) or "pages/1_🏠_Home.py"
                    try:
                        st.switch_page(dest)
                    except Exception:
                        st.experimental_rerun()
                else:
                    st.error("Enter email and password")
    with tab_forgot:
        fe = st.text_input("Email", key="forgot_email")
        np = st.text_input("New password", type="password", key="forgot_new")
        if st.button("Reset password"):
            with get_session() as s:
                u = get_user_by_email(s, fe.strip().lower()) if fe else None
                if not u:
                    st.error("No account for this email")
                elif not np:
                    st.error("Enter a new password")
                else:
                    update_user(s, u.id, password_hash=hash_password(np))
                    st.success("Password reset. Please log in.")

if not st.session_state.get("user"):
    with st.sidebar:
        st.info("Please log in to access Home, Summary, and Profile.")
else:
    st.write("Welcome. Use the sidebar to navigate.")
    st.info("Pages: Home, Summary, Profile")

with st.sidebar:
    if st.session_state.get("user") and st.button("Logout"):
        logout_and_clear()


