"""
The floating assistant's CSS, plus the small markup snippets that go with it.

Two things worth knowing before editing:

* **The panel is portalled.** Streamlit renders `stPopoverBody` at the end of
  `<body>`, *not* inside the `st.container(key=...)` anchor — so panel rules
  cannot be scoped by the anchor class. They are scoped by `.sd-asst`, a class
  this module puts on the panel's own content container instead.
* **Colours are inherited, not re-picked.** The tokens below alias `shell.py`'s
  `:root` variables, so the widget tracks the app theme automatically; the
  literal fallbacks only apply if the widget is ever rendered without the shell.
  `--sda-header` is the app header's gradient verbatim, which is what visually
  ties the panel header to the top bar.

The layout leans on two stable hooks — the anchor class and `stPopoverBody`.
If a Streamlit upgrade renames the rest, the widget still works; it just stops
looking bespoke.
"""

from __future__ import annotations

import streamlit as st

# st.container(key="sugbodoc_assistant") renders a wrapper with this class.
_ANCHOR = "st-key-sugbodoc_assistant"
# st.container(key="sdasstbody") wraps the panel content below the header.
_PANEL = "st-key-sdasstbody"

# A chat bubble with three dots — reads as "assistant" at 26px, and being an
# inline SVG it stays crisp and needs no network request.
_ICON = (
    "url(\"data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
    "stroke='%23ffffff' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'%3E"
    "%3Cpath d='M20.5 11.6a8.2 8.2 0 0 1-8.8 8.2 8.5 8.5 0 0 1-3.6-.9L3.5 20.5l1.6-4.6a8.2 8.2 0 0 1-1-4 "
    "8.2 8.2 0 0 1 8.2-8.2 8.2 8.2 0 0 1 8.2 8.2z'/%3E"
    "%3Ccircle cx='8.6' cy='11.8' r='1.05' fill='%23ffffff' stroke='none'/%3E"
    "%3Ccircle cx='12.3' cy='11.8' r='1.05' fill='%23ffffff' stroke='none'/%3E"
    "%3Ccircle cx='16' cy='11.8' r='1.05' fill='%23ffffff' stroke='none'/%3E"
    "%3C/svg%3E\")"
)

# Written with placeholder tokens rather than an f-string: CSS is mostly braces,
# and doubling every one of them for str.format is a bug farm.
_CSS_TEMPLATE = """
/* ---------------- tokens ----------------
   Aliased from shell.py's :root, declared on both the anchor and the portalled
   panel because those live in different subtrees. */
.ANCHOR_CLS, [data-testid="stPopoverBody"] {
    --sda-indigo: var(--sd-indigo, #3b41d6);
    --sda-indigo-600: var(--sd-indigo-600, #333ac2);
    --sda-indigo-50: var(--sd-indigo-50, #eef0fe);
    --sda-ink: var(--sd-ink, #1f2430);
    --sda-ink-2: var(--sd-ink-2, #3a4152);
    --sda-muted: var(--sd-muted, #6b7280);
    --sda-line: var(--sd-line, #e6e7ef);
    --sda-card: var(--sd-card, #ffffff);
    --sda-bg: var(--sd-bg, #f4f5fb);
    --sda-header: linear-gradient(100deg, #3b41d6 0%, #4a50e4 55%, #5a54e8 100%);
    --sda-pad: 14px;
}

/* ---------------- the floating button ---------------- */
.ANCHOR_CLS {
    position: fixed;
    right: 1.5rem;
    bottom: 1.5rem;
    z-index: 9990;
    width: auto;
}
.ANCHOR_CLS [data-testid="stPopover"] > div > button,
.ANCHOR_CLS button[kind="secondary"] {
    width: 58px;
    height: 58px;
    min-height: 58px;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: ICON_URL center / 26px 26px no-repeat,
                var(--sda-header);
    box-shadow: 0 8px 22px rgba(59, 65, 214, 0.38), 0 2px 6px rgba(31, 36, 48, 0.12);
    transition: transform 0.18s cubic-bezier(0.2, 0.8, 0.3, 1),
                box-shadow 0.18s ease;
}
/* The label stays in the DOM for screen readers; only its pixels go away. */
.ANCHOR_CLS [data-testid="stPopover"] > div > button p,
.ANCHOR_CLS button[kind="secondary"] p {
    font-size: 0 !important;
    line-height: 0 !important;
}
.ANCHOR_CLS [data-testid="stPopover"] > div > button:hover {
    transform: translateY(-2px) scale(1.04);
    box-shadow: 0 14px 30px rgba(59, 65, 214, 0.46), 0 3px 8px rgba(31, 36, 48, 0.14);
}
.ANCHOR_CLS [data-testid="stPopover"] > div > button:active {
    transform: translateY(0) scale(0.97);
    transition-duration: 0.08s;
}
.ANCHOR_CLS [data-testid="stPopover"] > div > button:focus-visible {
    outline: 3px solid var(--sda-indigo-50);
    outline-offset: 3px;
}

/* ---------------- unread badge ----------------
   Injected by the JS in widget.py, removed once the panel is opened. */
.ANCHOR_CLS .sd-fab-badge {
    position: absolute;
    top: 0;
    right: 0;
    width: 13px;
    height: 13px;
    border-radius: 50%;
    background: #e5484d;
    border: 2.5px solid #ffffff;
    box-shadow: 0 1px 3px rgba(31, 36, 48, 0.28);
    pointer-events: none;
    z-index: 2;
    animation: sd-badge-in 0.3s cubic-bezier(0.2, 0.8, 0.3, 1) both;
}
@keyframes sd-badge-in {
    from { transform: scale(0.3); opacity: 0; }
    to   { transform: scale(1);   opacity: 1; }
}

/* ---------------- greeting bubble ----------------
   width:max-content so short greetings do not stretch, capped against the
   viewport so it cannot be clipped on a narrow window. */
.ANCHOR_CLS .sd-greet {
    position: absolute;
    right: 4px;
    bottom: calc(100% + 14px);
    width: max-content;
    max-width: min(17rem, calc(100vw - 3rem));
    padding: 10px 13px;
    background: var(--sda-card);
    color: var(--sda-ink);
    border: 1px solid var(--sda-line);
    border-radius: 14px;
    font-size: 15px;
    font-weight: 500;
    line-height: 1.45;
    box-shadow: 0 12px 32px rgba(31, 36, 48, 0.55), 0 2px 6px rgba(31, 36, 48, 0.36);
    pointer-events: none;
    animation: sd-greet-in 0.34s cubic-bezier(0.2, 0.8, 0.3, 1) both;
}
.ANCHOR_CLS .sd-greet::after {
    content: "";
    position: absolute;
    right: 20px;
    bottom: -6px;
    width: 11px;
    height: 11px;
    background: var(--sda-card);
    border-right: 1px solid var(--sda-line);
    border-bottom: 1px solid var(--sda-line);
    border-bottom-right-radius: 2px;
    transform: rotate(45deg);
}
.ANCHOR_CLS .sd-greet.out {
    animation: sd-greet-out 0.34s ease both;
}
@keyframes sd-greet-in {
    from { opacity: 0; transform: translateY(7px) scale(0.97); }
    to   { opacity: 1; transform: none; }
}
@keyframes sd-greet-out {
    from { opacity: 1; transform: none; }
    to   { opacity: 0; transform: translateY(5px) scale(0.98); }
}

/* ---------------- the panel ----------------
   Portalled to <body>, so these are global; the app has exactly one popover. */
[data-testid="stPopoverBody"] {
    width: min(23rem, calc(100vw - 2rem)) !important;
    max-width: min(23rem, calc(100vw - 2rem)) !important;
    /* Streamlit floors the panel at 20rem, which overflows a 320px viewport. */
    min-width: 0 !important;
    /* A standing height, not just a cap. Streamlit positions the panel once, on
       open; if it were free to grow as replies arrive it would grow downward and
       run off the bottom of the viewport. Fixed height => positioned correctly
       once, and a long conversation scrolls inside instead. */
    height: min(36rem, calc(100vh - 7rem)) !important;
    max-height: min(36rem, calc(100vh - 7rem)) !important;
    padding: 0 !important;
    border: 1px solid var(--sda-line) !important;
    border-radius: 16px !important;
    box-shadow: 0 20px 52px rgba(31, 36, 48, 0.18), 0 4px 12px rgba(31, 36, 48, 0.08) !important;
    overflow: hidden auto !important;
}

/* Header banner — the app header's own gradient, so the panel reads as part of
   SugboDoc rather than a bolted-on chat widget. */
.sd-asst-head {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 13px var(--sda-pad);
    background: var(--sda-header);
    color: #ffffff;
}
.sd-asst-head .av {
    flex: 0 0 32px;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.18);
    box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.28);
    background-image: ICON_URL;
    background-repeat: no-repeat;
    background-position: center;
    background-size: 18px 18px;
}
.sd-asst-head b {
    display: block;
    font-size: 13.5px;
    line-height: 1.25;
    letter-spacing: -0.1px;
}
.sd-asst-head span {
    display: block;
    font-size: 11.5px;
    line-height: 1.3;
    color: rgba(255, 255, 255, 0.82);
}

/* Panel content sits inside st.container(key="sdasstbody") so the header above
   can run full-bleed to the panel edges. */
.PANEL_CLS {
    padding: 12px var(--sda-pad) var(--sda-pad);
}

/* ---------------- messages ----------------
   The transcript holds a standing height and grows upward from the bottom, so
   a one-message conversation still reads as a chat window and the input stays
   put instead of jumping down the panel as replies arrive. */
.st-key-sdasstlog {
    /* A standing height rather than a min: the transcript is the only part that
       scrolls, so the header and the input stay put and a scrollbar appears
       only once the conversation is taller than this box. Sized against the
       panel's own height so it still fits on a short viewport. */
    /* Streamlit gives every stVerticalBlock `flex: 1 1 0%`, and a flex-basis of
       0 overrides `height` on the main axis — so the height below is ignored
       until the block opts out of flex sizing. !important on both because those
       Streamlit rules outrank a plain class selector.

       The height is the panel minus everything else in it. `--sda-chrome` is
       set per rerun by widget.py, because the "Did that help?" row comes and
       goes and only Python knows which stage we are in — letting the transcript
       flex to fill instead does not survive Streamlit's nested wrappers. */
    flex: 0 0 auto !important;
    height: calc(min(36rem, calc(100vh - 7rem)) - var(--sda-chrome, 11.5rem)) !important;
    overflow-y: auto !important;
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
    /* scrolls, but shows no bar -- a track reads as a seam in a chat panel */
    scrollbar-width: none;
    -ms-overflow-style: none;
}
.st-key-sdasstlog::-webkit-scrollbar { display: none; }
/* ---------------- messages ---------------- */
.PANEL_CLS [data-testid="stChatMessage"] {
    background: transparent;
    padding: 2px 0;
    gap: 9px;
}
.PANEL_CLS [data-testid="stChatMessage"] [data-testid="stChatMessageContent"] {
    padding: 9px 12px;
    font-size: 13.5px;
    line-height: 1.5;
}
.PANEL_CLS [data-testid="stChatMessage"] p {
    font-size: 13.5px;
    line-height: 1.5;
    margin-bottom: 0.35rem;
}
/* Streamlit's -16px markdown margin cancelled the bubble's bottom padding, so
   text sat flush against the lower edge while the top had its full 9px. */
.PANEL_CLS [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {
    margin-bottom: 0 !important;
}
.PANEL_CLS [data-testid="stChatMessage"] [data-testid="stChatMessageContent"] > div > :last-child,
.PANEL_CLS [data-testid="stChatMessage"] p:last-child {
    margin-bottom: 0 !important;
}
/* assistant: light card, tail on the left */
.PANEL_CLS [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"])
    [data-testid="stChatMessageContent"] {
    background: var(--sda-bg);
    border: 1px solid var(--sda-line);
    border-radius: 14px 14px 14px 4px;
    color: var(--sda-ink-2);
}
/* user: indigo, right-aligned, tail on the right */
.PANEL_CLS [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    flex-direction: row-reverse;
}
.PANEL_CLS [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"])
    [data-testid="stChatMessageContent"] {
    background: var(--sda-indigo);
    border-radius: 14px 14px 4px 14px;
    color: #ffffff;
    flex-grow: 0;
    /* Streamlit centres a shrunk message bubble with ~130px auto side margins,
       which left short replies stranded in the middle of the row instead of
       tucked against the avatar. */
    margin: 0 !important;
    max-width: 85%;
}
.PANEL_CLS [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"])
    [data-testid="stChatMessageContent"] p {
    color: #ffffff;
}
.PANEL_CLS [data-testid="stChatMessageAvatarUser"],
.PANEL_CLS [data-testid="stChatMessageAvatarAssistant"] {
    width: 28px;
    height: 28px;
}
.PANEL_CLS [data-testid="stChatMessageAvatarAssistant"] {
    background-color: var(--sda-indigo) !important;
}
/* Streamlit's default user avatar is red, which fights the indigo palette. */
.PANEL_CLS [data-testid="stChatMessageAvatarUser"] {
    background-color: #9aa0b4 !important;
}

/* ---------------- input row + buttons ---------------- */
.PANEL_CLS [data-testid="stForm"] {
    border: 0;
    padding: 0;
    gap: 8px;
}
/* "Press Enter to submit form" — there is a Send button right there. */
.PANEL_CLS [data-testid="InputInstructions"] {
    display: none !important;
}
.PANEL_CLS [data-baseweb="input"] {
    border-radius: 999px;
    border: 1px solid var(--sda-line);
    background: var(--sda-card);
}
.PANEL_CLS [data-baseweb="input"]:focus-within {
    border-color: var(--sda-indigo);
    box-shadow: 0 0 0 3px var(--sda-indigo-50);
}
.PANEL_CLS [data-baseweb="input"] input {
    font-size: 13.5px;
    padding: 0.45rem 0.9rem;
}
.PANEL_CLS [data-testid="stFormSubmitButton"] button {
    border-radius: 999px;
    border: 0;
    background: var(--sda-indigo);
    color: #ffffff;
    font-weight: 600;
    font-size: 13.5px;
    box-shadow: 0 2px 8px rgba(59, 65, 214, 0.28);
    transition: background 0.15s ease, box-shadow 0.15s ease;
}
.PANEL_CLS [data-testid="stFormSubmitButton"] button:hover {
    background: var(--sda-indigo-600);
    box-shadow: 0 4px 14px rgba(59, 65, 214, 0.34);
}
/* the 👍/👎 · ticket · new-chat row */
.PANEL_CLS .stButton button {
    border-radius: 999px;
    border: 1px solid var(--sda-line);
    background: var(--sda-card);
    color: var(--sda-ink-2);
    font-size: 13px;
    font-weight: 600;
    transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;
}
.PANEL_CLS .stButton button:hover {
    border-color: var(--sda-indigo);
    color: var(--sda-indigo);
    background: #fafbff;
}

/* ---------------- busy state on the feedback buttons ----------------
   Streamlit has no loading state for a button, so the pressed one is disabled
   and its label faded out while a spinner turns in its place. The label keeps
   its box (opacity, not display) so the button does not resize mid-click. */
[class*="st-key-sdfb_busy"] button {
    position: relative;
}
[class*="st-key-sdfb_busy"] button p {
    opacity: 0;
}
[class*="st-key-sdfb_busy"] button::after {
    content: "";
    position: absolute;
    top: 50%;
    left: 50%;
    width: 15px;
    height: 15px;
    margin: -8px 0 0 -8px;
    border: 2px solid rgba(59, 65, 214, 0.25);
    border-top-color: var(--sda-indigo);
    border-radius: 50%;
    animation: sd-spin 0.7s linear infinite;
}
@keyframes sd-spin {
    to { transform: rotate(360deg); }
}

/* ---------------- typing indicator ----------------
   Fills the gap between "send" and the model's first streamed token; without
   it the bubble sits empty and the widget reads as hung. */
.sd-typing {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 2px;
}
.sd-typing span {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--sda-indigo, #3b41d6);
    opacity: 0.35;
    animation: sd-typing 1.2s infinite ease-in-out;
}
.sd-typing span:nth-child(2) { animation-delay: 0.18s; }
.sd-typing span:nth-child(3) { animation-delay: 0.36s; }
@keyframes sd-typing {
    0%, 80%, 100% { transform: translateY(0);     opacity: 0.35; }
    40%           { transform: translateY(-4px);  opacity: 1; }
}

/* ---------------- the JS host ----------------
   components.html always renders an iframe; this one only runs script against
   the parent document, so it is collapsed to nothing. */
.st-key-sdasstjs {
    height: 0;
    overflow: hidden;
}

/* ---------------- responsive ---------------- */
@media (max-width: 640px) {
    .ANCHOR_CLS {
        right: 0.9rem;
        bottom: 0.9rem;
    }
    .ANCHOR_CLS [data-testid="stPopover"] > div > button,
    .ANCHOR_CLS button[kind="secondary"] {
        width: 52px;
        height: 52px;
        min-height: 52px;
        background-size: 23px 23px, cover;
    }
    .ANCHOR_CLS .sd-greet {
        max-width: calc(100vw - 2rem);
        font-size: 13px;
    }
    /* 2.75rem, not 1.5rem: Streamlit's popper offsets the panel a few px left
       of the button, so a 100vw-1.5rem panel overhangs the viewport edge. */
    [data-testid="stPopoverBody"] {
        width: calc(100vw - 2.75rem) !important;
        max-width: calc(100vw - 2.75rem) !important;
        max-height: calc(100vh - 6rem) !important;
    }
}

/* Respect a stated preference for less motion: state, not movement. */
@media (prefers-reduced-motion: reduce) {
    .sd-typing span,
    .ANCHOR_CLS .sd-greet,
    .ANCHOR_CLS .sd-fab-badge {
        animation: none !important;
    }
    .sd-typing span { opacity: 0.55; }
    .ANCHOR_CLS [data-testid="stPopover"] > div > button {
        transition: none;
    }
}
"""

_CSS = (
    "<style>"
    + _CSS_TEMPLATE.replace("ANCHOR_CLS", _ANCHOR)
    .replace("PANEL_CLS", _PANEL)
    .replace("ICON_URL", _ICON)
    + "</style>"
)

# Three bouncing dots. role="status" so a screen reader announces the wait
# instead of silently skipping a decorative element.
TYPING_HTML = (
    '<div class="sd-typing" role="status" aria-label="Assistant is typing">'
    "<span></span><span></span><span></span>"
    "</div>"
)

PANEL_HEADER_HTML = (
    '<div class="sd-asst-head">'
    '<span class="av"></span>'
    "<span><b>SugboDoc Assistant</b>"
    "<span>Answers from the product documentation</span></span>"
    "</div>"
)


def inject() -> None:
    """Emit the stylesheet once per session run."""
    st.markdown(_CSS, unsafe_allow_html=True)
