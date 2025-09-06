import time
import streamlit as st


def _redirect(path: str) -> None:
    try:
        st.switch_page(path)
    except Exception:
        st.stop()


def require_login(redirect_to: str = "app.py"):
    user = st.session_state.get("user")
    # Session timeout (120 minutes)
    now_ts = time.time()
    last = st.session_state.get("last_active_at")
    if last and now_ts - float(last) > 120 * 60:
        logout_and_clear(message="Session timed out, please log in again.")
        _redirect(redirect_to)
        return None
    st.session_state["last_active_at"] = now_ts

    if not user:
        # Preserve intended destination if provided by the page beforehand
        if "auth_redirect_from" not in st.session_state:
            st.session_state["auth_redirect_from"] = redirect_to
        st.info("Please log in to continue.")
        _redirect("app.py")
        return None
    return user


def logout_and_clear(message: str = "Logged out safely.") -> None:
    # Clear known session keys
    for k in [
        "user",
        "user_email",
        "debug",
        "auth_redirect_from",
        "notifications_permission",
        "notifications_iframe",
    ]:
        if k in st.session_state:
            del st.session_state[k]
    st.success(message)
    try:
        st.switch_page("app.py")
    except Exception:
        st.stop()


