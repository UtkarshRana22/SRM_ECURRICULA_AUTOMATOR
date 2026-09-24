"""
Very simple status-check module: given a live sunburst chart on screen,
reads and prints the status of one specific Unit / Session (both of its
SLO badges) -- no clicking, no navigation, just a read.

Kept as its own module, separate from login_automation.py (login flow) and
sunburst_navigator.py (full chart navigation + quiz answering), so this
simple starting point can be swapped out or extended later without
touching either of those.
"""

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC


SUNBURST_SVG_CSS = ".sunburst-wrapper svg"

NUM_UNITS = 5
NUM_SESSIONS = 12
NUM_BADGES = 2

FILL_STATUS = {
    "rgb(26, 188, 156)": "Completed",
    "rgb(247, 183, 49)": "In Progress",
    "rgb(252, 92, 101)": "Not Started",
}


def badge_g_index(unit: int, session: int, badge: int) -> int:
    return 66 + (unit - 1) * NUM_SESSIONS * NUM_BADGES + (session - 1) * NUM_BADGES + badge


# Reads the two status badges (SLO 1, SLO 2) for one specific Unit/Session,
# using the same <g>-tag array-filter indexing already confirmed correct
# for the full grid read.
READ_SESSION_STATUS_JS = r"""
(svg, badge1Index, badge2Index) => {
  const groups = Array.from(svg.children).filter(c => c.tagName === 'g');
  function readBadge(idx) {
    const g = groups[idx - 1];
    if (!g) return null;
    const p = g.querySelector('path.sunburst-main-arc');
    const t = g.querySelector('text');
    return {
      fill: p ? (p.style.fill || p.getAttribute('fill')) : null,
      text: t ? t.textContent.trim() : null,
    };
  }
  return { badge1: readBadge(badge1Index), badge2: readBadge(badge2Index) };
}
"""


def print_session_status(driver, wait, unit: int, session: int) -> dict:
    """Reads and prints the status of both SLO badges for one specific
    Unit / Session, directly from the sunburst chart already on screen.
    Returns the raw {badge1, badge2} result dict."""
    sunburst_svg = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, SUNBURST_SVG_CSS))
    )

    idx1 = badge_g_index(unit, session, 1)
    idx2 = badge_g_index(unit, session, 2)
    result = driver.execute_script(
        f"return ({READ_SESSION_STATUS_JS})(arguments[0], arguments[1], arguments[2]);",
        sunburst_svg, idx1, idx2,
    )

    print(f"\nUnit {unit} / Session {session}:")
    for badge_num, key in ((1, "badge1"), (2, "badge2")):
        cell = result.get(key) if result else None
        if not cell:
            print(f"  SLO {badge_num}: (not found)")
            continue
        status = FILL_STATUS.get(cell["fill"], cell["fill"])
        print(f"  Session {badge_num}: {status}")

    return result


def print_all_sessions_status(driver, wait) -> None:
    """Loops every Unit (1-5) / Session (1-12) and prints each one's status
    via print_session_status(). Still just reads -- no clicking."""
    for unit in range(1, NUM_UNITS + 1):
        for session in range(1, NUM_SESSIONS + 1):
            print_session_status(driver, wait, unit, session)
