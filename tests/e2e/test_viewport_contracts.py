from __future__ import annotations

import os

import pytest

from tests.support.viewport_contracts import VIEWPORT_ASSERTIONS_JS


pytestmark = pytest.mark.e2e


def test_workbench_viewport_contracts(page) -> None:
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(os.environ["BIYU_QA_BASE_URL"] + "/workbench.html")
    page.wait_for_load_state("networkidle", timeout=10_000)
    result = page.evaluate(
        """({checker}) => {{
          const rules = {checker};
          const menu = document.querySelector('#workbench-more-menu');
          return {{
            horizontal: rules.noHorizontalOverflow(),
            menu: menu ? rules.overlayWithinViewport(menu) : true,
            text: [...document.querySelectorAll('body *')].filter(el => el.children.length === 0 && el.textContent.trim()).every(el => rules.textNotClipped(el)),
          }};
        }}""".format(checker=VIEWPORT_ASSERTIONS_JS),
    )
    assert result == {"horizontal": True, "menu": True, "text": True}
