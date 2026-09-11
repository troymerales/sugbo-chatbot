"""
SugboDoc app shell — the SaaS "eClinic" chrome shared by every page.

`render_shell(active)` paints:

* the **left navigation rail** (`st.sidebar`, restyled to match `web/dashboard.html`)
  — Dashboard / Consultation Transcript / Past Notes / Evaluation are real links;
  the rest of the eClinic modules are inert mock entries with hover only;
* the indigo **top bar** (clinic selector + user), and
* full-screen layout (Streamlit's header / menu / padding removed).

`panel("name")` is the content card used by the workspace pages, so they read
like the dashboard rather than like bare Streamlit widgets.

If a required key is missing it raises a one-off **alert dialog** (no status
panel — see `alert_missing_keys`). Streamlit-only: this is the mirror of
`assistant/` for the STT/home pages. Safe under AppTest — the nav is plain HTML,
so there's no `st.navigation` registry dependency.
"""

from __future__ import annotations

import base64
import functools
from contextlib import contextmanager

import streamlit as st

import config
from stt.config import get_settings


@functools.lru_cache(maxsize=1)
def _logo_uri() -> str | None:
    """The SugboDoc mark (``web/sugbodoc.png``) as a data: URI, so it can go
    straight into the rail's HTML. Falls back to the lettering mark if missing."""
    path = config.ROOT / "web" / "sugbodoc.png"
    try:
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
    except OSError:
        return None

# --------------------------------------------------------------------------- #
# Styling — palette + spacing lifted straight from web/dashboard.html
# --------------------------------------------------------------------------- #

_CSS = """
<style>
:root{
  --sd-indigo:#3b41d6; --sd-indigo-600:#333ac2; --sd-indigo-50:#eef0fe;
  --sd-ink:#1f2430; --sd-ink-2:#3a4152; --sd-muted:#6b7280;
  --sd-line:#e6e7ef; --sd-bg:#f4f5fb; --sd-card:#ffffff;
  --sd-ok:#12805c; --sd-ok-bg:#e5f4ee; --sd-warn:#a15c00; --sd-warn-bg:#fff7e6;
  --sd-danger:#b42318; --sd-danger-bg:#fdecea;
  --sd-r:14px; --sd-r-sm:10px;
  --sd-shadow:0 1px 2px rgba(31,36,48,.04), 0 4px 16px rgba(31,36,48,.06);
  --sd-shadow-lift:0 3px 8px rgba(59,65,214,.20), 0 10px 24px rgba(59,65,214,.16);
}

/* ---- full screen: drop Streamlit chrome ---- */
#MainMenu, header[data-testid="stHeader"], [data-testid="stToolbar"],
[data-testid="stDecoration"], [data-testid="stStatusWidget"], footer{
  display:none !important;
}
[data-testid="stAppViewContainer"], .stApp{ background:var(--sd-bg); }
[data-testid="stMain"]{ padding-top:0 !important; }
[data-testid="stMain"] .block-container,
[data-testid="stMainBlockContainer"]{
  padding:1.1rem 1.75rem 4rem !important;
  max-width:100% !important;
}
html, body, [class*="css"]{
  font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;
}
[data-testid="stMain"] ::-webkit-scrollbar{ width:10px; height:10px; }
[data-testid="stMain"] ::-webkit-scrollbar-thumb{
  background:#d7d9e8; border-radius:999px; border:2px solid var(--sd-bg);
}
[data-testid="stMain"] ::-webkit-scrollbar-thumb:hover{ background:#c2c5db; }

/* ---- left rail ----
   This is the web app's own navigation, not a Streamlit panel, so it never
   collapses: Streamlit's collapse/expand affordances are removed and the
   translateX it uses to slide the sidebar away is pinned back to 0. (Without
   this, one stray click on Streamlit's "<<" hides the rail for good, because
   the expand control lives in the stHeader we hide above.) */
[data-testid="stSidebar"]{
  background:var(--sd-card);
  border-right:1px solid var(--sd-line);
  transition:none !important;   /* the rail is fixed chrome: never slide it in */
  /* 270 not the reference's 236: "Consultation Transcript" is a longer label
     than anything in the static mock, and it wraps below ~265px. */
  width:270px !important; min-width:270px !important; max-width:270px !important;
  transform:none !important;
  margin-left:0 !important;
  visibility:visible !important;
  display:block !important;
}
[data-testid="stSidebar"][aria-expanded="false"]{ transform:none !important; }
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="stSidebarResizeHandle"]{ display:none !important; }
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"],
[data-testid="stSidebar"] .block-container{ padding:0.75rem 0.75rem 1rem; }
/* Streamlit pads stSidebarContent too; stacked on the padding above it left the
   rows ~172px wide, narrow enough to wrap "Consultation Transcript". */
[data-testid="stSidebar"] [data-testid="stSidebarContent"]{
  padding-left:0; padding-right:0;
  overflow-x:hidden;
  /* The module list is longer than any viewport, so the rail has to scroll --
     but a visible track reads as a seam in what is meant to be app chrome.
     Scrolling (wheel, trackpad, keyboard) still works; only the bar is gone. */
  overflow-y:auto;
  scrollbar-width:none;      /* Firefox */
  -ms-overflow-style:none;   /* legacy Edge */
}
[data-testid="stSidebar"] [data-testid="stSidebarContent"]::-webkit-scrollbar{
  display:none;              /* Chrome / Safari */
}
[data-testid="stSidebar"] [data-testid="stSidebarHeader"]{ min-height:0; padding:0; }

/* Same breakpoint the static dashboard used — the rail folds away on narrow screens. */
@media (max-width:900px){
  [data-testid="stSidebar"]{ display:none !important; }
}

.sd-brand{ display:flex; align-items:center; gap:9px; padding:2px 6px 12px; }
.sd-brand .mark{ width:34px; height:34px; flex:0 0 34px; }
/* provided PNG logo — shown as-is, proportions preserved */
.sd-brand img.mark{ object-fit:contain; display:block; }
/* fallback lettering mark, only if the PNG is missing */
.sd-brand span.mark{
  border-radius:10px;
  background:linear-gradient(135deg,#2bd4c4,#3b41d6);
  display:grid;place-items:center;color:#fff;font-weight:800;font-size:16px;
  box-shadow:0 4px 12px rgba(59,65,214,.28);
}
.sd-brand b{ font-size:18.5px; letter-spacing:-.2px; color:var(--sd-ink); }
.sd-brand b span{ color:var(--sd-indigo); }
.sd-tz{
  border:1px solid var(--sd-line); border-radius:var(--sd-r-sm); padding:8px 10px;
  margin:0 0 14px;
  color:var(--sd-muted); font-size:12px; display:flex; justify-content:space-between;
}

.sd-nav{ display:flex; flex-direction:column; gap:2px; }
.sd-nav a{
  position:relative;
  display:flex; align-items:center; gap:10px; padding:9px 10px; border-radius:var(--sd-r-sm);
  color:var(--sd-ink-2) !important; text-decoration:none; font-weight:500; font-size:13.5px;
  cursor:pointer; transition:background .14s ease, color .14s ease, transform .12s ease;
}
.sd-nav a .i{ width:18px; text-align:center; opacity:.85; }
.sd-nav a:hover{ background:#f3f4fb; }
.sd-nav a:active{ transform:translateY(1px); }
.sd-nav a.active{ background:var(--sd-indigo-50); color:var(--sd-indigo) !important; font-weight:700; }
.sd-nav .sub{ padding-left:38px; display:flex; flex-direction:column; }
.sd-nav .sub a{ padding:6px 8px; font-size:13px; color:var(--sd-muted) !important; font-weight:500; }
.sd-nav .sub a.active{ color:var(--sd-indigo); font-weight:700; background:transparent; }
.sd-foot{
  margin-top:14px; padding:9px 10px; display:flex; align-items:center; gap:9px;
  color:#c2410c; font-weight:600; font-size:13px; cursor:pointer;
}

/* ---- rail navigation buttons ----
   The four real destinations are st.buttons that call st.switch_page(), not
   <a href> anchors. An anchor is a full browser navigation: it re-boots the
   whole Streamlit frontend and opens a new WebSocket session (~3s locally,
   worse on Community Cloud, where that handshake crosses the internet), and
   the new session starts with an empty st.session_state -- so an in-progress
   transcript or assistant conversation was lost on every click. A button
   reruns over the socket that is already open (~200ms) and keeps state.
   These rules make the buttons indistinguishable from the inert .sd-nav
   anchors they sit among: ::before carries the icon (so a wrapped label hangs
   under the text, not under the icon) and ::after carries the active bar. */
[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{ gap:2px; }
/* Streamlit gives every markdown block a -16px bottom margin to cancel the
   trailing <p>'s margin. The rail chunks are flex divs with no such margin, so
   that -16px just dragged the next row up -- "Consultation Transcript" overlapped
   "Clinical Notes" by 14px while every other gap was 2px. */
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"]{ margin-bottom:0 !important; }

[class*="st-key-sdnav_"] button,
[class*="st-key-sdnavon_"] button,
[class*="st-key-sdsub_"] button,
[class*="st-key-sdsubon_"] button{
  position:relative;
  width:100%; justify-content:flex-start; text-align:left;
  border:0 !important; background:transparent !important; box-shadow:none !important;
  padding:9px 10px 9px 38px; border-radius:var(--sd-r-sm); min-height:0;
  color:var(--sd-ink-2) !important; font-weight:500; font-size:13.5px; line-height:1.3;
  transition:background .14s ease, color .14s ease, transform .12s ease;
}
[class*="st-key-sdnav_"] button p,
[class*="st-key-sdnavon_"] button p{
  font-weight:inherit; margin:0;
  font-size:13.5px !important; line-height:21.6px !important;
}
[class*="st-key-sdsub_"] button p,
[class*="st-key-sdsubon_"] button p{
  font-weight:inherit; margin:0;
  font-size:13px !important; line-height:20.8px !important;
}

/* icon column, matching .sd-nav a .i */
[class*="st-key-sdnav_"] button::before,
[class*="st-key-sdnavon_"] button::before{
  position:absolute; left:10px; top:9px; width:18px; text-align:center;
  opacity:.85; font-weight:400;
}
[class*="st-key-sdnav_dashboard"] button::before,
[class*="st-key-sdnavon_dashboard"] button::before{ content:"▦"; }
[class*="st-key-sdnav_consultation-transcript"] button::before,
[class*="st-key-sdnavon_consultation-transcript"] button::before{ content:"🎙️"; }

[class*="st-key-sdnav_"] button:hover,
[class*="st-key-sdsub_"] button:hover{ background:#f3f4fb !important; }
[class*="st-key-sdnav_"] button:active,
[class*="st-key-sdnavon_"] button:active,
[class*="st-key-sdsub_"] button:active,
[class*="st-key-sdsubon_"] button:active{ transform:translateY(1px); }
[class*="st-key-sdnav_"] button:focus,
[class*="st-key-sdnavon_"] button:focus,
[class*="st-key-sdsub_"] button:focus,
[class*="st-key-sdsubon_"] button:focus{ box-shadow:none !important; outline:none; }

/* sub-level rows -- indented, smaller, no icon column */
[class*="st-key-sdsub_"], [class*="st-key-sdsubon_"]{ padding-left:38px; box-sizing:border-box; }
[class*="st-key-sdsub_"] button,
[class*="st-key-sdsubon_"] button{
  padding:6px 8px; font-size:13px; color:var(--sd-muted) !important;
}

/* active row -- the indigo pill the static mock uses. Must come after the
   sub-level block: both sides are !important at equal specificity, so the
   later rule wins and an active sub would otherwise stay muted grey.
   Apply text-align:left to ALL nav buttons (active and inactive) to prevent
   Streamlit's centering behavior. */
[class*="st-key-sdnav_"] button,
[class*="st-key-sdnavon_"] button,
[class*="st-key-sdsub_"] button,
[class*="st-key-sdsubon_"] button{
  text-align:left !important;
}
[class*="st-key-sdnav_"] button > div,
[class*="st-key-sdnavon_"] button > div,
[class*="st-key-sdsub_"] button > div,
[class*="st-key-sdsubon_"] button > div{
  justify-content:flex-start !important;
}
[class*="st-key-sdnav_"] button p,
[class*="st-key-sdnavon_"] button p,
[class*="st-key-sdsub_"] button p,
[class*="st-key-sdsubon_"] button p{
  text-align:left !important;
  margin:0 !important;
}
[class*="st-key-sdnavon_"],
[class*="st-key-sdsubon_"]{
  background:var(--sd-indigo-50) !important;
}
[class*="st-key-sdnavon_"] button,
[class*="st-key-sdsubon_"] button{
  color:var(--sd-indigo) !important; font-weight:700;
}

/* ---- inert mock rows read as clearly unavailable ----
   Only the *active* real destination gets the indigo pill (rules above); every
   real button that isn't the current page keeps its default look. The inert
   eClinic modules + the feedback row are dimmed so they obviously don't work. */
.sd-nav a, .sd-nav .sub a, .sd-foot{
  color:var(--sd-muted) !important; font-weight:500 !important;
  opacity:.55; cursor:default;
}
.sd-nav a .i{ opacity:.4; }
.sd-nav a:hover{ background:transparent; }

/* ---- top bar (full-bleed via the block-container padding) ---- */
.sd-topbar{
  background:linear-gradient(100deg,#3b41d6 0%,#4a50e4 55%,#5a54e8 100%);
  color:#fff;
  margin:-1.1rem -1.75rem 1.4rem; padding:13px 26px;
  display:flex; align-items:center; justify-content:space-between; gap:16px;
  box-shadow:0 2px 14px rgba(59,65,214,.22);
}
.sd-topbar .clinic{
  background:#fff; color:var(--sd-ink); border-radius:12px; padding:7px 13px;
  display:flex; align-items:center; gap:10px;
  box-shadow:0 2px 8px rgba(15,18,40,.14);
}
.sd-topbar .clinic .logo{
  width:32px;height:32px;border-radius:9px;background:#e9ecff;
  display:grid;place-items:center;font-size:16px;
}
.sd-topbar .clinic .t b{ display:block; font-size:13px; letter-spacing:-.1px; }
.sd-topbar .clinic .t span{ font-size:11px; color:var(--sd-muted); }
.sd-topbar .right{ display:flex; align-items:center; gap:16px; }
.sd-topbar .bell{
  width:34px;height:34px;border-radius:50%;display:grid;place-items:center;
  background:rgba(255,255,255,.16); font-size:15px; cursor:pointer;
  transition:background .14s ease;
}
.sd-topbar .bell:hover{ background:rgba(255,255,255,.26); }
.sd-topbar .me{ display:flex; align-items:center; gap:10px; font-weight:600; font-size:13.5px; }
.sd-topbar .me .av{
  width:36px;height:36px;border-radius:50%;background:#c7ccf5;
  display:grid;place-items:center;color:#333ac2;font-weight:700;
  box-shadow:0 0 0 2px rgba(255,255,255,.45);
}

/* ---- typography ---- */
[data-testid="stMain"] h1{
  font-size:25px; font-weight:750; letter-spacing:-.4px; color:var(--sd-ink);
}
[data-testid="stMain"] h2{ font-size:19px; font-weight:700; letter-spacing:-.2px; }
[data-testid="stMain"] h3{
  font-size:16.5px; font-weight:700; letter-spacing:-.1px; color:var(--sd-ink);
}
[data-testid="stMain"] [data-testid="stCaptionContainer"],
[data-testid="stMain"] [data-testid="stCaptionContainer"] p{
  color:var(--sd-muted); font-size:12.8px;
}

/* ---- content cards: shell.panel() containers ---- */
[class*="st-key-sdpanel"]{
  background:var(--sd-card);
  border:1px solid var(--sd-line);
  border-radius:var(--sd-r);
  padding:18px 20px 14px;
  box-shadow:var(--sd-shadow);
  margin-bottom:2px;
}
[data-testid="stMain"] [data-testid="stExpander"]{
  border:1px solid var(--sd-line) !important; border-radius:var(--sd-r) !important;
  background:var(--sd-card); box-shadow:var(--sd-shadow); overflow:hidden;
}
[data-testid="stMain"] [data-testid="stExpander"] summary{ font-weight:600; }
[data-testid="stMain"] [data-testid="stExpander"] summary:hover{ color:var(--sd-indigo); }

[data-testid="stMain"] [data-testid="stMetric"]{
  background:var(--sd-card); border:1px solid var(--sd-line); border-radius:var(--sd-r);
  padding:13px 16px; box-shadow:var(--sd-shadow);
}
[data-testid="stMain"] [data-testid="stMetricLabel"] p{
  color:var(--sd-muted); font-size:11.5px; text-transform:uppercase; letter-spacing:.4px;
  font-weight:600;
}
[data-testid="stMain"] [data-testid="stMetricValue"]{
  font-size:23px; font-weight:750; color:var(--sd-ink);
}

/* ---- buttons ---- */
[data-testid="stMain"] .stButton > button,
[data-testid="stMain"] .stDownloadButton > button,
[data-testid="stMain"] .stFormSubmitButton > button{
  border-radius:var(--sd-r-sm); font-weight:600; font-size:13.5px;
  padding:.5rem 1rem; border:1px solid var(--sd-line); background:var(--sd-card);
  color:var(--sd-ink-2);
  transition:background .14s ease, border-color .14s ease, box-shadow .14s ease, transform .1s ease;
}
[data-testid="stMain"] .stButton > button:hover,
[data-testid="stMain"] .stDownloadButton > button:hover,
[data-testid="stMain"] .stFormSubmitButton > button:hover{
  border-color:var(--sd-indigo); color:var(--sd-indigo); background:#fafbff;
}
[data-testid="stMain"] .stButton > button:active{ transform:translateY(1px); }
[data-testid="stMain"] .stButton > button[kind="primary"],
[data-testid="stMain"] .stFormSubmitButton > button[kind="primary"]{
  background:var(--sd-indigo); border-color:var(--sd-indigo); color:#fff;
  box-shadow:0 2px 8px rgba(59,65,214,.28);
}
[data-testid="stMain"] .stButton > button[kind="primary"]:hover,
[data-testid="stMain"] .stFormSubmitButton > button[kind="primary"]:hover{
  background:var(--sd-indigo-600); border-color:var(--sd-indigo-600); color:#fff;
  box-shadow:var(--sd-shadow-lift);
}
[data-testid="stMain"] .stButton > button:disabled,
[data-testid="stMain"] .stButton > button:disabled:hover{
  background:#f1f2f7; border-color:var(--sd-line); color:#a8adbd;
  box-shadow:none; transform:none;
}

/* ---- inputs ---- */
[data-testid="stMain"] [data-baseweb="input"],
[data-testid="stMain"] [data-baseweb="textarea"],
[data-testid="stMain"] [data-baseweb="select"] > div{
  border-radius:var(--sd-r-sm) !important;
  border:1px solid var(--sd-line) !important;
  background:var(--sd-card) !important;
  transition:border-color .14s ease, box-shadow .14s ease;
}
[data-testid="stMain"] [data-baseweb="input"]:hover,
[data-testid="stMain"] [data-baseweb="textarea"]:hover,
[data-testid="stMain"] [data-baseweb="select"] > div:hover{ border-color:#c9cce0 !important; }
[data-testid="stMain"] [data-baseweb="input"]:focus-within,
[data-testid="stMain"] [data-baseweb="textarea"]:focus-within,
[data-testid="stMain"] [data-baseweb="select"] > div:focus-within{
  border-color:var(--sd-indigo) !important;
  box-shadow:0 0 0 3px rgba(59,65,214,.14) !important;
}
[data-testid="stMain"] input, [data-testid="stMain"] textarea{ font-size:13.5px !important; }
[data-testid="stMain"] label p{ font-size:13px !important; font-weight:600; color:var(--sd-ink-2); }

/* ======================================================================
   Consultation Transcript page
   The workflow is Record -> Transcribe -> Document. The layout mirrors that:
   a narrow, centred recording card is the focal point; once a transcript
   exists it collapses to a one-line summary and the document + SOAP cards
   take over at a wider reading width. All of it uses the same tokens as the
   dashboard (card, --sd-r, --sd-shadow, indigo).
   ====================================================================== */

/* ---- workflow stepper (pagehead, right side) ---- */
.sd-steps{ display:flex; align-items:center; gap:8px; font-size:12.5px; font-weight:600; }
.sd-steps .step{ display:flex; align-items:center; gap:7px; color:var(--sd-muted); }
.sd-steps .step .dot{
  width:20px; height:20px; border-radius:50%; display:grid; place-items:center;
  font-size:11px; background:var(--sd-line); color:var(--sd-muted);
}
.sd-steps .step.cur{ color:var(--sd-indigo); }
.sd-steps .step.cur .dot{ background:var(--sd-indigo); color:#fff; }
.sd-steps .step.done{ color:var(--sd-ink-2); }
.sd-steps .step.done .dot{ background:var(--sd-ok-bg); color:var(--sd-ok); }
.sd-steps .sep{ width:20px; height:1px; background:var(--sd-line); }
@media (max-width:760px){ .sd-steps .step span{ display:none; } }

/* ---- the recording hero card ---- */
[class*="st-key-sdpanel_record"]{
  text-align:center; padding:28px 26px 22px;
}
.sd-rec-title{ font-size:17px; font-weight:700; color:var(--sd-ink); margin:0 0 4px; }
.sd-rec-sub{ font-size:12.8px; color:var(--sd-muted); margin:0 auto 18px; max-width:none; line-height:1.5; }

/* ==================================================================
   st.audio_input — three states, one layout that never jumps.

     idle      : "Record" button, and no "Stop recording"/"Play"/"Pause"
     recording : "Stop recording" button  -> big red pulsing mic + live
                 waveform + running timer
     recorded  : "Play"/"Pause" button    -> a compact review player.
                 NB a "Record" button is also present here (to re-record),
                 so idle must be detected by the *absence* of the others.

   The widget's flex row is re-stacked as a centred column pinned to the
   top (justify-content:flex-start), so the mic sits at a fixed position
   and the waveform / timer simply appear in the space below it — earlier
   `center` re-centred the whole stack and shoved the mic upward the
   instant recording began. --sd-mic is the single size knob. */
[class*="st-key-sdpanel_record"] [data-testid="stAudioInput"]{
  --sd-mic:96px;
  border:0; background:none; display:flex; justify-content:center;
  overflow:visible !important;
}
[class*="st-key-sdpanel_record"] [data-testid="stAudioInput"] > div{
  flex-direction:column !important; align-items:center !important;
  justify-content:flex-start !important; background:none !important;
  overflow:visible !important;
  gap:6px; width:100%; padding:0 !important;
  min-height:calc(var(--sd-mic));
}
[class*="st-key-sdpanel_record"] [data-testid="stAudioInput"] > div > *{ margin:0 !important; }
[class*="st-key-sdpanel_record"] [data-testid="stAudioInput"] [data-testid="stElementToolbar"]{ display:none !important; }

/* every wrapper span/div around the button -> zero-margin flex-centre box, so
   the mic (and the stop square) lands dead centre whatever state we're in */
[class*="st-key-sdpanel_record"] [data-testid="stAudioInput"] *:has(> [data-testid="stAudioInputActionButton"]),
[class*="st-key-sdpanel_record"] [data-testid="stAudioInput"] *:has(> * > [data-testid="stAudioInputActionButton"]){
  margin:0 !important; padding:0 !important; gap:6px !important;
  display:flex !important; align-items:center !important; justify-content:center !important;
  width:auto !important; height:auto !important;
}
[class*="st-key-sdpanel_record"] [data-testid="stAudioInputActionButton"]{
  width:var(--sd-mic) !important; height:var(--sd-mic) !important;
  min-width:var(--sd-mic) !important; flex:0 0 var(--sd-mic) !important;
  border-radius:50% !important; padding:0 !important;
  display:flex !important; align-items:center !important; justify-content:center !important;
  background:linear-gradient(135deg,#4a50e4,#3b41d6) !important;
  box-shadow:0 12px 30px rgba(59,65,214,.36) !important;
  transition:transform .16s cubic-bezier(.2,.8,.3,1), box-shadow .16s ease, background .16s ease !important;
}
[class*="st-key-sdpanel_record"] [data-testid="stAudioInputActionButton"] svg{
  width:40% !important; height:40% !important; display:block !important;
  fill:#fff !important; color:#fff !important;
}
[class*="st-key-sdpanel_record"] [data-testid="stAudioInputActionButton"]:hover{
  transform:translateY(-2px) scale(1.05);
  box-shadow:0 16px 34px rgba(59,65,214,.44) !important;
}
[class*="st-key-sdpanel_record"] [data-testid="stAudioInputActionButton"]:active{ transform:scale(.96); }
[class*="st-key-sdpanel_record"] [data-testid="stAudioInputWaveformTimeCode"]{
  font-variant-numeric:tabular-nums; color:var(--sd-ink-2); font-weight:600; font-size:13px;
}

/* The WaveSurfer waveform is hidden in every state: it only renders when its
   container is sized at init time, which our restacked layout can't guarantee,
   and a 1px sliver looks worse than none. The pulsing mic + the timer carry
   the feedback instead. */
[class*="st-key-sdpanel_record"] [data-testid="stAudioInput"] [data-testid="stAudioInputWaveSurfer"]{
  display:none !important;
}
/* idle: no timer either */
[class*="st-key-sdpanel_record"] [data-testid="stAudioInput"]:not(:has([aria-label="Stop recording"])):not(:has([aria-label="Play"])):not(:has([aria-label="Pause"])) [data-testid="stAudioInputWaveformTimeCode"]{
  display:none !important;
}

/* recording: red pulsing stop + running timer below the mic */
[class*="st-key-sdpanel_record"] [data-testid="stAudioInput"]:has([aria-label="Stop recording"]) [data-testid="stAudioInputActionButton"]{
  background:linear-gradient(135deg,#e5555b,#d64550) !important;
  box-shadow:0 10px 26px rgba(214,69,80,.4) !important;
  animation:sd-rec-pulse 1.6s ease-out infinite;
}

/* recorded: a compact review row — Play (indigo, 44px) · duration · a ghost
   re-record button — centred in the same reserved box */
[class*="st-key-sdpanel_record"] [data-testid="stAudioInput"]:is(:has([aria-label="Play"]),:has([aria-label="Pause"])) > div{
  justify-content:center !important;
}
[class*="st-key-sdpanel_record"] [data-testid="stAudioInput"]:is(:has([aria-label="Play"]),:has([aria-label="Pause"])) *:has(> [data-testid="stAudioInputActionButton"]){
  flex-direction:row !important; gap:12px;
}
[class*="st-key-sdpanel_record"] [data-testid="stAudioInput"]:is(:has([aria-label="Play"]),:has([aria-label="Pause"])) [data-testid="stAudioInputActionButton"]{
  width:44px !important; height:44px !important; min-width:44px !important; flex:0 0 44px !important;
  box-shadow:0 4px 12px rgba(59,65,214,.24) !important;
}
[class*="st-key-sdpanel_record"] [data-testid="stAudioInput"]:is(:has([aria-label="Play"]),:has([aria-label="Pause"])) [data-testid="stAudioInputActionButton"][aria-label="Record"]{
  background:var(--sd-card) !important; border:1px solid var(--sd-line) !important; box-shadow:none !important;
}
[class*="st-key-sdpanel_record"] [data-testid="stAudioInput"]:is(:has([aria-label="Play"]),:has([aria-label="Pause"])) [data-testid="stAudioInputActionButton"][aria-label="Record"] svg{
  fill:var(--sd-ink-2) !important; color:var(--sd-ink-2) !important;
}
@keyframes sd-rec-pulse{
  0%{ box-shadow:0 0 0 0 rgba(229,72,77,.45); }
  70%{ box-shadow:0 0 0 16px rgba(229,72,77,0); }
  100%{ box-shadow:0 0 0 0 rgba(229,72,77,0); }
}

/* the "or upload a recording" link, centred under the mic */
[class*="st-key-sdpanel_record"] [data-testid="stFileUploader"]{ margin:6px 0 2px; }
[class*="st-key-sdpanel_record"] [data-testid="stFileUploaderDropzone"]{
  border:0 !important; background:none !important; padding:0 !important;
  min-height:0 !important; height:auto !important; justify-content:center;
}
[class*="st-key-sdpanel_record"] [data-testid="stFileUploaderDropzoneInstructions"]{ display:none !important; }
[class*="st-key-sdpanel_record"] [data-testid="stFileUploaderDropzone"] button{
  background:none !important; border:0 !important; box-shadow:none !important;
  padding:0 !important; min-height:auto !important; height:auto !important;
  color:transparent !important; font-size:0 !important; width:auto !important;
  display:inline !important;
}
[class*="st-key-sdpanel_record"] [data-testid="stFileUploaderDropzone"] button::after{
  content:"or upload a recording";
  font-size:12.5px; font-weight:500; color:var(--sd-muted);
  text-decoration:underline; text-underline-offset:2px;
  display:block !important; margin-top:-4px;
}
[class*="st-key-sdpanel_record"] [data-testid="stFileUploaderDropzone"] button:hover::after{ color:var(--sd-indigo); }
[data-testid="stMain"] [data-testid="stFileUploaderFile"]{ font-size:12.5px; padding:4px 0; }

/* thin rule between capture and the patient-detail fields inside the hero */
[class*="st-key-sdpanel_record"] hr{ margin:14px 0 12px; }
[class*="st-key-sdpanel_record"] [data-testid="stTextInput"] label p{ font-weight:600; }

/* "discard recording" — a small ✕ pinned onto the audio-input's own
   play / re-record row (only shown once a take exists), vertically centred
   against the mic, sitting just inside the card's right edge. */
[class*="st-key-sdrec_wrap"]{ position:relative; }
[class*="st-key-sdrec_reset"]{
  position:absolute; top:7px; height:44px; z-index:2;  /* == the play-button row */
  left:calc(50% + 56px); right:auto;                   /* just past the Play button */
  display:flex; align-items:center; width:auto !important;
}
[class*="st-key-sdrec_reset"] button,
[class*="st-key-sdrec_reset"] button:hover,
[class*="st-key-sdrec_reset"] button:active,
[class*="st-key-sdrec_reset"] button:focus{
  background:var(--sd-card) !important; border:1px solid var(--sd-line) !important;
  box-shadow:none !important; border-radius:50% !important;
  width:30px !important; height:30px !important; min-height:0 !important;
  padding:0 !important; font-size:13px; line-height:1;
  color:var(--sd-muted) !important; font-weight:600;
}
[class*="st-key-sdrec_reset"] button:hover{
  border-color:var(--sd-danger) !important; color:var(--sd-danger) !important;
}

/* Transcribe button while the ASR call runs: it stays full primary-indigo (not
   the greyed :disabled look) with a spinner set just before the label. */
[class*="st-key-sdbtn_busy_transcribe"] button:disabled,
[class*="st-key-sdbtn_busy_transcribe"] button:disabled:hover{
  background:var(--sd-indigo) !important; border-color:var(--sd-indigo) !important;
  color:#fff !important; box-shadow:0 2px 8px rgba(59,65,214,.28) !important;
  opacity:1 !important; cursor:progress;
  display:flex; align-items:center; justify-content:center; gap:9px;
}
[class*="st-key-sdbtn_busy_transcribe"] button:disabled::before{
  content:""; flex:0 0 14px; width:14px; height:14px; border-radius:50%;
  border:2px solid rgba(255,255,255,.35); border-top-color:#fff;
  animation:sd-btn-spin .7s linear infinite;
}
@keyframes sd-btn-spin{ to{ transform:rotate(360deg); } }

/* ---- recorded summary strip (after transcription) ---- */
[class*="st-key-sdpanel_recorded"]{
  padding:12px 16px; display:flex; align-items:center;
}
.sd-recdone{ display:flex; align-items:center; gap:10px; font-size:13px; color:var(--sd-ink-2); }
.sd-recdone .ok{
  width:22px; height:22px; border-radius:50%; background:var(--sd-ok-bg); color:var(--sd-ok);
  display:grid; place-items:center; font-size:12px; flex:0 0 22px;
}
.sd-recdone b{ color:var(--sd-ink); }
.sd-recdone .meta{ color:var(--sd-muted); }

/* ---- transcript: a document surface, not a form field ---- */
[class*="st-key-sdpanel_transcript"]{ padding:18px 22px 16px; }
[class*="st-key-sdpanel_transcript"] [data-testid="stTextArea"] textarea{
  font-size:14.5px !important; line-height:1.72 !important;
  background:#fcfcff !important; border-color:#e9eaf4 !important;
  padding:14px 16px !important; min-height:210px;
}
.sd-doc-head{ display:flex; align-items:baseline; gap:10px; margin-bottom:8px; }
.sd-doc-head h3{ margin:0; }
.sd-chip{
  font-size:11.5px; font-weight:600; color:var(--sd-muted);
  background:var(--sd-bg); border:1px solid var(--sd-line); border-radius:999px;
  padding:2px 9px;
}

/* ---- SOAP: a 2x2 workspace, each quadrant lightly accented ---- */
[class*="st-key-sdpanel_soap"]{ padding:18px 22px 16px; }
[class*="st-key-soap_cell_"], [class*="st-key-pn_soap_cell_"]{
  background:#fcfcff; border:1px solid #e9eaf4; border-left:3px solid var(--sd-line);
  border-radius:var(--sd-r-sm); padding:10px 12px 4px; margin-bottom:10px;
}
[class*="_cell_subjective"]{ border-left-color:var(--sd-indigo); }
[class*="_cell_objective"]{ border-left-color:#2bb8ab; }
[class*="_cell_assessment"]{ border-left-color:var(--sd-warn); }
[class*="_cell_plan"]{ border-left-color:var(--sd-ok); }
[class*="st-key-soap_cell_"] textarea, [class*="st-key-pn_soap_cell_"] textarea{
  border:0 !important; background:none !important; padding:2px 0 !important;
  font-size:13.5px !important; line-height:1.6 !important; min-height:120px;
}
[class*="st-key-soap_cell_"] label p, [class*="st-key-pn_soap_cell_"] label p{
  text-transform:uppercase; letter-spacing:.5px; font-size:11px !important;
  color:var(--sd-muted); font-weight:700;
}
.sd-soap-toolbar{ font-size:12.5px; color:var(--sd-muted); margin:2px 0 12px; }

/* ---- save: a quiet footer, not another hero card ---- */
[class*="st-key-sdpanel_save"]{
  padding:14px 18px; background:#fbfbfe;
}
[class*="st-key-sdpanel_save"] label p{ font-weight:600; }

/* ---- alerts ----
   Streamlit 1.49 carries the variant on an inner stAlertContent* element, not a
   `kind` attribute on the container, so these key off :has(). */
[data-testid="stMain"] [data-testid="stAlertContainer"]{
  border-radius:var(--sd-r-sm); border:1px solid transparent; font-size:13.3px;
}
[data-testid="stMain"] [data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]){
  background:var(--sd-indigo-50) !important; border-color:#d5d9fb; color:#2f3590 !important;
}
[data-testid="stMain"] [data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]){
  background:var(--sd-ok-bg) !important; border-color:#bfe3d3; color:#0e6b4d !important;
}
[data-testid="stMain"] [data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]){
  background:var(--sd-warn-bg) !important; border-color:#f0c36d; color:var(--sd-warn) !important;
}
[data-testid="stMain"] [data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]){
  background:var(--sd-danger-bg) !important; border-color:#f3c0ba; color:var(--sd-danger) !important;
}

/* ---- data + misc ---- */
[data-testid="stMain"] [data-testid="stDataFrame"]{
  border:1px solid var(--sd-line); border-radius:var(--sd-r); overflow:hidden;
  box-shadow:var(--sd-shadow);
}
/* A table already sitting inside a panel is a sub-element, not a second card:
   drop the lift and match the panel's inner radius so it doesn't read as
   card-in-card (Past Notes browse list, Evaluation results). */
[class*="st-key-sdpanel"] [data-testid="stDataFrame"]{
  border-radius:var(--sd-r-sm); box-shadow:none;
}
[data-testid="stMain"] [data-testid="stProgress"] > div > div > div > div{
  background:var(--sd-indigo);
}
[data-testid="stMain"] hr{ border-color:var(--sd-line); margin:1.1rem 0; }
[data-testid="stMain"] a{ color:var(--sd-indigo); }
</style>
"""

_TOPBAR = """
<div class="sd-topbar">
  <div class="clinic">
    <span class="logo">&#127973;</span>
    <div class="t"><b>SugboDoc eClinic</b><span>Talamban Branch</span></div>
  </div>
  <div class="right">
    <span class="bell">&#128276;</span>
    <div class="me"><span class="av">FV</span> Francesca Villanueva</div>
  </div>
</div>
"""

# Modules shown above "Consultation Transcript" in the rail — inert mockups.
# The real eClinic's module list, in its order. Everything here is an inert
# mockup; only the four entries rendered as buttons actually go anywhere.
# "Admin", "Staff" and "PhilHealth" are the sub-rows under Dashboard, so they
# aren't repeated at top level.
_MOCK_TOP = [
    ("Patient Worklist", "&#128101;"),
    ("Tasks Worklist", "&#9745;"),
    ("Encounter", "&#127973;"),
    ("Immunization", "&#128137;"),
    ("Schedule", "&#128197;"),
    ("Appointment", "&#128198;"),
    ("Clinical Notes", "&#128221;"),
]

# Shown below the Consultation Transcript block.
_MOCK_BOTTOM = [
    ("Prescription", "&#128196;"),
    ("Bills and Payments", "&#129534;"),
    ("Archive", "&#128452;&#65039;"),
    ("Payout", "&#128176;"),
    ("Medication", "&#128138;"),
    ("Staff Management", "&#128100;"),
    ("Locations", "&#128205;"),
    ("Stock Count", "&#128290;"),
    ("Inventory", "&#128230;"),
    ("Account Settings", "&#9881;&#65039;"),
    ("Subscription", "&#128179;"),
    ("Facility Settings", "&#127970;"),
    ("Inventory Report", "&#128200;"),
    ("Storage", "&#9729;"),
]


def _mock(icon: str, label: str) -> str:
    """An inert rail row — the eClinic modules this prototype doesn't implement."""
    return f'<a><span class="i">{icon}</span> {label}</a>'


# The rail is rendered as three HTML chunks with the real destinations, which
# are Streamlit buttons, interleaved between them (see the "rail navigation
# buttons" note in the stylesheet for why they aren't anchors). Each chunk has
# to be balanced HTML on its own: Streamlit renders every st.markdown call into
# its own container, so a <div> can't be left open across a button.
def _rail_head() -> str:
    uri = _logo_uri()
    mark = (f'<img class="mark" src="{uri}" alt="SugboDoc">' if uri
            else '<span class="mark">S</span>')
    return (
        f'<div class="sd-brand">{mark}<b>Sugbo<span>Doc</span></b></div>'
        '<div class="sd-tz">(GMT+08:00) Philippine Time <span>&#9662;</span></div>'
    )

_RAIL_MID = (
    '<div class="sd-nav">'
    '<div class="sub"><a>Admin</a><a>Staff</a><a>PhilHealth Claims</a></div>'
    + "".join(_mock(icon, label) for label, icon in _MOCK_TOP)
    + "</div>"
)

_RAIL_TAIL = (
    '<div class="sd-nav">'
    + "".join(_mock(icon, label) for label, icon in _MOCK_BOTTOM)
    + "</div>"
    '<div class="sd-foot"><span class="i">&#128681;</span> Send Feedback</div>'
)

# slug -> the page file st.switch_page() jumps to.
_PAGE_FILES = {
    "dashboard": "home.py",
    "consultation-transcript": "pages/1_Consultation_Transcript.py",
    "past-notes": "pages/2_Past_Notes.py",
    "evaluation": "pages/3_Evaluation.py",
}


def _nav_button(slug: str, label: str, active: str | None, *, sub: bool = False) -> None:
    """One real rail row. The active state is carried in the widget key rather
    than a class attribute — Streamlit turns the key into an ``st-key-…`` class,
    which is the only styling hook a widget gives you."""
    prefix = ("sdsub" if sub else "sdnav") + ("on_" if active == slug else "_")
    if st.button(label, key=f"{prefix}{slug}", use_container_width=True):
        st.switch_page(_PAGE_FILES[slug])


def _render_rail(active: str | None) -> None:
    st.markdown(_rail_head(), unsafe_allow_html=True)
    _nav_button("dashboard", "Dashboard", active)
    st.markdown(_RAIL_MID, unsafe_allow_html=True)
    _nav_button("consultation-transcript", "Consultation Transcript", active)
    _nav_button("past-notes", "Past Notes", active, sub=True)
    _nav_button("evaluation", "Evaluation", active, sub=True)
    st.markdown(_RAIL_TAIL, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Content cards
# --------------------------------------------------------------------------- #

@contextmanager
def panel(name: str):
    """An eClinic content card — the workspace equivalent of the dashboard's
    `.panel`. Usage::

        with shell.panel("audio"):
            st.subheader("1 · Audio")
            ...

    ``name`` only has to be unique within the page; it becomes the container's
    ``st-key-sdpanel_<name>`` class, which is what the stylesheet hooks onto.
    """
    with st.container(key=f"sdpanel_{name}"):
        yield


# --------------------------------------------------------------------------- #
# Missing-key alert  (a dialog, not a sidebar panel)
# --------------------------------------------------------------------------- #

@st.dialog("Configuration needed")
def _missing_keys_dialog(missing: list[tuple[str, str]]) -> None:
    st.write("Some keys aren't set, so part of the app is disabled:")
    for name, what in missing:
        st.markdown(f"- **`{name}`** — needed for {what}")
    st.caption(
        "Add them to `.streamlit/secrets.toml` (or the app's **Secrets** on "
        "Streamlit Community Cloud) and rerun. To try the app with no keys, run it "
        "with `LLM_BACKEND=mock`."
    )


def alert_missing_keys() -> None:
    """Pop a one-off dialog when a required key is missing. No-op under the mock
    backend and after it's been shown once this session."""
    if getattr(config, "LLM_BACKEND", "gemini") == "mock":
        return
    if st.session_state.get("_sd_key_alert_seen"):
        return

    missing: list[tuple[str, str]] = []
    if not config.get_api_key():
        missing.append(("GEMINI_API_KEY", "chatbot answers and SOAP note / extract / review"))
    if not get_settings().hf_token:
        missing.append(("HF_TOKEN", "Bisaya/Cebuano speech-to-text"))

    if missing:
        st.session_state["_sd_key_alert_seen"] = True
        _missing_keys_dialog(missing)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def render_shell(active: str | None = None, *, topbar: bool = True) -> None:
    """Paint the shell. ``active`` is a page ``url_path`` (``"dashboard"``,
    ``"consultation-transcript"``, ``"past-notes"``, ``"evaluation"``)."""
    st.markdown(_CSS, unsafe_allow_html=True)
    with st.sidebar:
        _render_rail(active)
    if topbar:
        st.markdown(_TOPBAR, unsafe_allow_html=True)
    alert_missing_keys()
