"""
Sunburst chart navigation for the SRM eCurricula course page.

Kept as its own module (separate from login_automation.py) so changes to
the chart-navigation / quiz-answering logic don't require touching or
re-pushing the login script.

Confirmed structure of the chart's 186 top-level <g> elements (verified
against real rendered markup):
    g[1]        = center circle (subject code)
    g[2..6]     = Unit 1..5 arcs
    g[7..66]    = Session arcs, grouped per unit, 12 each
                  (Unit u, Session s) -> g[6 + (u-1)*12 + s]
    g[67..186]  = Status badges, grouped per unit, 24 each (12 sessions x 2)
                  (Unit u, Session s, Badge b in {1,2})
                  -> g[66 + (u-1)*24 + (s-1)*2 + b]
Colors: green rgb(26,188,156)=Completed, orange rgb(247,183,49)=In
Progress, red rgb(252,92,101)=Not Started.

Usage from login_automation.py (or any script that already has a logged-in
`driver`/`wait` sitting on the subject's sunburst page):

    import sunburst_navigator as sn

    sunburst_svg = sn.get_sunburst_svg(driver, wait)
    grid = sn.read_grid(driver, sunburst_svg)          # also saves JSON
    sn.click_badge(driver, wait, unit=1, session=2, badge=1)
    sn.process_in_progress_sessions(driver, wait, grid)
"""

import json
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    StaleElementReferenceException,
)


# Stable: matches div.sunburst-wrapper > svg regardless of how deep the page
# nests it (unlike an absolute XPath, which broke depending on navigation
# route).
SUNBURST_SVG_CSS = ".sunburst-wrapper svg"

NUM_UNITS = 5
NUM_SESSIONS = 12
NUM_BADGES = 2

# Which (Unit, Session, Badge) to explicitly navigate to and click as a
# one-off targeted step. Badge 1 = SLO 1, Badge 2 = SLO 2.
TARGET_UNIT = 1
TARGET_SESSION = 2
TARGET_BADGE = 1

FILL_STATUS = {
    "rgb(26, 188, 156)": "Completed",
    "rgb(247, 183, 49)": "In Progress",
    "rgb(252, 92, 101)": "Not Started",
}


def unit_g_index(unit: int) -> int:
    return unit + 1


def session_g_index(unit: int, session: int) -> int:
    return 6 + (unit - 1) * NUM_SESSIONS + session


def session_xpath(unit: int, session: int) -> str:
    """Relative XPath (from the sunburst <svg> element) for a session's own
    arc. Kept for reference/inspection; clicking goes through CLICK_GROUP_JS
    instead (see below), since Selenium's XPath evaluator was found to
    disagree with the live DOM unpredictably."""
    idx = session_g_index(unit, session)
    return f".//g[{idx}]/path[1]"


def badge_g_index(unit: int, session: int, badge: int) -> int:
    return 66 + (unit - 1) * NUM_SESSIONS * NUM_BADGES + (session - 1) * NUM_BADGES + badge


def badge_xpath(unit: int, session: int, badge: int) -> str:
    """Relative XPath (from the sunburst <svg> element) for a given
    (unit, session, badge) cell. Kept for reference/inspection; clicking
    goes through CLICK_GROUP_JS."""
    idx = badge_g_index(unit, session, badge)
    return f".//g[{idx}]/path[1]"


# Reads every badge cell directly from the DOM using the confirmed index
# formula, given the sunburst <svg> element.
READ_GRID_JS = r"""
(svg) => {
  const groups = Array.from(svg.children).filter(c => c.tagName === 'g');
  function fillOf(g) {
    const p = g.querySelector('path.sunburst-main-arc');
    return p ? (p.style.fill || p.getAttribute('fill')) : null;
  }
  function textOf(g) {
    const t = g.querySelector('text');
    return t ? t.textContent.trim() : null;
  }
  const results = [];
  for (let unit = 1; unit <= 5; unit++) {
    for (let session = 1; session <= 12; session++) {
      for (let badge = 1; badge <= 2; badge++) {
        const idx = 66 + (unit - 1) * 24 + (session - 1) * 2 + badge;
        const g = groups[idx - 1];
        results.push({
          unit, session, badge, gIndex: idx,
          exists: !!g,
          fill: g ? fillOf(g) : null,
          text: g ? textOf(g) : null,
        });
      }
    }
  }
  return { totalGroups: groups.length, cells: results };
}
"""


# Clicks a top-level <g> by its 1-based position among svg.children whose
# tag is 'g' -- the EXACT SAME indexing method as READ_GRID_JS (proven
# correct: it matched the real on-screen statuses). Returns diagnostics
# (whether the index existed, how many <g> groups were actually present,
# and that group's label text) so a failure can be debugged instead of
# just raising blind.
CLICK_GROUP_JS = r"""
(svg, gIndex) => {
  const groups = Array.from(svg.children).filter(c => c.tagName === 'g');
  const g = groups[gIndex - 1];
  if (!g) {
    return { ok: false, totalGroups: groups.length, text: null };
  }
  const target = g.querySelector('path') || g;
  const rect = target.getBoundingClientRect();
  const opts = {
    bubbles: true, cancelable: true, view: window,
    clientX: rect.x + rect.width / 2, clientY: rect.y + rect.height / 2,
  };
  target.dispatchEvent(new MouseEvent('mousedown', opts));
  target.dispatchEvent(new MouseEvent('mouseup', opts));
  target.dispatchEvent(new MouseEvent('click', opts));
  const t = g.querySelector('text');
  return { ok: true, totalGroups: groups.length, text: t ? t.textContent.trim() : null };
}
"""


# Locates a top-level <g> by the same indexing as CLICK_GROUP_JS, but
# instead of dispatching a synthetic MouseEvent itself, returns the actual
# clickable DOM element. Selenium wraps a returned DOM node as a real
# WebElement, which click_group() then clicks with ActionChains -- a
# genuine, OS-level, "trusted" click. CLICK_GROUP_JS's synthetic
# dispatchEvent() was confirmed (via diag showing ok=True, correct text,
# correct totalGroups every time) to be finding the right element every
# time, but the chart's click handling was silently ignoring it -- almost
# certainly because it checks event.isTrusted, which is only true for a
# real click, never one created via `new MouseEvent()` in JS.
GET_GROUP_ELEMENT_JS = r"""
(svg, gIndex) => {
  const groups = Array.from(svg.children).filter(c => c.tagName === 'g');
  const g = groups[gIndex - 1];
  if (!g) {
    return { ok: false, totalGroups: groups.length, text: null, element: null };
  }
  const target = g.querySelector('path') || g;
  const t = g.querySelector('text');
  return { ok: true, totalGroups: groups.length, text: t ? t.textContent.trim() : null, element: target };
}
"""


# Grabs the smallest ancestor of a given element (e.g. the SUBMIT button)
# whose visible text includes both markers, i.e. the whole question card
# (header + stem + options), and separately returns its radio inputs so
# option N can be clicked reliably in document order.
QUESTION_CARD_JS = r"""
(submitBtn) => {
  let el = submitBtn;
  while (el && !(el.innerText && el.innerText.includes('Question') && el.innerText.includes('SUBMIT'))) {
    el = el.parentElement;
  }
  if (!el) return null;
  const radios = Array.from(el.querySelectorAll('input[type="radio"]'));
  return { text: el.innerText, radioCount: radios.length };
}
"""


def in_progress_sessions(grid: dict) -> list:
    """Unique (unit, session) pairs where at least one badge is In Progress,
    sorted by unit then session."""
    seen = set()
    for cell in grid.get("cells", []):
        if FILL_STATUS.get(cell["fill"]) == "In Progress":
            seen.add((cell["unit"], cell["session"]))
    return sorted(seen)


def get_sunburst_svg(driver, wait):
    """Re-fetches the sunburst <svg> fresh. Must be called again after any
    action that could cause the chart to re-render (e.g. after submitting a
    question), since cached <g> children can drift out of sync with the
    live DOM (indices that existed before a submit may no longer exist
    after it)."""
    return wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, SUNBURST_SVG_CSS)))


CENTER_XPATH = ".//g[1]/path[1]"
EXPECTED_TOTAL_GROUPS = 186


def group_count(driver, sunburst_svg) -> int:
    """Counts only <g>-tag children, matching the exact filter READ_GRID_JS
    and CLICK_GROUP_JS use for their indexing. Counting ALL children
    (including any non-<g> siblings) would silently disagree with the
    g[N] index space our formulas operate in."""
    return driver.execute_script(
        "return Array.from(arguments[0].children).filter(c => c.tagName === 'g').length;",
        sunburst_svg,
    )


def ensure_full_view(driver, wait):
    """Clicking a badge appears to zoom the sunburst into that slice, which
    shrinks the <svg>'s <g> children to just the zoomed subtree -- so a
    previously-valid g[n] index can stop existing. This clicks the center
    circle (the reset-zoom target in most sunburst libraries) until the
    full 186-group view is back, then returns a fresh svg handle."""
    sunburst_svg = get_sunburst_svg(driver, wait)
    for attempt in range(4):
        count = group_count(driver, sunburst_svg)
        if count == EXPECTED_TOTAL_GROUPS:
            return sunburst_svg
        try:
            center = sunburst_svg.find_element(By.XPATH, CENTER_XPATH)
            driver.execute_script("arguments[0].click();", center)
        except (NoSuchElementException, StaleElementReferenceException):
            pass
        time.sleep(1.5)
        sunburst_svg = get_sunburst_svg(driver, wait)

    print(f"  Warning: chart still shows {group_count(driver, sunburst_svg)} "
          f"groups (expected {EXPECTED_TOTAL_GROUPS}) after trying to reset zoom.")
    return sunburst_svg


def read_grid(driver, sunburst_svg, save_path: str = "sunburst_status_grid.json") -> dict:
    """Reads the full 5x12x2 status grid via READ_GRID_JS, prints it,
    saves it to save_path (skip saving by passing save_path=None), and
    returns the grid dict."""
    grid = driver.execute_script(f"return ({READ_GRID_JS})(arguments[0]);", sunburst_svg)

    print(f"\nTotal <g> groups: {grid.get('totalGroups')} (expected {EXPECTED_TOTAL_GROUPS})")
    print("\nStatus grid (Unit / Session / Badge -> status):")
    for cell in grid.get("cells", []):
        status = FILL_STATUS.get(cell["fill"], cell["fill"])
        print(f"  Unit {cell['unit']} / S{cell['session']} / badge{cell['badge']} "
              f"(g[{cell['gIndex']}]): {status}")

    if save_path:
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(grid, f, indent=2)
        print(f"\nFull grid saved to {save_path}")

    return grid


def click_group(driver, wait, g_index: int):
    """Clicks a top-level <g> by its 1-based g-index (in the space defined
    by unit_g_index / session_g_index / badge_g_index above).

    Uses GET_GROUP_ELEMENT_JS to locate the element (same proven-correct
    indexing as READ_GRID_JS/CLICK_GROUP_JS), then clicks it with a real
    Selenium ActionChains click rather than a JS-dispatched synthetic
    MouseEvent -- the synthetic-event approach was reliably finding the
    right element (confirmed via diagnostics) but the chart never reacted
    to it, most likely because it checks event.isTrusted.

    Returns a diagnostics dict: {'ok': bool, 'totalGroups': int, 'text':
    str|None}, plus 'clickError' if the real click itself raised."""
    sunburst_svg = ensure_full_view(driver, wait)
    result = driver.execute_script(
        f"return ({GET_GROUP_ELEMENT_JS})(arguments[0], arguments[1]);",
        sunburst_svg, g_index,
    )
    diag = {
        "ok": bool(result and result.get("ok")),
        "totalGroups": result.get("totalGroups") if result else None,
        "text": result.get("text") if result else None,
    }
    if not diag["ok"] or not result.get("element"):
        return diag

    element = result["element"]
    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
            element,
        )
        ActionChains(driver).move_to_element(element).click().perform()
    except Exception as exc:  # noqa: BLE001
        diag["clickError"] = f"{exc.__class__.__name__}: {exc}"

    return diag


def wait_for_session_panel(wait, session: int) -> bool:
    header_xpath = (
        f"//*[contains(normalize-space(text()), 'Learning Unit') and "
        f"contains(normalize-space(text()), 'Session') and "
        f"contains(normalize-space(text()), '{session}')]"
    )
    try:
        wait.until(EC.presence_of_element_located((By.XPATH, header_xpath)))
        return True
    except TimeoutException:
        return False


OPEN_SESSION_MAX_ATTEMPTS = 4


def open_session(driver, wait, unit: int, session: int) -> bool:
    """Clicks a session's own arc (not a status badge) to reveal its detail
    panel below the chart, via CLICK_GROUP_JS.

    This function NEVER raises. It retries up to OPEN_SESSION_MAX_ATTEMPTS
    times (re-fetching the svg and re-resetting zoom each time), printing
    diagnostics on every failure, and if every attempt fails it prints why
    and returns False so the caller can skip this one session and move on
    to the rest -- instead of one bad click target crashing the whole run."""
    idx = session_g_index(unit, session)

    last_error = None
    last_diag = None
    for attempt in range(1, OPEN_SESSION_MAX_ATTEMPTS + 1):
        try:
            diag = click_group(driver, wait, idx)
            last_diag = diag
            if not diag or not diag.get("ok"):
                total = diag.get("totalGroups") if diag else "?"
                raise NoSuchElementException(
                    f"g-index {idx} not found (svg currently reports {total} <g> children)"
                )

            if wait_for_session_panel(wait, session):
                return True
            raise TimeoutException("detail panel header did not appear")

        except (NoSuchElementException, StaleElementReferenceException, TimeoutException) as exc:
            last_error = exc
            print(f"  [Unit {unit} / S{session}] attempt {attempt}/{OPEN_SESSION_MAX_ATTEMPTS} "
                  f"failed to open ({exc.__class__.__name__}: {exc}). diag={last_diag}. Retrying...")
            time.sleep(2)

    print(f"  Giving up on Unit {unit} / S{session} after {OPEN_SESSION_MAX_ATTEMPTS} attempts "
          f"({last_error.__class__.__name__ if last_error else 'unknown error'}). "
          f"Last diag={last_diag}. Skipping this session.")
    return False


def click_badge(driver, wait, unit: int, session: int, badge: int) -> bool:
    """Clicks a specific status badge (SLO 1 = badge 1, SLO 2 = badge 2)
    directly, via CLICK_GROUP_JS. Prints diagnostics either way. Returns
    True if the click landed and the session's detail panel is showing."""
    idx = badge_g_index(unit, session, badge)
    print(f"Clicking Unit {unit} / Session {session} / Badge {badge} (g[{idx}])...")
    diag = click_group(driver, wait, idx)
    print(f"  diag={diag}")

    if not diag or not diag.get("ok"):
        total = diag.get("totalGroups") if diag else "?"
        print(f"  Could not find g[{idx}] (svg currently reports {total} <g> children). "
              f"Nothing was clicked.")
        return False

    if wait_for_session_panel(wait, session):
        print("  Detail panel opened.")
        return True

    print("  Clicked, but could not confirm the detail panel opened.")
    return False


def expand_learning_practice(driver, wait, slo_index: int) -> bool:
    """slo_index: 1 for SLO 1, 2 for SLO 2. Clicks that SLO's 'Learning
    Practice' row to expand it. Returns True on success."""
    practice_spans = driver.find_elements(
        By.XPATH, "//span[normalize-space(text())='Learning Practice']"
    )
    if len(practice_spans) < slo_index:
        print(f"  Could not find 'Learning Practice' row #{slo_index}.")
        return False
    practice_spans[slo_index - 1].click()
    time.sleep(1)
    return True


def ensure_questions_generated(driver, wait) -> None:
    """If 'REFRESH NEW QUESTIONS' is showing (no questions generated yet),
    click it once and wait for the Q-number buttons to appear."""
    try:
        refresh_btn = driver.find_element(
            By.XPATH, "//button[contains(., 'REFRESH NEW QUESTIONS')]"
        )
        refresh_btn.click()
        wait.until(EC.presence_of_element_located(
            (By.XPATH, "//button[normalize-space(text())='Q 1']")
        ))
        time.sleep(1)
    except NoSuchElementException:
        pass  # Questions already generated.


def answer_questions_interactively(driver, wait, unit: int, session: int, slo_index: int) -> None:
    q_buttons = driver.find_elements(By.XPATH, "//button[starts-with(normalize-space(text()), 'Q ')]")
    total = len(q_buttons)
    if total == 0:
        print(f"  No question buttons found for Unit {unit} / S{session} / SLO{slo_index}.")
        return

    for q in range(1, total + 1):
        try:
            q_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, f"//button[normalize-space(text())='Q {q}']")
            ))
            q_btn.click()
            time.sleep(1)

            submit_btn = wait.until(EC.presence_of_element_located(
                (By.XPATH, "//button[normalize-space(text())='SUBMIT']")
            ))
            card = driver.execute_script(f"return ({QUESTION_CARD_JS})(arguments[0]);", submit_btn)
            if not card:
                print(f"  Could not read question card for Q{q}.")
                continue

            print(f"\n--- Unit {unit} / S{session} / SLO{slo_index} / Q{q} ---")
            print(card["text"])

            radio_count = card["radioCount"]
            if radio_count == 0:
                print("  No options found for this question -- skipping.")
                continue

            choice = input(
                f"Select option 1-{radio_count} (or 's' to skip, 'q' to stop this SLO): "
            ).strip().lower()

            if choice == "q":
                return
            if choice == "s" or not choice:
                continue

            try:
                choice_num = int(choice)
                if not (1 <= choice_num <= radio_count):
                    raise ValueError
            except ValueError:
                print("  Invalid input, skipping this question.")
                continue

            radios = submit_btn.find_element(
                By.XPATH,
                "./ancestor::*[.//input[@type='radio']][1]"
            ).find_elements(By.XPATH, ".//input[@type='radio']")
            if len(radios) != radio_count:
                # Fall back to a page-wide radio lookup if ancestor scoping
                # picked up a different count than JS reported.
                radios = driver.find_elements(By.XPATH, "//input[@type='radio']")

            driver.execute_script("arguments[0].click();", radios[choice_num - 1])
            time.sleep(0.5)

            submit_btn = driver.find_element(
                By.XPATH, "//button[normalize-space(text())='SUBMIT']"
            )
            submit_btn.click()
            time.sleep(1)
            print(f"  Submitted option {choice_num} for Q{q}.")

        except (TimeoutException, StaleElementReferenceException, NoSuchElementException) as exc:
            print(f"  Skipped Q{q} due to error: {exc}")
            continue


def process_in_progress_sessions(driver, wait, grid: dict) -> None:
    sessions = in_progress_sessions(grid)
    print(f"\nFound {len(sessions)} in-progress session(s): {sessions}")

    for unit, session in sessions:
        print(f"\n=== Unit {unit} / Session {session} ===")
        if not open_session(driver, wait, unit, session):
            continue

        for slo_index in (1, 2):
            print(f"\n-- SLO {slo_index} --")
            if not expand_learning_practice(driver, wait, slo_index):
                continue
            ensure_questions_generated(driver, wait)
            answer_questions_interactively(driver, wait, unit, session, slo_index)


def navigate_all_sessions(driver, wait) -> None:
    """Walks every Unit (1-5) / Session (1-12) in order -- not just the
    In Progress ones -- opening each session's detail panel in turn via
    open_session(). Use this for a full sweep/verification pass over the
    whole chart, e.g. to confirm every session is reachable, rather than
    process_in_progress_sessions()'s targeted pass.

    Never raises: each session's failure/skip is handled by open_session()
    itself (it already retries and prints diagnostics), so one bad session
    doesn't stop the sweep. Returns nothing; prints progress as it goes."""
    results = []

    for unit in range(1, NUM_UNITS + 1):
        for session in range(1, NUM_SESSIONS + 1):
            print(f"\n=== Navigating to Unit {unit} / Session {session} ===")
            opened = open_session(driver, wait, unit, session)
            results.append((unit, session, opened))

            if opened:
                # Reset back to the full chart view before moving to the
                # next session, so the next open_session() call isn't
                # starting from a zoomed-in/expanded state.
                ensure_full_view(driver, wait)
                time.sleep(1)

    opened_count = sum(1 for _, _, ok in results if ok)
    print(f"\nNavigated {opened_count}/{len(results)} sessions successfully.")
    failed = [(u, s) for u, s, ok in results if not ok]
    if failed:
        print(f"Failed to open: {failed}")


def find_first_not_completed(grid: dict):
    """Returns the (unit, session) of the first session, in Unit/Session
    order, where at least one of its two badges is not Completed. Returns
    None if every session is Completed."""
    for cell in sorted(grid.get("cells", []), key=lambda c: (c["unit"], c["session"], c["badge"])):
        if FILL_STATUS.get(cell["fill"]) != "Completed":
            return (cell["unit"], cell["session"])
    return None


def open_first_not_completed(driver, wait):
    """Reads the full status grid, finds the first not-completed (unit,
    session) in Unit/Session order, and clicks that session's arc (via
    open_session) to open its detail panel. Returns the (unit, session)
    tuple if it opened successfully, otherwise None."""
    sunburst_svg = ensure_full_view(driver, wait)
    grid = read_grid(driver, sunburst_svg)
    target = find_first_not_completed(grid)
    if target is None:
        print("\nEvery session is Completed -- nothing to open.")
        return None

    unit, session = target
    print(f"\nFirst not-completed session: Unit {unit} / Session {session}. Opening it...")
    if open_session(driver, wait, unit, session):
        return target

    print(f"  Could not open Unit {unit} / Session {session}.")
    return None
