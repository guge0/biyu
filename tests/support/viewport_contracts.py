"""Machine-checkable author-facing viewport rules from the 2026-08-24 ruling."""

VIEWPORT_ASSERTIONS_JS = r"""
({
  noHorizontalOverflow() {
    return document.documentElement.scrollWidth <= window.innerWidth;
  },
  overlayWithinViewport(el) {
    const r = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    const canScroll = /(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight;
    return r.left >= 0 && r.right <= innerWidth &&
      (r.top >= 0 && r.bottom <= innerHeight || canScroll);
  },
  textNotClipped(el) {
    return el.scrollWidth <= el.clientWidth + 1;
  },
  stickyHeaderAndFirstRequired(form) {
    const header = form.querySelector('h3');
    const firstRequired = form.querySelector('label:first-of-type');
    if (!header || !firstRequired) return false;
    const hr = header.getBoundingClientRect();
    const fr = firstRequired.getBoundingClientRect();
    return hr.top >= 0 && hr.bottom <= innerHeight && fr.top >= 0 && fr.bottom <= innerHeight;
  }
})
"""


def required_viewport_assertion_names() -> tuple[str, ...]:
    return (
        "noHorizontalOverflow",
        "overlayWithinViewport",
        "textNotClipped",
        "stickyHeaderAndFirstRequired",
    )
