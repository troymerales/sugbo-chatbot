"""
`render_floating_assistant()` — the shared floating support widget.

Call it once at the bottom of any page (Homepage, Consultation Transcript, …).
State lives in `st.session_state`, so the conversation follows the user from
page to page. The widget is a `st.popover` pinned bottom-right by `styles.py`;
its body is a `@st.fragment`, so typing in the widget reruns only the widget,
not the host page (which may be rendering a heavy dashboard iframe).
"""

from __future__ import annotations

import json
import random

import streamlit as st
import streamlit.components.v1 as components

import config
from assistant import session, styles
from assistant.ticket_dialog import ticket_dialog
from core import jira_client

_INPUT_STAGES = ("chat", "feedback", "offer_ticket")

# Shown once in a bubble beside the button, then replaced by the unread dot.
_GREETINGS = (
    "Hi! How may I help you today?",
    "Do you need assistance?",
    "Need help finding something?",
    "How can I assist you?",
    "Have a question about SugboDoc?",
)

# Runs in a components.html iframe, which is same-origin with the app, so it can
# drive the parent document directly. Streamlit strips <script> from st.markdown,
# and the timing here genuinely belongs on the client: the bubble has to survive
# script reruns rather than restart on each one.
#
# State lives on the parent `window`, which outlives reruns but not a page load:
#   __sdAsstGreeted -- bubble already shown for this page load
#   __sdAsstRead    -- panel opened, so the notification is "read"
# A MutationObserver re-applies that state because Streamlit rebuilds the
# button's DOM on rerun, which would otherwise resurrect a dismissed badge.
_NOTIFY_JS = """
<script>
(function () {
  var W = window.parent, D = W.document;
  var GREETING = __GREETING__;
  var ANCHOR = ".__ANCHOR__";
  var HOLD_MS = 10000, FADE_MS = 340;

  function strip(root) {
    root.querySelectorAll(".sd-greet, .sd-fab-badge").forEach(function (n) { n.remove(); });
  }

  // The transcript is its own scroll area, so a fresh reply can land below the
  // fold. Follow it down as the conversation grows — but leave the view alone
  // once someone has scrolled up to re-read an earlier answer. The state lives
  // on `window`, not on the element: Streamlit rebuilds the element on every
  // rerun, so anything stored on it is gone by the time the reply arrives.
  function pinLog() {
    var log = D.querySelector(".st-key-sdasstlog");
    if (!log) return;
    var n = log.querySelectorAll('[data-testid="stChatMessage"]').length;
    if (W.__sdMsgN === undefined) { W.__sdMsgN = n; return; }  // first paint: top
    if (n !== W.__sdMsgN) { W.__sdMsgN = n; W.__sdFollow = true; }
    if (!log.__sdScrollBound) {
      log.__sdScrollBound = true;
      log.addEventListener("scroll", function () {
        W.__sdFollow = (log.scrollHeight - log.scrollTop - log.clientHeight) < 40;
      });
    }
    if (W.__sdFollow) log.scrollTop = log.scrollHeight;
  }

  function apply() {
    pinLog();
    var root = D.querySelector(ANCHOR);
    if (!root) return;
    var btn = root.querySelector("button");
    if (!btn) return;

    if (!btn.__sdBound) {
      btn.__sdBound = true;
      btn.addEventListener("click", function () {
        W.__sdAsstRead = true;          // opening the panel reads the notification
        strip(root);
      });
    }

    if (W.__sdAsstRead) { strip(root); return; }

    if (!root.querySelector(".sd-fab-badge")) {
      var dot = D.createElement("span");
      dot.className = "sd-fab-badge";
      root.appendChild(dot);
    }

    if (!W.__sdAsstGreeted) {
      W.__sdAsstGreeted = true;
      var bubble = D.createElement("div");
      bubble.className = "sd-greet";
      bubble.textContent = GREETING;
      root.appendChild(bubble);
      W.setTimeout(function () {
        bubble.classList.add("out");
        W.setTimeout(function () { bubble.remove(); }, FADE_MS);
      }, HOLD_MS);
    }
  }

  apply();
  // Re-install rather than skip when one already exists: Streamlit tears down
  // this iframe on every rerun, and a MutationObserver whose callback closed
  // over a destroyed context silently stops firing. The flags above live on the
  // parent window precisely so they survive that.
  if (W.__sdAsstObserver) {
    try { W.__sdAsstObserver.disconnect(); } catch (e) {}
  }
  // setTimeout, not requestAnimationFrame: rAF does not run at all in a
  // background tab, so the queued work would never fire if the user switched
  // tabs while an answer was streaming.
  var queued = false;
  W.__sdAsstObserver = new W.MutationObserver(function () {
    if (queued) return;
    queued = true;
    W.setTimeout(function () { queued = false; apply(); }, 50);
  });
  W.__sdAsstObserver.observe(D.body, { childList: true, subtree: true });
})();
</script>
"""


def _greeting() -> str:
    """Pick once per session, not per rerun — otherwise the bubble would say
    something different every time the script re-runs."""
    ss = st.session_state
    if "asst_greeting" not in ss:
        ss.asst_greeting = random.choice(_GREETINGS)
    return ss.asst_greeting


def preload_assistant() -> None:
    """Inject the widget's stylesheet early in the run.

    ``render_floating_assistant()`` is called at the very bottom of a page, so a
    ``st.spinner`` higher up pauses the script before its ``styles.inject()`` is
    reached. Streamlit then drops the not-yet-re-rendered ``<style>`` and the
    stale floating button loses its ``position:fixed`` rounding, dumping a bare
    rectangle into the page flow. Claiming the CSS up front avoids that; the
    second ``inject()`` at render time is a harmless duplicate.
    """
    styles.inject()


def render_floating_assistant() -> None:
    session.init()
    styles.inject()
    with st.container(key="sugbodoc_assistant"):
        # The label is hidden by CSS but kept as the button's accessible name.
        with st.popover("Assistant", use_container_width=False):
            st.markdown(styles.PANEL_HEADER_HTML, unsafe_allow_html=True)
            with st.container(key="sdasstbody"):
                _panel()

    # Outside the anchor: the anchor is position:fixed, and this host has no
    # visual output of its own.
    with st.container(key="sdasstjs"):
        components.html(
            _NOTIFY_JS.replace("__GREETING__", json.dumps(_greeting()))
            .replace("__ANCHOR__", styles._ANCHOR),
            height=0,
        )


@st.fragment
def _panel() -> None:
    ss = st.session_state

    # How much of the panel is *not* transcript. The feedback / ticket row only
    # exists in some stages, so without adjusting for it the panel either ends
    # in a band of blank space or overflows when that row appears. Letting the
    # transcript flex to fill would be nicer, but flex sizing does not survive
    # Streamlit's nested block wrappers — see styles.py.
    _chrome = "19.25rem" if ss.asst_stage in ("feedback", "offer_ticket") else "13.5rem"
    st.markdown(
        f'<style>[data-testid="stPopoverBody"]{{--sda-chrome:{_chrome};}}</style>',
        unsafe_allow_html=True,
    )

    # The transcript gets its own container so the stylesheet can give it a
    # standing height — a chat panel that is only as tall as its content looks
    # like a tooltip, not a chat window.
    with st.container(key="sdasstlog"):
        for msg in ss.asst_messages:
            role = "user" if msg["role"] == "user" else "assistant"
            with st.chat_message(role):
                st.markdown(msg["content"])

        # An answer is mid-flight: stream it, verify, then rerun to show controls.
        if ss.get("asst_pending"):
            with st.chat_message("assistant"):
                typing = st.empty()
                typing.markdown(styles.TYPING_HTML, unsafe_allow_html=True)
                draft = st.write_stream(_typing_then(session.stream_reply(), typing))
            # The grounding pass runs silently: it is an internal check, not a
            # step the person asking a question needs narrated to them.
            session.resolve_pending(draft or "")
            st.rerun()

    _controls(ss.asst_stage)

    if ss.asst_stage in _INPUT_STAGES:
        with st.form("asst_input", clear_on_submit=True, border=False):
            text = st.text_input(
                "Message", label_visibility="collapsed",
                placeholder="Ask about scheduling, billing, encounters…",
            )
            sent = st.form_submit_button("Send", use_container_width=True)
        if sent and text.strip():
            session.ask(text.strip())
            st.rerun()


def _typing_then(chunks, placeholder):
    """Yield `chunks`, clearing the typing dots as the first one lands.

    `st.write_stream` renders nothing until the model produces a token, so the
    dots fill that gap and disappear the instant real text takes their place.
    Cleared in the no-chunks case too, so an empty answer can't strand them.
    """
    cleared = False
    try:
        for chunk in chunks:
            if not cleared:
                placeholder.empty()
                cleared = True
            yield chunk
    finally:
        if not cleared:
            placeholder.empty()


def _controls(stage: str) -> None:
    ss = st.session_state

    if stage == "feedback":
        st.caption("Did that help? You can also just keep typing.")
        # Two passes, so the click is painted before the work starts: the first
        # records which button was pressed and reruns; the second renders that
        # button in its busy state and *then* calls session.feedback(), which
        # for a thumbs-down runs failure capture and a duplicate lookup.
        busy = ss.get("asst_fb_busy")
        c1, c2 = st.columns(2)
        yes_box = c1.container(key="sdfb_busy_yes" if busy == "up" else "sdfb_yes")
        no_box = c2.container(key="sdfb_busy_no" if busy == "down" else "sdfb_no")
        yes = yes_box.button("👍 Yes", use_container_width=True, key="asst_fb_yes",
                             disabled=busy is not None)
        no = no_box.button("👎 No", use_container_width=True, key="asst_fb_no",
                           disabled=busy is not None)
        if busy is None:
            if yes:
                ss.asst_fb_busy = "up"
                st.rerun()
            if no:
                ss.asst_fb_busy = "down"
                st.rerun()
        else:
            session.feedback(busy == "up")
            del ss.asst_fb_busy
            st.rerun()

    elif stage == "offer_ticket":
        if ss.asst_question_count >= config.QUESTIONS_BEFORE_TICKET:
            st.warning("This is taking a while — want to file a ticket?")
        else:
            st.caption("Sorry that didn't help. File a ticket, or tell me more?")
        c1, c2 = st.columns(2)
        if c1.button("📨 Submit a ticket", use_container_width=True, key="asst_mk"):
            ticket_dialog()
        if c2.button("💬 Tell me more", use_container_width=True, key="asst_more"):
            session.tell_me_more()
            st.rerun()

    elif stage == "done":
        tid = ss.asst_ticket_id
        if tid and jira_client.jira_configured():
            st.success(f"Ticket [{tid}]({jira_client.browse_url(tid)}) created.")
        if st.button("Start a new chat", use_container_width=True, key="asst_new"):
            session.reset()
            st.rerun()
